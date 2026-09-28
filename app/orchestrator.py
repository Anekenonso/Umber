"""Agent Orchestrator for Umber (Phase 4, Phase 6, Phase 9 & Stage 3).

Coordinates conversational state transitions, intent routing, selfie acquisition,
YouCam Skin-Tone Analysis, and customer-facing error recovery.

Operating Rules:
- Phase 4: Matcher is authoritative on WHAT is recommended; agent on HOW it is phrased.
- Phase 6: Explicit state machine transitions:
    RECEIVED -> CLASSIFIED -> AWAITING_PHOTO -> ANALYZING -> MATCHING -> ...
- Phase 9: Graceful failure handling. On bad selfie (e.g. error_pose):
    1st failure: Ask once for retake facing forward.
    2nd failure: Fall back to general best-sellers, never stall.
- Phase 13: Structured event logging across all transitions.
- Phase 14: Rate limits and timeouts respected (30s polling cap).
"""
import logging
from typing import Any, Dict, Optional

from app.classifier import classify_intent
from app.clients.whatsapp import WhatsAppClient
from app.clients.youcam import YouCamAPIError, YouCamClient, YouCamTimeoutError
from app.events import log_event
from app.states import (
    ClassificationResult,
    ConversationState,
    EscalationReason,
    Intent,
)
from app.store import ConversationSession, store

logger = logging.getLogger("umber.orchestrator")

# Customer-facing fallback prompts for documented YouCam errors (Phase 5 & 9)
YOUCAM_RETRY_MESSAGES = {
    "error_pose": (
        "We couldn't clearly detect your face. Could you send a clear selfie facing forward with good lighting?"
    ),
    "error_invalid_ref": (
        "We couldn't detect a clear face in that image. Please send a front-facing selfie!"
    ),
    "error_download_image": (
        "We had trouble downloading your photo. Could you try sending it again?"
    ),
    "error_nsfw_content_detected": (
        "We couldn't process this photo. Please send a standard face selfie."
    ),
    "timeout": (
        "Our skin-tone analysis took a bit too long right now. Let's look at our most versatile best-sellers!"
    ),
    "unknown": (
        "We ran into a small hiccup analyzing that photo. Could you send a clear, forward-facing photo?"
    ),
}

FALLBACK_GENERAL_MESSAGE = (
    "No worries at all! Here are our curated best-selling dresses designed to look stunning across all complexions."
)

PHOTO_REMINDER_MESSAGE = (
    "To find the perfect color for your complexion, please send a front-facing selfie in natural light! "
    "Or if you have a general question, feel free to ask."
)


