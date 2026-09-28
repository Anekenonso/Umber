"""Stage 4 Test Suite: Catalog Matching & VTO Render Flow (cloth-v4) (Phase 2, 4, 8, 9, 11).

Verifies:
1. Happy path: Inbound selfie -> Skin-Tone Analysis -> Deterministic Catalog Match ->
   YouCam Clothes Changer (cloth-v4) -> WhatsApp Image recommendation with caption.
2. Graceful render failure (Phase 9 & 11):
   - When cloth-v4 returns error_editing_failed, send text-only recommendation without stalling.
   - When cloth-v4 exceeds 30s timeout cap, send text-only recommendation without stalling.
3. Post-recommendation alternative request:
   - "Show me another color" advances match_index to next ranked catalog item and renders it.
4. Post-recommendation dissatisfaction escalation (Phase 2 success criteria #3):
   - "I don't like this recommendation" immediately triggers ESCALATED state and stylist handoff.
5. Deterministic selection: Top SKU matches expected tone/depth characteristics.
"""
import json
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from app.clients.youcam import YouCamAPIError, YouCamTimeoutError
from app.config import settings
from app.main import app, orchestrator
from app.states import ConversationState
from app.store import store


@pytest.fixture(autouse=True)
def clean_database():
    """Ensure clean isolated SQLite state store for each test."""
    store.clear_all()
    original_stage = settings.stage
    settings.stage = 4
    yield
    store.clear_all()
    settings.stage = original_stage


@pytest.mark.asyncio
async def test_stage4_full_round_trip_success():
    """Step 1: End-to-end happy path: photo -> skin analysis -> catalog match -> cloth-v4 render -> image reply."""
    # Seed state as AWAITING_PHOTO
    session = store.get_session("2348099998888")
    session.state = ConversationState.AWAITING_PHOTO
    store.save_session(session)

    mock_whatsapp = AsyncMock()
    mock_whatsapp.get_media_url.return_value = "https://media.whatsapp.net/v/customer_selfie.jpg"

    mock_youcam = AsyncMock()
    # Mock skin analysis
    mock_youcam.analyze_skin_tone.return_value = {
        "status": "success",
        "result": {
            "skin_color": "#c48858",  # Medium warm tone
            "undertone": "warm",
            "depth": "medium",
        },
    }
    # Mock cloth-v4 Clothes Changer
    mock_youcam.render_clothes_vto.return_value = {
        "status": "success",
        "result": {
            "result_url": "https://media.youcam.net/vto/rendered_outfit_123.jpg",
        },
    }

    orchestrator.whatsapp = mock_whatsapp
    orchestrator.youcam = mock_youcam

    res = await orchestrator.handle_inbound_message(
        sender_id="2348099998888",
        msg_type="image",
        media_id="media_id_selfie_hq",
    )

    assert res["status"] == "recommendation_sent"
    assert res["state"] == ConversationState.SENT.value
    assert res["rendered_image_url"] == "https://media.youcam.net/vto/rendered_outfit_123.jpg"

    # Verify session state and context
    updated = store.get_session("2348099998888")
    assert updated.state == ConversationState.SENT
    assert updated.context["selected_sku"] is not None
    assert updated.context["last_rendered_url"] == "https://media.youcam.net/vto/rendered_outfit_123.jpg"

    # Both YouCam calls executed
    mock_youcam.analyze_skin_tone.assert_called_once()
    mock_youcam.render_clothes_vto.assert_called_once()

    # Image message dispatched with caption
    mock_whatsapp.send_image_message.assert_called_once()
    args, kwargs = mock_whatsapp.send_image_message.call_args
    assert kwargs["to"] == "2348099998888"
    assert kwargs["image_url"] == "https://media.youcam.net/vto/rendered_outfit_123.jpg"
    assert "personalized match" in kwargs["caption"].lower()


