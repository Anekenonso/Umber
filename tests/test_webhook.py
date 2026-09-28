"""Tests for the WhatsApp Webhook server (Stage 1).

Covers:
1. Handshake verification (success with valid token and mode).
2. Handshake rejection (invalid token).
3. Handshake rejection (invalid mode).
4. Webhook receive rejection on missing signature header.
5. Webhook receive rejection on invalid/tampered signature.
6. Quiet handling of status update payloads (HTTP 200, 0 messages sent).
7. Inbound text message handling (valid signature -> HTTP 200, exactly 1 fixed reply sent).
"""
import hashlib
import hmac
import json
import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app, STAGE_1_ACK_MESSAGE
from app.config import settings

client = TestClient(app)

TEST_VERIFY_TOKEN = "test_umber_verify_token_123"
TEST_APP_SECRET = "test_umber_secret_key_456"


@pytest.fixture(autouse=True)
def setup_test_env():
    """Ensure test configuration settings are active."""
    settings.whatsapp_verify_token = TEST_VERIFY_TOKEN
    settings.whatsapp_app_secret = TEST_APP_SECRET
    settings.whatsapp_phone_number_id = "10987654321"
    settings.whatsapp_token = "mock_token"
    settings.stage = 1


def compute_signature(payload_bytes: bytes, secret: str = TEST_APP_SECRET) -> str:
    """Helper to compute valid X-Hub-Signature-256 header."""
    sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def test_handshake_success():
    """Handshake succeeds with HTTP 200 and raw challenge text for valid token."""
    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "1158201444",
            "hub.verify_token": TEST_VERIFY_TOKEN,
        },
    )
    assert response.status_code == 200
    assert response.text == "1158201444"


def test_handshake_failure_invalid_token():
    """Handshake returns 403 Forbidden for mismatched verify token."""
    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "1158201444",
            "hub.verify_token": "wrong_token",
        },
    )
    assert response.status_code == 403
    assert "token mismatch" in response.text


def test_handshake_failure_invalid_mode():
    """Handshake returns 403 Forbidden when hub.mode != 'subscribe'."""
    response = client.get(
        "/webhook",
        params={
            "hub.mode": "publish",
            "hub.challenge": "1158201444",
            "hub.verify_token": TEST_VERIFY_TOKEN,
        },
    )
    assert response.status_code == 403


def test_receive_missing_signature_header():
    """Missing signature header must be rejected with 403 before parsing."""
    payload = json.dumps({"test": "data"}).encode("utf-8")
    response = client.post(
        "/webhook",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 403
    assert "Signature verification failed" in response.text


def test_receive_invalid_signature():
    """Tampered or invalid signature must be rejected with 403."""
    payload = json.dumps({"test": "data"}).encode("utf-8")
    wrong_sig = compute_signature(payload, secret="wrong_secret")
    response = client.post(
        "/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": wrong_sig,
        },
    )
    assert response.status_code == 403
    assert "Signature verification failed" in response.text


@pytest.mark.asyncio
async def test_receive_status_update_payload_quietly():
    """Status updates (sent, delivered, read) must return 200 OK and send NO reply message."""
    status_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "12345678",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550234567",
                                "phone_number_id": "10987654321",
                            },
                            "statuses": [
                                {
                                    "id": "wamid.HBgLMTE1Nzg",
                                    "status": "delivered",
                                    "timestamp": "1720000000",
                                    "recipient_id": "2348012345678",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    payload_bytes = json.dumps(status_payload).encode("utf-8")
    valid_sig = compute_signature(payload_bytes)

    with patch("app.main.whatsapp_client.send_text_message", new_callable=AsyncMock) as mock_send:
        response = client.post(
            "/webhook",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": valid_sig,
            },
        )
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        # Guarantee no reply was sent
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_receive_valid_message_sends_fixed_reply():
    """A valid signed incoming message must return 200 and dispatch exactly one fixed acknowledgment."""
    inbound_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "12345678",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550234567",
                                "phone_number_id": "10987654321",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Test Customer"},
                                    "wa_id": "2348012345678",
                                }
                            ],
                            "messages": [
                                {
                                    "from": "2348012345678",
                                    "id": "wamid.HBgLMTE1Nzg=",
                                    "timestamp": "1720000000",
                                    "text": {"body": "Hi, what color dress suits me?"},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    payload_bytes = json.dumps(inbound_payload).encode("utf-8")
    valid_sig = compute_signature(payload_bytes)

    with patch("app.main.whatsapp_client.send_text_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"messages": [{"id": "wamid.outbound123"}]}

        response = client.post(
            "/webhook",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": valid_sig,
            },
        )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        # Verify exactly one fixed acknowledgment message was dispatched
        mock_send.assert_called_once_with(
            to="2348012345678",
            text=STAGE_1_ACK_MESSAGE,
        )


@pytest.mark.asyncio
async def test_receive_stage_2_routes_personalization_intent():
    """In Stage 2, a skin tone inquiry triggers personalization selfie prompt."""
    settings.stage = 2
    inbound_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "12345678",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "2348012345678",
                                    "id": "wamid.HBgLMTE1Nzg=",
                                    "timestamp": "1720000000",
                                    "text": {"body": "What color dress suits my dark skin tone?"},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    payload_bytes = json.dumps(inbound_payload).encode("utf-8")
    valid_sig = compute_signature(payload_bytes)

    with patch("app.main.whatsapp_client.send_text_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"messages": [{"id": "wamid.outbound123"}]}

        response = client.post(
            "/webhook",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": valid_sig,
            },
        )

        assert response.status_code == 200
        assert mock_send.call_count == 1
        call_args = mock_send.call_args[1]
        assert call_args["to"] == "2348012345678"
        assert "selfie" in call_args["text"].lower() or "photo" in call_args["text"].lower()


@pytest.mark.asyncio
async def test_receive_stage_2_routes_escalation_intent():
    """In Stage 2, a complaint triggers immediate escalation response."""
    settings.stage = 2
    inbound_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "12345678",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "2348012345678",
                                    "id": "wamid.HBgLMTE1Nzg=",
                                    "timestamp": "1720000000",
                                    "text": {"body": "I demand an immediate refund for damaged goods!"},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    payload_bytes = json.dumps(inbound_payload).encode("utf-8")
    valid_sig = compute_signature(payload_bytes)

    with patch("app.main.whatsapp_client.send_text_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"messages": [{"id": "wamid.outbound123"}]}

        response = client.post(
            "/webhook",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": valid_sig,
            },
        )

        assert response.status_code == 200
        assert mock_send.call_count == 1
        call_args = mock_send.call_args[1]
        assert call_args["to"] == "2348012345678"
        assert "human support team" in call_args["text"].lower() or "agent" in call_args["text"].lower()
