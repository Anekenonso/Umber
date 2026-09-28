"""WhatsApp Cloud API client for Meta Graph API.

Handles sending outbound text and media messages to customers via WhatsApp Cloud API.
Follows Meta Graph API specifications (v21.0).
"""
import asyncio
import logging
from typing import Any, Dict, Optional
import httpx

from app.config import settings
from app.events import log_event

logger = logging.getLogger("umber.whatsapp")


class WhatsAppClient:
    """Client for Meta WhatsApp Cloud API."""

    def __init__(
        self,
        token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        api_version: Optional[str] = None,
    ):
        self.token = token or settings.whatsapp_token
        self.phone_number_id = phone_number_id or settings.whatsapp_phone_number_id
        self.api_version = api_version or settings.whatsapp_api_version
        self.base_url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def send_text_message(
        self,
        to: str,
        text: str,
        preview_url: bool = False,
    ) -> Dict[str, Any]:
        """Send a plain text message to a WhatsApp user.
        
        Implements 1 retry with backoff as per Phase 14 risk map.
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {
                "preview_url": preview_url,
                "body": text,
            },
        }

        max_attempts = 2  # 1 initial + 1 retry
        last_error = None

        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(1, max_attempts + 1):
                try:
                    response = await client.post(
                        self.base_url,
                        headers=self._get_headers(),
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    log_event("REPLY_SENT", {
                        "to": to,
                        "text": text,
                        "attempt": attempt,
                        "response": data,
                    })
                    return data
                except (httpx.HTTPStatusError, httpx.RequestError) as e:
                    last_error = e
                    logger.warning(
                        f"Failed to send WhatsApp message to {to} on attempt {attempt}: {e}"
                    )
                    if attempt < max_attempts:
                        await asyncio.sleep(1.0)  # Short backoff before 1 retry

        # Fallback if both attempts fail: log and drop (Phase 14)
        log_event("REPLY_FAILED", {
            "to": to,
            "text": text,
            "error": str(last_error),
        })
        raise RuntimeError(f"Failed to send WhatsApp message after retry: {last_error}")

    async def send_image_message(
        self,
        to: str,
        image_url: str,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send an image message to a WhatsApp user."""
        image_obj: Dict[str, Any] = {"link": image_url}
        if caption:
            image_obj["caption"] = caption

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "image",
            "image": image_obj,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(
                    self.base_url,
                    headers=self._get_headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                log_event("REPLY_SENT", {
                    "to": to,
                    "image_url": image_url,
                    "caption": caption,
                    "response": data,
                })
                return data
            except Exception as e:
                log_event("REPLY_FAILED", {
                    "to": to,
                    "image_url": image_url,
                    "error": str(e),
                })
                raise