class Orchestrator:
    """Manages conversational state machine and orchestrates client actions."""

    def __init__(
        self,
        whatsapp_client: Optional[WhatsAppClient] = None,
        youcam_client: Optional[YouCamClient] = None,
    ):
        self.whatsapp = whatsapp_client or WhatsAppClient()
        self.youcam = youcam_client or YouCamClient()

    async def handle_inbound_message(
        self,
        sender_id: str,
        msg_type: str,
        body_text: Optional[str] = None,
        media_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process an inbound WhatsApp message and advance conversation state."""
        session: ConversationSession = store.get_session(sender_id)

        # -------------------------------------------------------------------
        # Branch 1: Inbound Image Message
        # -------------------------------------------------------------------
        if msg_type == "image":
            log_event("PHOTO_RECEIVED", {
                "sender": sender_id,
                "media_id": media_id,
                "current_state": session.state.value,
            })
            return await self._handle_image_message(session, media_id)

        # -------------------------------------------------------------------
        # Branch 2: Inbound Text Message
        # -------------------------------------------------------------------
        text = (body_text or "").strip()

        # If user is in AWAITING_PHOTO but sends text instead of an image
        if session.state == ConversationState.AWAITING_PHOTO:
            # Check for genuine complaints or explicit human asks
            classification = classify_intent(text)
            if (
                classification.intent == Intent.ESCALATION
                and classification.escalation_reason != EscalationReason.UNCERTAIN_INTENT
            ):
                session.state = ConversationState.ESCALATED
                store.save_session(session)
                log_event("ESCALATED", {
                    "sender": sender_id,
                    "reason": classification.escalation_reason.value if classification.escalation_reason else "user_escalation",
                })
                reply_text = (
                    "I've flagged this for our store manager. "
                    "A human team member will assist you shortly!"
                )
                await self.whatsapp.send_text_message(sender_id, reply_text)
                return {"status": "escalated", "state": session.state.value}

            # If they asked a clear general question, transition out of AWAITING_PHOTO
            if classification.intent == Intent.GENERAL and classification.confidence > 0.8:
                session.state = ConversationState.GENERAL_REPLY
                store.save_session(session)
                reply_text = (
                    "We're open Mon–Sat 9am–7pm. Orders ship nationwide within 24–48 hours! "
                    "Let us know how else we can help."
                )
                await self.whatsapp.send_text_message(sender_id, reply_text)
                return {"status": "general_reply", "state": session.state.value}

            # Otherwise gently remind them we're waiting on a selfie
            await self.whatsapp.send_text_message(sender_id, PHOTO_REMINDER_MESSAGE)
            return {"status": "photo_reminder_sent", "state": session.state.value}

        # Standard initial text message: classify intent
        classification = classify_intent(text)
        log_event("INTENT_CLASSIFIED", {
            "sender": sender_id,
            "intent": classification.intent.value,
            "confidence": classification.confidence,
            "reason": classification.reason,
        })

        if classification.intent == Intent.PERSONALIZATION:
            session.state = ConversationState.AWAITING_PHOTO
            session.photo_retries = 0
            store.save_session(session)

            log_event("PHOTO_REQUESTED", {"sender": sender_id})
            reply_text = (
                "I'd love to help find the shade and style that best suits your skin tone! "
                "Could you send a quick selfie facing forward in natural lighting?"
            )
            await self.whatsapp.send_text_message(sender_id, reply_text)
            return {"status": "photo_requested", "state": session.state.value}

        elif classification.intent == Intent.ESCALATION:
            session.state = ConversationState.ESCALATED
            store.save_session(session)

            log_event("ESCALATED", {
                "sender": sender_id,
                "reason": classification.escalation_reason.value if classification.escalation_reason else "explicit",
            })
            reply_text = (
                "I'm connecting you with a member of our store team right away. "
                "Someone will follow up in this chat shortly."
            )
            await self.whatsapp.send_text_message(sender_id, reply_text)
            return {"status": "escalated", "state": session.state.value}

        else:
            session.state = ConversationState.GENERAL_REPLY
            store.save_session(session)
            reply_text = (
                "Hello! Welcome to our store. We're open Mon–Sat 9am–7pm. "
                "Ask us anything about our collection, or ask what colors suit your complexion!"
            )
            await self.whatsapp.send_text_message(sender_id, reply_text)
            return {"status": "general_reply", "state": session.state.value}

    async def _handle_image_message(
        self,
        session: ConversationSession,
        media_id: Optional[str],
    ) -> Dict[str, Any]:
        """Handle selfie upload, call YouCam Skin-Tone Analysis, and manage retries."""
        sender_id = session.sender_id

        if not media_id:
            await self.whatsapp.send_text_message(
                sender_id,
                "We couldn't read that image format. Could you send your selfie as a standard photo?",
            )
            return {"status": "invalid_media_id"}

        # Advance state to ANALYZING
        session.state = ConversationState.ANALYZING
        store.save_session(session)

        # Retrieve direct image URL from WhatsApp Cloud API
        try:
            image_url = await self.whatsapp.get_media_url(media_id)
        except Exception as e:
            logger.error(f"Failed to fetch media url for {media_id}: {e}")
            image_url = f"https://media.whatsapp.net/v/{media_id}"

        # Call YouCam Skin-Tone Analysis API
        try:
            result = await self.youcam.analyze_skin_tone(image_url)

            # Analysis succeeded! Extract results
            result_data = result.get("result", {})
            skin_color = result_data.get("skin_color", "#A66D46")
            undertone = result_data.get("undertone", "warm")

            session.context["skin_color"] = skin_color
            session.context["undertone"] = undertone
            session.state = ConversationState.MATCHING
            store.save_session(session)

            log_event("CATALOG_MATCH_COMPUTED", {
                "sender": sender_id,
                "skin_color": skin_color,
                "undertone": undertone,
            })

            # Stage 3 milestone confirmation reply:
            reply_text = (
                f"We analyzed your photo: detected skin tone {skin_color} with {undertone} undertones! "
                "Matching our catalog for your best picks..."
            )
            await self.whatsapp.send_text_message(sender_id, reply_text)
            return {
                "status": "analysis_success",
                "state": session.state.value,
                "skin_color": skin_color,
                "undertone": undertone,
            }

        except YouCamAPIError as e:
            logger.warning(f"YouCam API error during skin analysis: {e.error_code} - {e.message}")
            return await self._handle_analysis_failure(session, error_code=e.error_code)

        except YouCamTimeoutError:
            logger.warning("YouCam skin analysis exceeded 30s timeout cap.")
            return await self._handle_analysis_failure(session, error_code="timeout")

        except Exception as e:
            logger.error(f"Unexpected error in skin analysis: {e}")
            return await self._handle_analysis_failure(session, error_code="unknown")

    async def _handle_analysis_failure(
        self,
        session: ConversationSession,
        error_code: str,
    ) -> Dict[str, Any]:
        """Implement Phase 9 retake policy: 1 retake, then fall back to general catalog."""
        sender_id = session.sender_id
        session.photo_retries += 1

        if session.photo_retries <= 1 and error_code != "timeout":
            # First failure: ask for retake
            session.state = ConversationState.ANALYZING_FAILED
            store.save_session(session)

            log_event("FALLBACK_TRIGGERED", {
                "sender": sender_id,
                "type": "retake_requested",
                "retry_count": session.photo_retries,
                "error_code": error_code,
            })

            retry_msg = YOUCAM_RETRY_MESSAGES.get(error_code, YOUCAM_RETRY_MESSAGES["unknown"])
            await self.whatsapp.send_text_message(sender_id, retry_msg)
            return {
                "status": "retake_requested",
                "state": session.state.value,
                "error_code": error_code,
            }
        else:
            # Second failure or timeout: degrade gracefully to general picks (never stall)
            session.state = ConversationState.GENERAL_REPLY
            store.save_session(session)

            log_event("FALLBACK_TRIGGERED", {
                "sender": sender_id,
                "type": "general_degradation",
                "retry_count": session.photo_retries,
                "error_code": error_code,
            })

            fallback_msg = (
                YOUCAM_RETRY_MESSAGES.get("timeout") if error_code == "timeout" else FALLBACK_GENERAL_MESSAGE
            )
            await self.whatsapp.send_text_message(sender_id, fallback_msg)
            return {
                "status": "degraded_to_general",
                "state": session.state.value,
                "error_code": error_code,
            }
