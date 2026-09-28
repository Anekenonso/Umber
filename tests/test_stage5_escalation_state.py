"""Stage 5 Test Suite: Escalation Rules & State Persistence Hardening (Phase 2, 6, 9, 25).

Verifies:
1. Trigger 1 - Explicit human agent requests:
   - "I want to speak with a human agent" -> State ESCALATED, stores reason and timestamp.
2. Trigger 2 - Inbound complaint / dispute:
   - "I got charged twice and package arrived damaged" -> State ESCALATED.
3. Trigger 3 - Post-recommendation dissatisfaction:
   - Customer in SENT state says "I don't like this recommendation, ugly fit" -> State ESCALATED.
4. Escalation lockout (Phase 2 #4):
   - Once in ESCALATED state, further messages do NOT trigger YouCam calls, do not reset state,
     and return a friendly holding message.
5. State persistence across restarts:
   - Writing to SQLite, creating a new store instance with the same database file,
     and confirming session state, retries, and context remain intact.
6. Staff escalation management:
   - Listing open escalated sessions.
   - Resolving an escalation and restoring session to active state.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, orchestrator
from app.states import ConversationState, EscalationReason
from app.store import ConversationStore, store

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_database():
    """Ensure clean isolated SQLite state store for each test."""
    store.clear_all()
    original_stage = settings.stage
    settings.stage = 5
    yield
    store.clear_all()
    settings.stage = original_stage


@pytest.mark.asyncio
async def test_trigger_1_explicit_human_agent_escalation():
    """Trigger 1: Explicit human request deterministically escalates."""
    mock_whatsapp = AsyncMock()
    orchestrator.whatsapp = mock_whatsapp

    res = await orchestrator.handle_inbound_message(
        sender_id="2348011223344",
        msg_type="text",
        body_text="Please connect me to a human representative right now",
    )

    assert res["status"] == "escalated"
    assert res["state"] == ConversationState.ESCALATED.value

    # Check database persistence
    session = store.get_session("2348011223344")
    assert session.state == ConversationState.ESCALATED

    # Verify message sent to customer
    mock_whatsapp.send_text_message.assert_called_once()
    assert "connecting you with a member" in mock_whatsapp.send_text_message.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_trigger_2_complaint_and_billing_escalation():
    """Trigger 2: Inbound complaint or billing dispute deterministically escalates."""
    mock_whatsapp = AsyncMock()
    orchestrator.whatsapp = mock_whatsapp

    res = await orchestrator.handle_inbound_message(
        sender_id="2348011223344",
        msg_type="text",
        body_text="I was charged twice and my order arrived damaged! refund my money!",
    )

    assert res["status"] == "escalated"
    assert res["state"] == ConversationState.ESCALATED.value

    session = store.get_session("2348011223344")
    assert session.state == ConversationState.ESCALATED


@pytest.mark.asyncio
async def test_trigger_3_post_recommendation_dissatisfaction():
    """Trigger 3: Post-recommendation dissatisfaction in SENT state escalates."""
    session = store.get_session("2348011223344")
    session.state = ConversationState.SENT
    store.save_session(session)

    mock_whatsapp = AsyncMock()
    orchestrator.whatsapp = mock_whatsapp

    res = await orchestrator.handle_inbound_message(
        sender_id="2348011223344",
        msg_type="text",
        body_text="I don't like this recommendation, this shade does not suit me at all",
    )

    assert res["status"] == "escalated"
    assert res["state"] == ConversationState.ESCALATED.value

    session = store.get_session("2348011223344")
    assert session.state == ConversationState.ESCALATED
    assert "stylist" in mock_whatsapp.send_text_message.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_escalation_lockout_prevents_api_calls_and_state_reset():
    """Phase 2 #4: Escalated session prevents bot from making API calls or resetting state."""
    session = store.get_session("2348011223344")
    session.state = ConversationState.ESCALATED
    store.save_session(session)

    mock_whatsapp = AsyncMock()
    mock_youcam = AsyncMock()
    orchestrator.whatsapp = mock_whatsapp
    orchestrator.youcam = mock_youcam

    # 1. Customer sends photo while already escalated
    res_photo = await orchestrator.handle_inbound_message(
        sender_id="2348011223344",
        msg_type="image",
        media_id="media_test_123",
    )
    assert res_photo["status"] == "escalated_lockout"
    assert res_photo["state"] == ConversationState.ESCALATED.value
    # No YouCam API units burned!
    mock_youcam.analyze_skin_tone.assert_not_called()
    mock_youcam.render_clothes_vto.assert_not_called()

    # 2. Customer sends general message while already escalated
    mock_whatsapp.reset_mock()
    res_text = await orchestrator.handle_inbound_message(
        sender_id="2348011223344",
        msg_type="text",
        body_text="what time do you close today?",
    )
    assert res_text["status"] == "escalated_lockout"
    assert res_text["state"] == ConversationState.ESCALATED.value
    # Holding message dispatched
    mock_whatsapp.send_text_message.assert_called_once()
    assert "representative is reviewing" in mock_whatsapp.send_text_message.call_args[0][1].lower()


def test_sqlite_state_persistence_across_process_restarts(tmp_path):
    """Phase 25: Verify state survives process restarts with SQLite."""
    db_file = tmp_path / "test_persist.db"
    store1 = ConversationStore(db_path=db_file)

    # Write in instance 1
    session1 = store1.get_session("2348099887766")
    session1.state = ConversationState.MATCHING
    session1.photo_retries = 1
    session1.context = {"skin_color": "#a86b3e", "undertone": "warm", "selected_sku": "UMB-DRS-01"}
    store1.save_session(session1)

    # Read back in a brand new store instance pointing to same file
    store2 = ConversationStore(db_path=db_file)
    session2 = store2.get_session("2348099887766")

    assert session2.state == ConversationState.MATCHING
    assert session2.photo_retries == 1
    assert session2.context["skin_color"] == "#a86b3e"
    assert session2.context["selected_sku"] == "UMB-DRS-01"


def test_staff_escalation_listing_and_resolution_endpoints():
    """Verify staff endpoints for listing open escalations and resolving them."""
    # Seed an escalated session
    store.escalate_session("2348012345678", reason=EscalationReason.COMPLAINT_OR_DISPUTE.value)

    # 1. GET /sessions/escalations
    resp = client.get("/sessions/escalations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    escalated_ids = [e["sender_id"] for e in data["escalations"]]
    assert "2348012345678" in escalated_ids

    # 2. POST /sessions/{sender_id}/resolve
    resolve_resp = client.post("/sessions/2348012345678/resolve")
    assert resolve_resp.status_code == 200
    resolve_data = resolve_resp.json()
    assert resolve_data["status"] == "resolved"
    assert resolve_data["session"]["state"] == ConversationState.GENERAL_REPLY.value

    # 3. Confirm cleared in store
    refetched = store.get_session("2348012345678")
    assert refetched.state == ConversationState.GENERAL_REPLY
    assert refetched.escalation_reason is None
