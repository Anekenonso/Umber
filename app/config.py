"""Configuration management for Umber.

Loads environment variables dynamically and validates required settings.
Fails fast if critical variables are missing.
"""
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def reload_env():
    """Reload .env file to pick up any runtime updates."""
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH, override=True)


reload_env()


class Settings:
    def __init__(self):
        self._whatsapp_token: Optional[str] = None
        self._whatsapp_phone_number_id: Optional[str] = None
        self._whatsapp_verify_token: Optional[str] = None
        self._whatsapp_app_secret: Optional[str] = None
        self._whatsapp_api_version: Optional[str] = None
        self._youcam_api_key: Optional[str] = None
        self._youcam_base_url: Optional[str] = None
        self._stage: Optional[int] = None

    @property
    def stage(self) -> int:
        if self._stage is not None:
            return self._stage
        reload_env()
        return int(os.getenv("STAGE", "2"))

    @stage.setter
    def stage(self, val: int):
        self._stage = val

    @property
    def whatsapp_token(self) -> str:
        if self._whatsapp_token is not None:
            return self._whatsapp_token
        reload_env()
        return os.getenv("WHATSAPP_TOKEN", "")

    @whatsapp_token.setter
    def whatsapp_token(self, val: str):
        self._whatsapp_token = val

    @property
    def whatsapp_phone_number_id(self) -> str:
        if self._whatsapp_phone_number_id is not None:
            return self._whatsapp_phone_number_id
        reload_env()
        return os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

    @whatsapp_phone_number_id.setter
    def whatsapp_phone_number_id(self, val: str):
        self._whatsapp_phone_number_id = val

    @property
    def whatsapp_verify_token(self) -> str:
        if self._whatsapp_verify_token is not None:
            return self._whatsapp_verify_token
        reload_env()
        return os.getenv("WHATSAPP_VERIFY_TOKEN", "")

    @whatsapp_verify_token.setter
    def whatsapp_verify_token(self, val: str):
        self._whatsapp_verify_token = val

    @property
    def whatsapp_app_secret(self) -> str:
        if self._whatsapp_app_secret is not None:
            return self._whatsapp_app_secret
        reload_env()
        return os.getenv("WHATSAPP_APP_SECRET", "")

    @whatsapp_app_secret.setter
    def whatsapp_app_secret(self, val: str):
        self._whatsapp_app_secret = val

    @property
    def whatsapp_api_version(self) -> str:
        if self._whatsapp_api_version is not None:
            return self._whatsapp_api_version
        reload_env()
        return os.getenv("WHATSAPP_API_VERSION", "v21.0")

    @whatsapp_api_version.setter
    def whatsapp_api_version(self, val: str):
        self._whatsapp_api_version = val

    @property
    def youcam_api_key(self) -> str:
        if self._youcam_api_key is not None:
            return self._youcam_api_key
        reload_env()
        return os.getenv("YOUCAM_API_KEY", "")

    @youcam_api_key.setter
    def youcam_api_key(self, val: str):
        self._youcam_api_key = val

    @property
    def youcam_base_url(self) -> str:
        if self._youcam_base_url is not None:
            return self._youcam_base_url
        reload_env()
        return os.getenv("YOUCAM_BASE_URL", "https://yce-api-01.makeupar.com")

    @youcam_base_url.setter
    def youcam_base_url(self, val: str):
        self._youcam_base_url = val

    @property
    def host(self) -> str:
        return os.getenv("HOST", "0.0.0.0")

    @property
    def port(self) -> int:
        return int(os.getenv("PORT", "8000"))

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
                f"Please check your .env file."
            )


# Default singleton instance
settings = Settings()
