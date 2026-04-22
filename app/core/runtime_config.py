from __future__ import annotations

import json
from typing import Any

from app.core.settings import Settings


class RuntimeConfigStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = settings.storage_dir / "runtime_config.json"

    def load(self) -> dict[str, Any]:
        defaults = {
            "llm_base_url": self.settings.llm_base_url,
            "llm_api_key": self.settings.llm_api_key,
            "llm_model": self.settings.llm_model,
            "ai_image_enabled": False,
            "image_backend": "openai",
            "image_api_key": "",
            "image_model": "",
            "image_base_url": "",
            "public_base_url": self.settings.public_base_url,
            "service_api_key": self.settings.api_key,
            "default_canvas_format": self.settings.default_canvas_format,
            "default_page_count": self.settings.default_page_count,
            "default_style_objective": self.settings.default_style_objective,
        }
        if not self.path.exists():
            return defaults
        current = json.loads(self.path.read_text(encoding="utf-8"))
        defaults.update(current)
        return defaults

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.load()
        current.update(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return current
