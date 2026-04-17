from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.config import (
    DEFAULT_API_BASE_URL,
    DEFAULT_API_MODEL,
    DEFAULT_API_PROVIDER,
    DEFAULT_HOTKEY,
    REQUEST_TIMEOUT,
)


@dataclass
class AppSettings:
    hotkey: str = DEFAULT_HOTKEY
    api_provider: str = DEFAULT_API_PROVIDER
    api_base_url: str = DEFAULT_API_BASE_URL
    api_key: str = ""
    api_model: str = DEFAULT_API_MODEL
    request_timeout: int = REQUEST_TIMEOUT


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return AppSettings()

        hotkey = payload.get("hotkey", DEFAULT_HOTKEY)
        if not isinstance(hotkey, str) or not hotkey.strip():
            hotkey = DEFAULT_HOTKEY

        provider = payload.get("api_provider", DEFAULT_API_PROVIDER)
        if not isinstance(provider, str) or not provider.strip():
            provider = DEFAULT_API_PROVIDER

        base_url = payload.get("api_base_url", DEFAULT_API_BASE_URL)
        if not isinstance(base_url, str) or not base_url.strip():
            base_url = DEFAULT_API_BASE_URL

        api_key = payload.get("api_key", "")
        if not isinstance(api_key, str):
            api_key = ""

        model = payload.get("api_model", DEFAULT_API_MODEL)
        if not isinstance(model, str) or not model.strip():
            model = DEFAULT_API_MODEL

        timeout = payload.get("request_timeout", REQUEST_TIMEOUT)
        if not isinstance(timeout, int) or timeout < 15:
            timeout = REQUEST_TIMEOUT

        return AppSettings(
            hotkey=hotkey.strip(),
            api_provider=provider.strip(),
            api_base_url=base_url.strip(),
            api_key=api_key,
            api_model=model.strip(),
            request_timeout=timeout,
        )

    def save(self, settings: AppSettings) -> None:
        payload = {
            "hotkey": settings.hotkey,
            "api_provider": settings.api_provider,
            "api_base_url": settings.api_base_url,
            "api_key": settings.api_key,
            "api_model": settings.api_model,
            "request_timeout": settings.request_timeout,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