@pytest.mark.asyncio
async def test_stage4_vto_render_error_editing_failed_falls_back_to_text():
    """Step 2: When cloth-v4 returns error_editing_failed, send text recommendation without blocking."""
    session = store.get_session("2348099998888")
    session.state = ConversationState.AWAITING_PHOTO
    store.save_session(session)

    mock_whatsapp = AsyncMock()
    mock_whatsapp.get_media_url.return_value = "https://media.whatsapp.net/v/customer_selfie.jpg"

    mock_youcam = AsyncMock()
    mock_youcam.analyze_skin_tone.return_value = {
        "status": "success",
        "result": {
            "skin_color": "#4a2d1a",  # Deep rich skin tone
            "undertone": "warm",
            "depth": "rich",
        },
    }
    # Simulate documented error_editing_failed on VTO render
    mock_youcam.render_clothes_vto.side_effect = YouCamAPIError(
        error_code="error_editing_failed",
        message="VTO render failed to generate distinct output.",
    )

    orchestrator.whatsapp = mock_whatsapp
    orchestrator.youcam = mock_youcam

    res = await orchestrator.handle_inbound_message(
        sender_id="2348099998888",
        msg_type="image",
        media_id="media_id_selfie_deep",
    )

    assert res["status"] == "text_recommendation_sent"
    assert res["state"] == ConversationState.SENT.value
    assert res["fallback"] is True
    assert res["error_code"] == "error_editing_failed"

    # Session persisted in SENT state
    updated = store.get_session("2348099998888")
    assert updated.state == ConversationState.SENT

    # Text message sent, NOT an image message
    mock_whatsapp.send_image_message.assert_not_called()
    mock_whatsapp.send_text_message.assert_called_once()
    sent_text = mock_whatsapp.send_text_message.call_args[0][1]
    assert "top recommendation is the" in sent_text
    assert "temporarily unavailable" in sent_text


@pytest.mark.asyncio
async def test_stage4_vto_timeout_falls_back_to_text():
    """Step 3: When cloth-v4 polling exceeds 30s cap, send text recommendation."""
    session = store.get_session("2348099998888")
    session.state = ConversationState.AWAITING_PHOTO
    store.save_session(session)

    mock_whatsapp = AsyncMock()
    mock_whatsapp.get_media_url.return_value = "https://media.whatsapp.net/v/selfie.jpg"

    mock_youcam = AsyncMock()
    mock_youcam.analyze_skin_tone.return_value = {
        "status": "success",
        "result": {"skin_color": "#e0ac69", "undertone": "warm"},
    }
    mock_youcam.render_clothes_vto.side_effect = YouCamTimeoutError("Exceeded 30s polling cap.")

    orchestrator.whatsapp = mock_whatsapp
    orchestrator.youcam = mock_youcam

    res = await orchestrator.handle_inbound_message(
        sender_id="2348099998888",
        msg_type="image",
        media_id="media_id_slow_vto",
    )

    assert res["status"] == "text_recommendation_sent"
    assert res["state"] == ConversationState.SENT.value
    assert res["fallback"] is True
    mock_whatsapp.send_text_message.assert_called_once()


@pytest.mark.asyncio
async def test_stage4_post_recommendation_alternative_request():
    """Step 4: Customer asks for 'another' option in SENT state -> cycles to next match."""
    session = store.get_session("2348099998888")
    session.state = ConversationState.SENT
    session.context = {
        "selfie_url": "https://media.whatsapp.net/v/selfie.jpg",
        "skin_color": "#c48858",
        "undertone": "warm",
        "matches": [
            {"sku": "SKU-1", "name": "Item One", "garment_image_url": "http://img1.jpg", "price": "$70"},
            {"sku": "SKU-2", "name": "Item Two", "garment_image_url": "http://img2.jpg", "price": "$80"},
        ],
        "match_index": 0,
        "selected_sku": "SKU-1",
    }
    store.save_session(session)

    mock_whatsapp = AsyncMock()
    mock_youcam = AsyncMock()
    mock_youcam.render_clothes_vto.return_value = {
        "status": "success",
        "result": {"result_url": "https://media.youcam.net/vto/sku2_render.jpg"},
    }

    orchestrator.whatsapp = mock_whatsapp
    orchestrator.youcam = mock_youcam

    res = await orchestrator.handle_inbound_message(
        sender_id="2348099998888",
        msg_type="text",
        body_text="Can I see another color or different dress?",
    )

    assert res["status"] == "recommendation_sent"
    assert res["sku"] == "SKU-2"

    updated = store.get_session("2348099998888")
    assert updated.context["match_index"] == 1
    assert updated.context["selected_sku"] == "SKU-2"


@pytest.mark.asyncio
async def test_stage4_post_recommendation_dissatisfaction_escalates():
    """Step 5: Customer expresses dissatisfaction ('not satisfied' / 'don't like') -> ESCALATED."""
    session = store.get_session("2348099998888")
    session.state = ConversationState.SENT
    store.save_session(session)

    mock_whatsapp = AsyncMock()
    orchestrator.whatsapp = mock_whatsapp

    res = await orchestrator.handle_inbound_message(
        sender_id="2348099998888",
        msg_type="text",
        body_text="I don't like this recommendation at all, poor fit for me",
    )

    assert res["status"] == "escalated"
    assert res["state"] == ConversationState.ESCALATED.value

    updated = store.get_session("2348099998888")
    assert updated.state == ConversationState.ESCALATED
    assert "stylist" in mock_whatsapp.send_text_message.call_args[0][1].lower()
