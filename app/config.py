"""Configuration management for Umber.

Loads environment variables and validates required settings.
Fails fast if critical variables are missing.
"""
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load .env if present in workspace root
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


class Settings:
    def __init__(
        self,
        whatsapp_token: Optional[str] = None,
        whatsapp_phone_number_id: Optional[str] = None,
        whatsapp_verify_token: Optional[str] = None,
        whatsapp_app_secret: Optional[str] = None,
        whatsapp_api_version: Optional[str] = None,
        youcam_api_key: Optional[str] = None,
        youcam_base_url: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ):
        self.whatsapp_token: str = whatsapp_token or os.getenv("WHATSAPP_TOKEN", "")
        self.whatsapp_phone_number_id: str = (
            whatsapp_phone_number_id or os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        )
        self.whatsapp_verify_token: str = (
            whatsapp_verify_token or os.getenv("WHATSAPP_VERIFY_TOKEN", "")
        )
        self.whatsapp_app_secret: str = (
            whatsapp_app_secret or os.getenv("WHATSAPP_APP_SECRET", "")
        )
        self.whatsapp_api_version: str = (
            whatsapp_api_version or os.getenv("WHATSAPP_API_VERSION", "v21.0")
        )
        self.youcam_api_key: str = youcam_api_key or os.getenv("YOUCAM_API_KEY", "")
        self.youcam_base_url: str = (
            youcam_base_url
            or os.getenv("YOUCAM_BASE_URL", "https://yce-api-01.makeupar.com")
        )
        self.host: str = host or os.getenv("HOST", "0.0.0.0")
        self.port: int = port or int(os.getenv("PORT", "8000"))

    def validate_webhook_settings(self) -> None:
        """Validate settings required for the WhatsApp webhook server."""
        missing = []
        if not self.whatsapp_verify_token:
            missing.append("WHATSAPP_VERIFY_TOKEN")
        if not self.whatsapp_app_secret:
            missing.append("WHATSAPP_APP_SECRET")
        if not self.whatsapp_token:
            missing.append("WHATSAPP_TOKEN")
        if not self.whatsapp_phone_number_id:
            missing.append("WHATSAPP_PHONE_NUMBER_ID")

        if missing:
            raise ValueError(
                f"Missing required WhatsApp environment variable(s): {', '.join(missing)}. "
                f"Please check your .env file or environment."
            )


# Default singleton instance
settings = Settings()
