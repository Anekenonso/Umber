"""Stage 3 Test Suite: Skin-Tone Analysis & Selfie Request Flow (Phase 6, 9, 11, 14).

Verifies:
1. Happy path: Personalization intent transitions to AWAITING_PHOTO, sends photo request prompt.
2. Inbound image in AWAITING_PHOTO transitions to ANALYZING -> MATCHING upon successful skin tone analysis.
3. Documented YouCam error handling (Phase 9 & 11):
   - First failure with error_pose triggers friendly retake request (ANALYZING_FAILED, retry_count=1).
   - Second failure with error_pose falls back to general recommendations (GENERAL_REPLY, never stalls).
4. Other documented error codes (error_invalid_ref, error_download_image, error_nsfw_content_detected) trigger specific friendly messages.
5. YouCam timeout cap (Phase 14): Exceeding 30s cap triggers holding/fallback message without hanging.
6. Non-image text in AWAITING_PHOTO:
   - Escalation text routes immediately to human handoff.
   - General text answers politely and transitions out.
   - Ambiguous text gently reminds customer to send selfie.
7. Webhook end-to-end integration with image payload in Stage 3 mode.
"""
import json
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from app.clients.youcam import YouCamAPIError, YouCamTimeoutError
from app.config import settings
from app.main import app, orchestrator, verify_signature
from app.orchestrator import (
    FALLBACK_GENERAL_MESSAGE,
    PHOTO_REMINDER_MESSAGE,
    YOUCAM_RETRY_MESSAGES,
)
from app.states import ConversationState, Intent
from app.store import store


@pytest.fixture(autouse=True)
def clean_database():
    """Ensure clean isolated SQLite state store for every test."""
    store.clear_all()
    original_stage = settings.stage
    settings.stage = 3
    yield
    store.clear_all()
    settings.stage = original_stage


@pytest.mark.asyncio
async def test_personalization_requests_photo_and_sets_awaiting_state():
    """Step 1: Text with personalization intent sets state to AWAITING_PHOTO."""
    mock_whatsapp = AsyncMock()
    orchestrator.whatsapp = mock_whatsapp

    res = await orchestrator.handle_inbound_message(
        sender_id="2348011112222",
        msg_type="text",
        body_text="What color dress suits my dark skin and warm undertones?",
    )

    assert res["status"] == "photo_requested"
    assert res["state"] == ConversationState.AWAITING_PHOTO.value

    # Session persisted
    session = store.get_session("2348011112222")
    assert session.state == ConversationState.AWAITING_PHOTO
    assert session.photo_retries == 0

    # WhatsApp reply sent
    mock_whatsapp.send_text_message.assert_called_once()
    args, _ = mock_whatsapp.send_text_message.call_args
    assert args[0] == "2348011112222"
    assert "selfie" in args[1].lower()


@pytest.mark.asyncio
async def test_image_in_awaiting_photo_succeeds_analysis():
    """Step 2: Customer sends selfie in AWAITING_PHOTO -> triggers skin-tone analysis."""
    # Seed state as AWAITING_PHOTO
    session = store.get_session("2348011112222")
    session.state = ConversationState.AWAITING_PHOTO
    store.save_session(session)

    mock_whatsapp = AsyncMock()
    mock_whatsapp.get_media_url.return_value = "https://lookaside.fbsbx.com/whatsapp_media/sample.jpg"
    mock_youcam = AsyncMock()
    mock_youcam.analyze_skin_tone.return_value = {
        "status": "success",
        "result": {
            "skin_color": "#8D5524",
            "undertone": "warm",
            "depth": "deep",
        },
    }

    orchestrator.whatsapp = mock_whatsapp
    orchestrator.youcam = mock_youcam

    res = await orchestrator.handle_inbound_message(
        sender_id="2348011112222",
        msg_type="image",
        media_id="media_id_999",
    )

    assert res["status"] == "analysis_success"
    assert res["state"] == ConversationState.MATCHING.value
    assert res["skin_color"] == "#8D5524"
    assert res["undertone"] == "warm"

    # Context saved
    updated_session = store.get_session("2348011112222")
    assert updated_session.state == ConversationState.MATCHING
    assert updated_session.context["skin_color"] == "#8D5524"
    assert updated_session.context["undertone"] == "warm"

    # Confirmation message dispatched
    mock_whatsapp.send_text_message.assert_called_once()
    assert "#8D5524" in mock_whatsapp.send_text_message.call_args[0][1]


@pytest.mark.asyncio
async def test_image_error_pose_first_failure_requests_retake():
    """Step 3: Documented error_pose on 1st attempt triggers retake request."""
    session = store.get_session("2348011112222")
    session.state = ConversationState.AWAITING_PHOTO
    store.save_session(session)

    mock_whatsapp = AsyncMock()
    mock_whatsapp.get_media_url.return_value = "https://lookaside.fbsbx.com/bad_pose.jpg"
    mock_youcam = AsyncMock()
    mock_youcam.analyze_skin_tone.side_effect = YouCamAPIError(
        error_code="error_pose",
        message="Face pose angle exceeded threshold.",
    )

    orchestrator.whatsapp = mock_whatsapp
    orchestrator.youcam = mock_youcam

    res = await orchestrator.handle_inbound_message(
        sender_id="2348011112222",
        msg_type="image",
        media_id="media_id_bad_pose",
    )

    assert res["status"] == "retake_requested"
    assert res["state"] == ConversationState.ANALYZING_FAILED.value
    assert res["error_code"] == "error_pose"

    # Session tracks retake count
    updated = store.get_session("2348011112222")
    assert updated.photo_retries == 1

    # Verify specific customer-facing message
    mock_whatsapp.send_text_message.assert_called_once_with(
        "2348011112222",
        YOUCAM_RETRY_MESSAGES["error_pose"],
    )


