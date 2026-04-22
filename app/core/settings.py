from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str
    host: str
    port: int
    api_key: str
    storage_dir: Path
    job_poll_interval_seconds: int
    export_retention_days: int
    cleanup_interval_seconds: int
    max_upload_mb: int
    public_base_url: str
    repo_root: Path
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: int
    llm_temperature: float
    log_llm_prompts: bool
    default_canvas_format: str
    default_page_count: int
    default_style_objective: str
    default_image_strategy: str
    default_icon_style: str


def load_settings() -> Settings:
    service_root = Path(__file__).resolve().parents[2]
    default_storage = service_root / "storage"
    # In containerized deployments service_root may be "/app", which has only one parent.
    default_repo_root = service_root.parent

    return Settings(
        app_name=os.getenv("APP_NAME", "ppt-master-service"),
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", "8099")),
        api_key=os.getenv("SERVICE_API_KEY", ""),
        storage_dir=Path(os.getenv("STORAGE_DIR", str(default_storage))).resolve(),
        job_poll_interval_seconds=int(os.getenv("JOB_POLL_INTERVAL_SECONDS", "3")),
        export_retention_days=int(os.getenv("EXPORT_RETENTION_DAYS", "7")),
        cleanup_interval_seconds=int(os.getenv("CLEANUP_INTERVAL_SECONDS", "3600")),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "50")),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8099").rstrip("/"),
        repo_root=Path(os.getenv("PPT_MASTER_REPO_ROOT", str(default_repo_root))).resolve(),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "180")),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
        log_llm_prompts=_env_bool("LOG_LLM_PROMPTS", False),
        default_canvas_format=os.getenv("DEFAULT_CANVAS_FORMAT", "ppt169"),
        default_page_count=int(os.getenv("DEFAULT_PAGE_COUNT", "8")),
        default_style_objective=os.getenv("DEFAULT_STYLE_OBJECTIVE", "general_consulting"),
        default_image_strategy=os.getenv("DEFAULT_IMAGE_STRATEGY", "placeholder"),
        default_icon_style=os.getenv("DEFAULT_ICON_STYLE", "tabler-outline"),
    )
