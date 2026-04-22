from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import re
import time
from typing import Any, Optional

import requests
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse

from app.core.job_store import JobStore
from app.core.runtime_config import RuntimeConfigStore
from app.core.settings import Settings, load_settings


SETTINGS = load_settings()
JOB_STORE = JobStore(SETTINGS.storage_dir)
RUNTIME_CONFIG = RuntimeConfigStore(SETTINGS)
APP = FastAPI(title=SETTINGS.app_name)


def get_settings() -> Settings:
    return SETTINGS


def _is_image_model(item: dict[str, Any]) -> bool:
    model_type = str(item.get("type", "")).lower().strip()
    if model_type == "image":
        return True

    model_id = str(item.get("id", "")).lower()
    if "image" in model_id or "img" in model_id:
        return True
    for field in ("modalities", "input_modalities", "output_modalities", "capabilities"):
        value = item.get(field)
        if isinstance(value, list):
            lowered = {str(v).lower() for v in value}
            if "image" in lowered or "images" in lowered:
                return True
        elif isinstance(value, dict):
            if value.get("image") is True or value.get("images") is True:
                return True
    return False


def enforce_api_key(
    x_api_key: Optional[str] = Header(default=None),
    api_key: Optional[str] = Query(default=None),
    service_api_key: Optional[str] = Query(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    runtime_api_key = str(RUNTIME_CONFIG.load().get("service_api_key") or "").strip()
    required_key = runtime_api_key or str(settings.api_key or "").strip()
    provided = (x_api_key or api_key or service_api_key or "").strip()
    if required_key and provided != required_key:
        raise HTTPException(status_code=401, detail="Invalid API key.")


def _required_api_key(settings: Settings) -> str:
    runtime_api_key = str(RUNTIME_CONFIG.load().get("service_api_key") or "").strip()
    return runtime_api_key or str(settings.api_key or "").strip()


def _build_download_token(job_id: str, kind: str, settings: Settings, ttl_seconds: int = 86400) -> str:
    secret = _required_api_key(settings)
    if not secret:
        return ""
    expires = int(time.time()) + max(60, ttl_seconds)
    payload = f"{job_id}:{kind}:{expires}"
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def _verify_download_token(job_id: str, kind: str, token: str, settings: Settings) -> bool:
    secret = _required_api_key(settings)
    if not secret or not token:
        return False
    parts = token.split(".", 1)
    if len(parts) != 2:
        return False
    exp_raw, sig_raw = parts
    try:
        expires = int(exp_raw)
    except ValueError:
        return False
    if expires < int(time.time()):
        return False
    payload = f"{job_id}:{kind}:{expires}"
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_raw)


@APP.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@APP.get("/admin", response_class=HTMLResponse, dependencies=[Depends(enforce_api_key)])
def admin_page() -> HTMLResponse:
    html = (Path(__file__).resolve().parents[1] / "templates" / "admin.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@APP.post("/api/jobs", dependencies=[Depends(enforce_api_key)])
async def create_job(
    project_name: str = Form(...),
    source_text: str = Form(default=""),
    source_url: str = Form(default=""),
    source_items: str = Form(default=""),
    canvas_format: str = Form(default=SETTINGS.default_canvas_format),
    page_count: int = Form(default=SETTINGS.default_page_count),
    target_audience: str = Form(default=""),
    use_case: str = Form(default=""),
    style_objective: str = Form(default=SETTINGS.default_style_objective),
    color_hint: str = Form(default=""),
    image_strategy: str = Form(default=SETTINGS.default_image_strategy),
    icon_style: str = Form(default=SETTINGS.default_icon_style),
    template_name: str = Form(default=""),
    notes_style: str = Form(default="professional"),
    language: str = Form(default=""),
    file: Optional[UploadFile] = File(default=None),
    files: list[UploadFile] = File(default=[]),
) -> JSONResponse:
    uploaded_items: list[UploadFile] = []
    seen_upload_obj: set[int] = set()
    for candidate in ([file] if file is not None else []) + [item for item in files if item is not None]:
        key = id(candidate)
        if key in seen_upload_obj:
            continue
        seen_upload_obj.add(key)
        uploaded_items.append(candidate)

    parsed_source_items: list[str] = []
    raw_source_items = (source_items or "").strip()
    if raw_source_items:
        try:
            data = json.loads(raw_source_items)
            if isinstance(data, list):
                parsed_source_items = [str(item).strip() for item in data if str(item).strip()]
        except json.JSONDecodeError:
            # Fallback for newline/comma separated plain text.
            for part in re.split(r"[\n,]", raw_source_items):
                text = part.strip()
                if text:
                    parsed_source_items.append(text)

    if not any([source_text.strip(), source_url.strip(), parsed_source_items, uploaded_items]):
        raise HTTPException(status_code=400, detail="Provide source_text, source_url, or file.")

    payload = {
        "project_name": project_name,
        "source_text": source_text,
        "source_url": source_url,
        "source_items": parsed_source_items,
        "canvas_format": canvas_format,
        "page_count": page_count,
        "target_audience": target_audience,
        "use_case": use_case,
        "style_objective": style_objective,
        "color_hint": color_hint,
        "image_strategy": image_strategy,
        "icon_style": icon_style,
        "template_name": template_name,
        "notes_style": notes_style,
        "language": language,
        "uploaded_file_path": "",
        "uploaded_file_name": "",
    }
    metadata = JOB_STORE.create_job(payload)
    job_paths = JOB_STORE.get_paths(metadata["job_id"])

    seen_uploaded_names: set[str] = set()
    for idx, up in enumerate(uploaded_items):
        normalized_name = str(up.filename or f"uploaded_{idx + 1}").strip().lower()
        if normalized_name in seen_uploaded_names:
            continue
        seen_uploaded_names.add(normalized_name)
        contents = await up.read()
        if len(contents) > SETTINGS.max_upload_mb * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Uploaded file is too large.")
        filename = up.filename or f"uploaded_{idx + 1}"
        destination = job_paths.uploads_dir / filename
        if destination.exists():
            destination = job_paths.uploads_dir / f"{destination.stem}_{idx + 1}{destination.suffix}"
        destination.write_bytes(contents)
        if not payload["uploaded_file_path"]:
            payload["uploaded_file_path"] = str(destination)
            payload["uploaded_file_name"] = destination.name
        payload["source_items"].append(str(destination))

    if uploaded_items:
        metadata = JOB_STORE.update_job(metadata["job_id"], payload=payload)

    return JSONResponse(_public_job_response(metadata))


@APP.post("/api/jobs/json", dependencies=[Depends(enforce_api_key)])
async def create_job_json(body: dict) -> JSONResponse:
    source_items_raw = body.get("source_items", [])
    source_items = [str(item).strip() for item in source_items_raw if str(item).strip()]
    if not any([body.get("source_text", "").strip(), body.get("source_url", "").strip(), source_items]):
        raise HTTPException(status_code=400, detail="Provide source_text or source_url or source_items.")
    payload = {
        "project_name": body.get("project_name") or "ppt_job",
        "source_text": body.get("source_text", ""),
        "source_url": body.get("source_url", ""),
        "source_items": source_items,
        "canvas_format": body.get("canvas_format", SETTINGS.default_canvas_format),
        "page_count": int(body.get("page_count", SETTINGS.default_page_count)),
        "target_audience": body.get("target_audience", ""),
        "use_case": body.get("use_case", ""),
        "style_objective": body.get("style_objective", SETTINGS.default_style_objective),
        "color_hint": body.get("color_hint", ""),
        "image_strategy": body.get("image_strategy", SETTINGS.default_image_strategy),
        "icon_style": body.get("icon_style", SETTINGS.default_icon_style),
        "template_name": body.get("template_name", ""),
        "notes_style": body.get("notes_style", "professional"),
        "language": body.get("language", ""),
        "uploaded_file_path": "",
        "uploaded_file_name": "",
    }
    metadata = JOB_STORE.create_job(payload)
    return JSONResponse(_public_job_response(metadata))


@APP.get("/api/jobs/{job_id}", dependencies=[Depends(enforce_api_key)])
def get_job(job_id: str) -> JSONResponse:
    try:
        metadata = JOB_STORE.get_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc
    return JSONResponse(_public_job_response(metadata))


@APP.get("/api/admin/config", dependencies=[Depends(enforce_api_key)])
def get_runtime_config() -> JSONResponse:
    current = RUNTIME_CONFIG.load()
    return JSONResponse(
        {
            "llm_base_url": current.get("llm_base_url", ""),
            "llm_api_key": current.get("llm_api_key", ""),
            "llm_model": current.get("llm_model", ""),
            "ai_image_enabled": bool(current.get("ai_image_enabled", False)),
            "image_backend": current.get("image_backend", "openai"),
            "image_api_key": current.get("image_api_key", ""),
            "image_model": current.get("image_model", ""),
            "image_base_url": current.get("image_base_url", ""),
            "public_base_url": current.get("public_base_url", ""),
            "service_api_key": current.get("service_api_key", ""),
            "default_canvas_format": current.get("default_canvas_format", ""),
            "default_page_count": current.get("default_page_count", 8),
            "default_style_objective": current.get("default_style_objective", ""),
        }
    )


@APP.post("/api/admin/config", dependencies=[Depends(enforce_api_key)])
async def save_runtime_config(body: dict) -> JSONResponse:
    allowed = {
        "llm_base_url",
        "llm_api_key",
        "llm_model",
        "ai_image_enabled",
        "image_backend",
        "image_api_key",
        "image_model",
        "image_base_url",
        "public_base_url",
        "service_api_key",
        "default_canvas_format",
        "default_page_count",
        "default_style_objective",
    }
    payload = {key: value for key, value in body.items() if key in allowed}
    saved = RUNTIME_CONFIG.save(payload)
    return JSONResponse({"ok": True, "config": saved})


@APP.post("/api/admin/llm/models", dependencies=[Depends(enforce_api_key)])
async def fetch_llm_models(body: dict) -> JSONResponse:
    runtime = RUNTIME_CONFIG.load()
    base_url = str(body.get("llm_base_url") or runtime.get("llm_base_url") or "").rstrip("/")
    api_key = str(body.get("llm_api_key") or runtime.get("llm_api_key") or "")
    if not base_url or not api_key:
        raise HTTPException(status_code=400, detail="llm_base_url and llm_api_key are required.")
    response = requests.get(
        f"{base_url}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    models = [
        {"id": item.get("id", ""), "owned_by": item.get("owned_by", "")}
        for item in payload.get("data", [])
        if item.get("id")
    ]
    models.sort(key=lambda item: item["id"])
    return JSONResponse({"models": models})


@APP.post("/api/admin/image/models", dependencies=[Depends(enforce_api_key)])
async def fetch_image_models(body: dict) -> JSONResponse:
    runtime = RUNTIME_CONFIG.load()
    base_url = str(body.get("image_base_url") or runtime.get("image_base_url") or "").rstrip("/")
    api_key = str(body.get("image_api_key") or runtime.get("image_api_key") or "")
    if not base_url or not api_key:
        raise HTTPException(status_code=400, detail="image_base_url and image_api_key are required.")
    response = requests.get(
        f"{base_url}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    raw_models = [item for item in payload.get("data", []) if isinstance(item, dict) and item.get("id")]
    filtered = [{"id": item.get("id", ""), "owned_by": item.get("owned_by", "")} for item in raw_models if _is_image_model(item)]
    if not filtered:
        # Fallback for providers that don't expose capability metadata.
        filtered = [
            {"id": item.get("id", ""), "owned_by": item.get("owned_by", "")}
            for item in raw_models
            if "image" in str(item.get("id", "")).lower() or "img" in str(item.get("id", "")).lower()
        ]
    filtered.sort(key=lambda item: item["id"])
    return JSONResponse({"models": filtered})


@APP.get("/api/jobs/{job_id}/logs", dependencies=[Depends(enforce_api_key)])
def get_job_logs(job_id: str) -> PlainTextResponse:
    try:
        logs = JOB_STORE.read_logs(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc
    return PlainTextResponse(logs)


@APP.get("/api/jobs/{job_id}/artifacts", dependencies=[Depends(enforce_api_key)])
def get_job_artifacts(job_id: str) -> JSONResponse:
    metadata = JOB_STORE.get_job(job_id)
    return JSONResponse(metadata.get("artifacts", {}))


@APP.get("/api/jobs/{job_id}/download/{kind}")
def download_artifact(
    job_id: str,
    kind: str,
    x_api_key: Optional[str] = Header(default=None),
    api_key: Optional[str] = Query(default=None),
    service_api_key: Optional[str] = Query(default=None),
    dl_token: Optional[str] = Query(default=None),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    required_key = _required_api_key(settings)
    provided_key = (x_api_key or api_key or service_api_key or "").strip()
    key_ok = bool(required_key) and provided_key == required_key
    token_ok = _verify_download_token(job_id, kind, dl_token or "", settings)
    if required_key and not (key_ok or token_ok):
        raise HTTPException(status_code=401, detail="Invalid API key.")

    metadata = JOB_STORE.get_job(job_id)
    files = metadata.get("artifacts", {}).get("files", [])
    for item in files:
        if item["kind"] == kind:
            path = Path(item["path"])
            return FileResponse(path, filename=path.name)
    raise HTTPException(status_code=404, detail="Artifact not found.")


def _public_job_response(metadata: dict) -> dict:
    job_id = metadata["job_id"]
    runtime = RUNTIME_CONFIG.load()
    runtime_public_base_url = str(runtime.get("public_base_url") or "").rstrip("/")
    base_url = runtime_public_base_url or SETTINGS.public_base_url
    native_token = _build_download_token(job_id, "native", SETTINGS)
    svg_token = _build_download_token(job_id, "svg_reference", SETTINGS)
    download_native = f"{base_url}/api/jobs/{job_id}/download/native"
    download_svg_reference = f"{base_url}/api/jobs/{job_id}/download/svg_reference"
    if native_token:
        download_native = f"{download_native}?dl_token={native_token}"
    if svg_token:
        download_svg_reference = f"{download_svg_reference}?dl_token={svg_token}"
    response = {
        "job_id": job_id,
        "status": metadata.get("status"),
        "created_at": metadata.get("created_at"),
        "updated_at": metadata.get("updated_at"),
        "error": metadata.get("error"),
        "artifacts": metadata.get("artifacts", {}),
        "links": {
            "self": f"{base_url}/api/jobs/{job_id}",
            "logs": f"{base_url}/api/jobs/{job_id}/logs",
            "artifacts": f"{base_url}/api/jobs/{job_id}/artifacts",
            "download_native": download_native,
            "download_svg_reference": download_svg_reference,
        },
    }
    return response


app = APP