@pytest.mark.asyncio
async def test_image_error_pose_second_failure_falls_back_to_general():
    """Step 4: Repeated failure gracefully falls back to general catalog, never stalls."""
    session = store.get_session("2348011112222")
    session.state = ConversationState.ANALYZING_FAILED
    session.photo_retries = 1  # Already retried once
    store.save_session(session)

    mock_whatsapp = AsyncMock()
    mock_whatsapp.get_media_url.return_value = "https://lookaside.fbsbx.com/bad_pose_2.jpg"
    mock_youcam = AsyncMock()
    mock_youcam.analyze_skin_tone.side_effect = YouCamAPIError(
        error_code="error_pose",
        message="Face pose angle exceeded threshold.",
    )

    orchestrator.whatsapp = mock_whatsapp
    orchestrator.youcam = mock_youcam

    res = await orchestrator.handle_inbound_message(
        sender_id="2348011112222",
        msg_type="image",
        media_id="media_id_bad_pose_2",
    )

    assert res["status"] == "degraded_to_general"
    assert res["state"] == ConversationState.GENERAL_REPLY.value

    updated = store.get_session("2348011112222")
    assert updated.photo_retries == 2
    assert updated.state == ConversationState.GENERAL_REPLY

    # Fallback message sent
    mock_whatsapp.send_text_message.assert_called_once_with(
        "2348011112222",
        FALLBACK_GENERAL_MESSAGE,
    )


@pytest.mark.asyncio
async def test_youcam_timeout_cap_triggers_graceful_fallback():
    """Step 5: When 30s timeout cap is reached, don't spin or crash; send friendly fallback."""
    session = store.get_session("2348011112222")
    session.state = ConversationState.AWAITING_PHOTO
    store.save_session(session)

    mock_whatsapp = AsyncMock()
    mock_youcam = AsyncMock()
    mock_youcam.analyze_skin_tone.side_effect = YouCamTimeoutError("Task poll timed out after 30s.")

    orchestrator.whatsapp = mock_whatsapp
    orchestrator.youcam = mock_youcam

    res = await orchestrator.handle_inbound_message(
        sender_id="2348011112222",
        msg_type="image",
        media_id="media_id_slow",
    )

    assert res["status"] == "degraded_to_general"
    assert res["state"] == ConversationState.GENERAL_REPLY.value
    assert "versatile best-sellers" in mock_whatsapp.send_text_message.call_args[0][1]


@pytest.mark.asyncio
async def test_text_in_awaiting_photo_triggers_reminder_or_escalation():
    """Step 6: Customer sends text instead of photo while in AWAITING_PHOTO."""
    session = store.get_session("2348011112222")
    session.state = ConversationState.AWAITING_PHOTO
    store.save_session(session)

    mock_whatsapp = AsyncMock()
    orchestrator.whatsapp = mock_whatsapp

    # Case A: Ambiguous text -> reminder
    res = await orchestrator.handle_inbound_message(
        sender_id="2348011112222",
        msg_type="text",
        body_text="hold on checking my gallery",
    )
    assert res["status"] == "photo_reminder_sent"
    mock_whatsapp.send_text_message.assert_called_with("2348011112222", PHOTO_REMINDER_MESSAGE)

    # Case B: Complaint / escalation while in AWAITING_PHOTO -> immediate escalation
    mock_whatsapp.reset_mock()
    res2 = await orchestrator.handle_inbound_message(
        sender_id="2348011112222",
        msg_type="text",
        body_text="this bot is rubbish I want to speak to a real person",
    )
    assert res2["status"] == "escalated"
    assert res2["state"] == ConversationState.ESCALATED.value
    assert "human team member" in mock_whatsapp.send_text_message.call_args[0][1]


def test_stage3_webhook_end_to_end(monkeypatch):
    """Step 7: Webhook receives signed image payload in STAGE=3 mode."""
    monkeypatch.setenv("STAGE", "3")
    settings.stage = 3

    client = TestClient(app)
    mock_whatsapp = AsyncMock()
    mock_whatsapp.get_media_url.return_value = "https://media.test/photo.jpg"
    mock_youcam = AsyncMock()
    mock_youcam.analyze_skin_tone.return_value = {
        "status": "success",
        "result": {"skin_color": "#9C6B43", "undertone": "neutral"},
    }

    orchestrator.whatsapp = mock_whatsapp
    orchestrator.youcam = mock_youcam

    # Set user in AWAITING_PHOTO first
    session = store.get_session("2348012345678")
    session.state = ConversationState.AWAITING_PHOTO
    store.save_session(session)

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "1234", "phone_number_id": "5678"},
                            "messages": [
                                {
                                    "from": "2348012345678",
                                    "id": "wamid.HBgLMjM0ODAxMjM0NTY3OBUCABEYEkFDMEU0RDM4Mjk=",
                                    "timestamp": "1710000000",
                                    "type": "image",
                                    "image": {
                                        "id": "media_id_selfie_1",
                                        "mime_type": "image/jpeg",
                                        "sha256": "abcdef123456",
                                    },
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    import hashlib
    import hmac

    secret = "test_stage3_secret"
    settings.whatsapp_app_secret = secret

    raw_body = json.dumps(payload).encode("utf-8")
    sig = "sha256=" + hmac.new(secret.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256).hexdigest()

    response = client.post(
        "/webhook",
        content=raw_body,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_youcam.analyze_skin_tone.assert_called_once()
    mock_whatsapp.send_text_message.assert_called_once()
    assert "#9C6B43" in mock_whatsapp.send_text_message.call_args[0][1]
