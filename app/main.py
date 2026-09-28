"""FastAPI Webhook server for Umber (Stage 1).

Implements Meta WhatsApp Cloud API subscription handshake and HMAC-SHA256
signature verification, inbound message reception, status update filtering,
and static acknowledgment reply dispatch.
"""
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse

from app.config import settings
from app.events import log_event
from app.clients.whatsapp import WhatsAppClient

logger = logging.getLogger("umber.webhook")

app = FastAPI(
    title="Umber - WhatsApp Webhook Server",
    description="Webhook server handling Meta WhatsApp Cloud API webhooks.",
    version="0.1.0",
)

whatsapp_client = WhatsAppClient()

# Stage 1 static acknowledgment message
STAGE_1_ACK_MESSAGE = "Thank you for reaching out to Umber! We have received your message."


@app.get("/")
async def root():
    return {"app": "Umber", "status": "running", "stage": 1}


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/webhook")
async def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
):
    """Meta WhatsApp subscription verification handshake.
    
    Meta sends GET request with hub.mode, hub.challenge, and hub.verify_token.
    If hub.mode == 'subscribe' and hub.verify_token matches WHATSAPP_VERIFY_TOKEN,
    we MUST return hub.challenge as plain text with HTTP 200.
    Otherwise return 403 Forbidden.
    """
    expected_token = settings.whatsapp_verify_token

    if hub_mode == "subscribe" and hub_verify_token and hub_verify_token == expected_token:
        log_event("HANDSHAKE_VERIFIED", {"mode": hub_mode})
        # Meta requires the raw challenge string as plain text
        return PlainTextResponse(content=hub_challenge or "", status_code=200)

    log_event("HANDSHAKE_REJECTED", {
        "mode": hub_mode,
        "token_match": bool(hub_verify_token and hub_verify_token == expected_token),
    })
    return Response(content="Verification failed: token mismatch", status_code=403)


def verify_signature(raw_body: bytes, signature_header: Optional[str], app_secret: str) -> bool:
    """Verify request signature against the raw body using HMAC-SHA256.
    
    Uses constant-time comparison (hmac.compare_digest) to prevent timing attacks.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    received_sig = signature_header[len("sha256="):]
    expected_sig = hmac.new(
        app_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_sig, received_sig)


@app.post("/webhook")
async def receive_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
):
    """Receive and process WhatsApp webhook events from Meta Cloud API.
    
    1. Reads raw request body.
    2. Validates HMAC-SHA256 signature BEFORE parsing JSON.
    3. Filters out status updates quietly (HTTP 200, no reply sent).
    4. Extracts inbound message text and sender.
    5. Dispatches fixed acknowledgment via WhatsAppClient.
    """
    raw_body = await request.body()

    # Step 1: Enforce HMAC-SHA256 signature verification
    app_secret = settings.whatsapp_app_secret
    if not verify_signature(raw_body, x_hub_signature_256, app_secret):
        log_event("SIGNATURE_REJECTED", {
            "has_header": bool(x_hub_signature_256),
            "header_preview": x_hub_signature_256[:15] if x_hub_signature_256 else None,
        })
        return Response(content="Signature verification failed", status_code=403)

    log_event("SIGNATURE_VERIFIED", {})

    # Step 2: Parse validated JSON payload
    try:
        payload: Dict[str, Any] = json.loads(raw_body)
    except json.JSONDecodeError as e:
        logger.error(f"Malformed JSON in webhook body: {e}")
        return Response(content="Malformed JSON", status_code=400)

    # Step 3: Extract entries and changes
    entries = payload.get("entry", [])
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})

            # Quietly handle status updates (sent, delivered, read) without replying
            statuses = value.get("statuses")
            if statuses:
                for status in statuses:
                    log_event("STATUS_UPDATE_RECEIVED", {
                        "status_id": status.get("id"),
                        "recipient_id": status.get("recipient_id"),
                        "status": status.get("status"),
                    })
                continue

            # Process inbound customer messages
            messages = value.get("messages", [])
            for message in messages:
                sender_id = message.get("from")
                msg_type = message.get("type", "unknown")
                msg_id = message.get("id")

                if msg_type == "text":
                    body_text = message.get("text", {}).get("body", "")
                else:
                    body_text = f"[{msg_type} message]"

                log_event("MESSAGE_RECEIVED", {
                    "sender": sender_id,
                    "message_id": msg_id,
                    "type": msg_type,
                    "text": body_text,
                })

                # Stage 1: Send one fixed acknowledgment
                if sender_id:
                    try:
                        await whatsapp_client.send_text_message(
                            to=sender_id,
                            text=STAGE_1_ACK_MESSAGE,
                        )
                    except Exception as e:
                        logger.error(f"Failed to send acknowledgment to {sender_id}: {e}")

    # Meta expects 200 OK fast
    return {"status": "ok"}
