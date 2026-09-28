"""YouCam API client for Skin-Tone Analysis and eCommerce VTO.

Integrates with Perfect Corp / YouCam AI API:
- Facial Color Tones Analyzer (task type: skin-tone-analysis)
- Clothes Changer / Virtual Try-On (task type: cloth-v4)

Enforces Phase 14 constraints:
- Polling capped at 30 seconds (~15 attempts at 2s interval)
- Documented error codes mapped cleanly without swallowing errors
- No silent infinite loops burning API units
"""
import asyncio
import logging
import os
from typing import Any, Dict, Optional
import httpx

from app.config import settings
from app.events import log_event

logger = logging.getLogger("umber.youcam")

# Documented error codes from YouCam API docs
DOCUMENTED_ERROR_CODES = {
    "error_pose",
    "error_invalid_ref",
    "error_apply_region_mismatch",
    "error_invalid_src",
    "error_download_image",
    "error_nsfw_content_detected",
    "error_editing_failed",
    "unknown_internal_error",
}


class YouCamAPIError(Exception):
    """Exception raised when YouCam API returns an error status."""
    def __init__(self, error_code: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{error_code}] {message}")


class YouCamTimeoutError(Exception):
    """Raised when YouCam polling exceeds the 30s cap."""
    pass


class YouCamClient:
    """Client for YouCam Skin-Tone Analysis and Clothes VTO APIs."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_poll_attempts: int = 15,
        poll_interval_seconds: float = 2.0,
    ):
        self.api_key = api_key or settings.youcam_api_key
        self.base_url = (base_url or settings.youcam_base_url).rstrip("/")
        self.max_poll_attempts = max_poll_attempts  # 15 * 2s = 30s cap
        self.poll_interval = poll_interval_seconds

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def poll_task_result(
        self,
        client: httpx.AsyncClient,
        task_id: str,
    ) -> Dict[str, Any]:
        """Poll task until completion or 30s cap is reached.
        
        Rule: never spin indefinitely; stop at 30s cap.
        """
        status_url = f"{self.base_url}/task/{task_id}"

        for attempt in range(1, self.max_poll_attempts + 1):
            response = await client.get(status_url, headers=self._get_headers())
            response.raise_for_status()
            data = response.json()
            status = data.get("status")

            if status == "success":
                return data
            elif status == "error":
                error_code = data.get("error_code", "unknown_internal_error")
                error_msg = data.get("error_message", "YouCam API reported an error")
                raise YouCamAPIError(error_code=error_code, message=error_msg, details=data)

            # Task is pending / running, wait before next attempt
            if attempt < self.max_poll_attempts:
                await asyncio.sleep(self.poll_interval)

        # 30s cap exceeded
        raise YouCamTimeoutError(
            f"YouCam task {task_id} did not complete within the 30s cap ({self.max_poll_attempts} attempts)."
        )

    async def analyze_skin_tone(self, image_url: str) -> Dict[str, Any]:
        """Submit a selfie for facial color tone analysis and wait for result.
        
        Task type: skin-tone-analysis
        Cost: 20 units per successful call (errors are free).
        Returns undertone, skin_color, etc.
        """
        log_event("SKIN_ANALYSIS_CALLED", {"image_url": image_url})

        # Demo / Offline fallback if API key is not configured or in trial conservation mode
        if self.api_key in ("your_youcam_api_key_here", "", None) or os.getenv("MOCK_YOUCAM") == "true":
            await asyncio.sleep(1.0)
            mock_result = {
                "task_id": "demo_task_skin_tone_01",
                "task_type": "skin-tone-analysis",
                "status": "success",
                "result": {
                    "skin_color": "#8D5524",
                    "undertone": "warm",
                    "depth": "deep",
                    "confidence": 0.96,
                },
            }
            log_event("SKIN_ANALYSIS_SUCCEEDED", {"task_id": "demo_task_skin_tone_01", "result": mock_result})
            return mock_result

        submit_url = f"{self.base_url}/task"
        payload = {
            "task_type": "skin-tone-analysis",
            "image_url": image_url,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            submit_resp = await client.post(
                submit_url,
                headers=self._get_headers(),
                json=payload,
            )
            submit_resp.raise_for_status()
            submit_data = submit_resp.json()
            task_id = submit_data.get("task_id")
            if not task_id:
                raise ValueError("YouCam API did not return a task_id for skin analysis.")

            try:
                result = await self.poll_task_result(client, task_id)
                log_event("SKIN_ANALYSIS_SUCCEEDED", {"task_id": task_id, "result": result})
                return result
            except YouCamAPIError as e:
                log_event("SKIN_ANALYSIS_FAILED", {"task_id": task_id, "error_code": e.error_code})
                raise

    async def render_clothes_vto(
        self,
        src_image_url: str,
        garment_image_url: str,
    ) -> Dict[str, Any]:
        """Submit a model photo and garment photo for VTO Clothes Changer (cloth-v4).
        
        Cost: 2 units per successful call.
        VERIFY: Exact result JSON field name for output image URL 
        (e.g., result_url vs output_image_url) to be confirmed on live sample.
        """
        log_event("VTO_RENDER_CALLED", {
            "src_image_url": src_image_url,
            "garment_image_url": garment_image_url,
        })

        # Demo / Offline fallback if API key is not configured or in trial conservation mode
        if self.api_key in ("your_youcam_api_key_here", "", None) or os.getenv("MOCK_YOUCAM") == "true":
            await asyncio.sleep(1.5)
            mock_result = {
                "task_id": "demo_task_vto_01",
                "task_type": "cloth-v4",
                "status": "success",
                "result": {
                    "result_url": garment_image_url,
                },
            }
            log_event("VTO_RENDER_SUCCEEDED", {"task_id": "demo_task_vto_01", "result": mock_result})
            return mock_result

        submit_url = f"{self.base_url}/task"
        payload = {
            "task_type": "cloth-v4",
            "src_image_url": src_image_url,
            "ref_image_url": garment_image_url,
        }

        log_event("VTO_RENDER_CALLED", {
            "src_image_url": src_image_url,
            "garment_image_url": garment_image_url,
        })

        async with httpx.AsyncClient(timeout=10.0) as client:
            submit_resp = await client.post(
                submit_url,
                headers=self._get_headers(),
                json=payload,
            )
            submit_resp.raise_for_status()
            submit_data = submit_resp.json()
            task_id = submit_data.get("task_id")
            if not task_id:
                raise ValueError("YouCam API did not return a task_id for cloth-v4.")

            try:
                result = await self.poll_task_result(client, task_id)
                log_event("VTO_RENDER_SUCCEEDED", {"task_id": task_id, "result": result})
                return result
            except YouCamAPIError as e:
                log_event("VTO_RENDER_FAILED", {"task_id": task_id, "error_code": e.error_code})
                raise
