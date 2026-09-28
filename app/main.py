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

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.responses import PlainTextResponse

from app.clients.whatsapp import WhatsAppClient
from app.config import settings
from app.events import log_event
from app.classifier import classify_intent
from app.states import Intent
from app.orchestrator import Orchestrator

logger = logging.getLogger("umber.webhook")

app = FastAPI(
    title="Umber - WhatsApp Webhook Server",
    description="Webhook server handling Meta WhatsApp Cloud API webhooks.",
    version="0.3.0",
)

whatsapp_client = WhatsAppClient()
orchestrator = Orchestrator(whatsapp_client=whatsapp_client)

# Stage 1 static acknowledgment message
STAGE_1_ACK_MESSAGE = "Thank you for reaching out to Umber! We have received your message."

# Stage 2 intent-driven responses
STAGE_2_REPLIES = {
    Intent.PERSONALIZATION: (
        "We'd love to help you find the perfect outfit for your skin tone! "
        "Please send a clear, forward-facing photo or selfie in good lighting, "
        "and we'll analyze your palette and recommend matching pieces."
    ),
    Intent.GENERAL: (
        "Thanks for messaging Umber! We specialize in personalized fashion recommendations "
        "tailored to your unique complexion and style. For pricing, shipping, or catalog inquiries, "
        "feel free to ask, or send a selfie to try on our collection!"
    ),
    Intent.ESCALATION: (
        "We apologize for any trouble you've experienced. We have flagged your request for "
        "our human support team, and an agent will be with you shortly."
    ),
}


@app.get("/")
async def root(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
):
    """Root endpoint. If Meta sends handshake to / instead of /webhook, handle it seamlessly."""
    if hub_mode == "subscribe":
        return await verify_webhook(hub_mode, hub_challenge, hub_verify_token)
    return {"app": "Umber", "status": "running", "stage": settings.stage}


@app.post("/")
async def root_post(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
):
    """Fallback if webhook URL in Meta is configured as / instead of /webhook."""
    return await receive_webhook(request, x_hub_signature_256)


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

                media_id = None
                if msg_type == "text":
                    body_text = message.get("text", {}).get("body", "")
                elif msg_type == "image":
                    image_info = message.get("image", {})
                    media_id = image_info.get("id")
                    body_text = image_info.get("caption", "[image message]")
                else:
                    body_text = f"[{msg_type} message]"

                log_event("MESSAGE_RECEIVED", {
                    "sender": sender_id,
                    "message_id": msg_id,
                    "type": msg_type,
                    "text": body_text,
                })

                if sender_id:
                    try:
                        if settings.stage == 1:
                            reply_text = STAGE_1_ACK_MESSAGE
                            await whatsapp_client.send_text_message(
                                to=sender_id,
                                text=reply_text,
                            )
                        elif settings.stage == 2:
                            # Stage 2: Intent classification & intelligent routing
                            classification = classify_intent(body_text)
                            reply_text = STAGE_2_REPLIES.get(
                                classification.intent,
                                STAGE_2_REPLIES[Intent.GENERAL],
                            )
                            await whatsapp_client.send_text_message(
                                to=sender_id,
                                text=reply_text,
                            )
                        else:
                            # Stage 3+: Orchestrator handles state machine, photo analysis & retakes
                            await orchestrator.handle_inbound_message(
                                sender_id=sender_id,
                                msg_type=msg_type,
                                body_text=body_text,
                                media_id=media_id,
                            )
                    except Exception as e:
                        logger.error(f"Failed to handle message for {sender_id}: {e}")

    # Meta expects 200 OK fast
    return {"status": "ok"}


@app.get("/sessions/escalations")
async def get_escalated_sessions():
    """List open customer conversations flagged for human staff review."""
    from app.store import store
    escalations = store.list_escalations()
    return {"count": len(escalations), "escalations": escalations}


@app.post("/sessions/{sender_id}/resolve")
async def resolve_session_escalation(sender_id: str):
    """Staff resolves escalation, restoring conversation to active state."""
    from app.store import store
    from app.states import ConversationState
    updated_session = store.resolve_escalation(sender_id, next_state=ConversationState.GENERAL_REPLY)
    log_event("ESCALATION_RESOLVED", {"sender_id": sender_id, "new_state": updated_session.state.value})
    return {"status": "resolved", "session": updated_session.to_dict()}
