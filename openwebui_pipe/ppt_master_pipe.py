"""
OpenWebUI Pipe for the standalone PPT Master service.

Import this file in OpenWebUI Functions -> Import.
"""

import re
import time
import json
from urllib.parse import urljoin
from typing import Any

import requests
from pydantic import BaseModel, Field


class Pipe:
    class Valves(BaseModel):
        service_url: str = Field(default="http://127.0.0.1:8099", description="PPT service base URL")
        service_api_key: str = Field(default="", description="SERVICE_API_KEY for the PPT service")
        confirmation_mode: str = Field(
            default="auto",
            description="auto | lite | full. auto=直接生成, lite=轻确认, full=完整八项确认",
        )
        canvas_format: str = Field(default="ppt169", description="Default canvas format")
        page_count: int = Field(default=8, description="Default page count")
        style_objective: str = Field(
            default="general_consulting",
            description="general_versatile or general_consulting or top_consulting",
        )
        poll_interval_seconds: int = Field(default=5, description="Polling interval")
        max_wait_seconds: int = Field(default=900, description="Maximum wait time before returning a pending job")
        openwebui_base_url: str = Field(
            default="",
            description="Optional OpenWebUI base URL, used to resolve relative/private attachment URLs",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    def pipes(self) -> list[dict[str, str]]:
        return [{"id": "ppt-master-service", "name": "PPT Master Service"}]

    async def pipe(
        self,
        body: dict[str, Any],
        __event_emitter__=None,
        __user__=None,
    ) -> str:
        messages = body.get("messages", [])
        user_texts = self._extract_user_texts(messages)
        latest_prompt = user_texts[-1] if user_texts else ""
        if not latest_prompt:
            return "Please provide the source material or requirements for the PPT."
        source_text = self._build_source_text(user_texts)
        source_items = self._extract_source_items(user_texts, body)
        attachment_files = self._collect_attachment_files(body, __user__)
        parsed = self._collect_requirements(user_texts)
        if self._wants_config_help(latest_prompt):
            return self._render_config_help(parsed)
        mode = self._resolve_confirmation_mode(parsed.get("confirmation_mode"))
        missing = self._missing_fields(parsed, mode)
        if mode in {"lite", "full"} and missing:
            return self._render_missing_questions(mode, parsed, missing)
        if mode == "full" and not self._is_explicit_confirm(latest_prompt):
            return self._render_full_confirmation(parsed)

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": "Submitting PPT generation job...", "done": False},
                }
            )

        headers = {}
        if self.valves.service_api_key:
            headers["X-API-Key"] = self.valves.service_api_key

        job_payload = {
            "project_name": parsed.get("project_name") or "openwebui_ppt",
            "source_text": source_text,
            "source_items": source_items,
            "canvas_format": parsed.get("canvas_format") or self.valves.canvas_format,
            "page_count": parsed.get("page_count") or self.valves.page_count,
            "style_objective": parsed.get("style_objective") or self.valves.style_objective,
            "target_audience": parsed.get("target_audience", ""),
            "use_case": parsed.get("use_case", ""),
            "color_hint": parsed.get("color_hint", ""),
            "image_strategy": parsed.get("image_strategy") or "placeholder",
            "language": parsed.get("language", ""),
        }

        if attachment_files:
            form_data = {
                "project_name": str(job_payload["project_name"]),
                "source_text": str(job_payload["source_text"]),
                "source_url": "",
                "source_items": json.dumps(job_payload["source_items"], ensure_ascii=False),
                "canvas_format": str(job_payload["canvas_format"]),
                "page_count": str(job_payload["page_count"]),
                "style_objective": str(job_payload["style_objective"]),
                "target_audience": str(job_payload["target_audience"]),
                "use_case": str(job_payload["use_case"]),
                "color_hint": str(job_payload["color_hint"]),
                "image_strategy": str(job_payload["image_strategy"]),
                "language": str(job_payload["language"]),
                "icon_style": "tabler-outline",
                "template_name": "",
                "notes_style": "professional",
            }
            multipart_files = [
                ("files", (item["name"], item["content"], item["mime"]))
                for item in attachment_files
            ]
            create_resp = requests.post(
                f"{self.valves.service_url}/api/jobs",
                headers=headers,
                data=form_data,
                files=multipart_files,
                timeout=120,
            )
        else:
            json_headers = {"Content-Type": "application/json", **headers}
            create_resp = requests.post(
                f"{self.valves.service_url}/api/jobs/json",
                headers=json_headers,
                json=job_payload,
                timeout=60,
            )
        create_resp.raise_for_status()
        job = create_resp.json()
        job_id = job["job_id"]

        deadline = time.time() + self.valves.max_wait_seconds
        while time.time() < deadline:
            time.sleep(self.valves.poll_interval_seconds)
            status_resp = requests.get(
                f"{self.valves.service_url}/api/jobs/{job_id}",
                headers=headers,
                timeout=60,
            )
            status_resp.raise_for_status()
            status = status_resp.json()
            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "status",
                        "data": {
                            "description": f"PPT job {job_id} is {status['status']}",
                            "done": False,
                        },
                    }
                )
            if status["status"] == "succeeded":
                if __event_emitter__:
                    await __event_emitter__(
                        {
                            "type": "status",
                            "data": {"description": "PPT generation finished.", "done": True},
                        }
                    )
                return self._render_success(status)
            if status["status"] == "failed":
                return f"PPT generation failed.\n\nJob ID: `{job_id}`\nError: {status.get('error', 'unknown error')}"

        return (
            "PPT job is still running.\n\n"
            f"Job ID: `{job_id}`\n"
            f"Status: `{job['status']}`\n"
            f"Track: {job['links']['self']}\n"
            f"Logs: {job['links']['logs']}"
        )

    @staticmethod
    def _last_user_message(body: dict[str, Any]) -> str:
        messages = body.get("messages", [])
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            content = message.get("content", "")
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                return "\n".join(part for part in text_parts if part).strip()
            return str(content).strip()
        return ""

    @staticmethod
    def _render_success(status: dict[str, Any]) -> str:
        files = status.get("artifacts", {}).get("files", [])
        rows = [f"Job ID: `{status['job_id']}`", ""]
        for item in files:
            rows.append(f"- {item['kind']}: {item['name']}")
        rows.append("")
        rows.append(f"Native PPTX: {status['links']['download_native']}")
        rows.append(f"SVG Reference PPTX: {status['links']['download_svg_reference']}")
        rows.append(f"Logs: {status['links']['logs']}")
        return "\n".join(rows)

    @staticmethod
    def _extract_user_texts(messages: list[dict[str, Any]]) -> list[str]:
        texts: list[str] = []
        for message in messages:
            if message.get("role") != "user":
                continue
            content = message.get("content", "")
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(str(item.get("text", "")).strip())
                text = "\n".join(part for part in parts if part).strip()
            else:
                text = str(content).strip()
            if text:
                texts.append(text)
        return texts

    @staticmethod
    def _build_source_text(user_texts: list[str]) -> str:
        cleaned: list[str] = []
        for text in user_texts:
            if Pipe._is_explicit_confirm(text):
                continue
            cleaned.append(text)
        return "\n\n".join(cleaned).strip()

    @staticmethod
    def _extract_source_items(user_texts: list[str], body: dict[str, Any]) -> list[str]:
        merged = "\n".join(user_texts)
        urls = re.findall(r"https?://[^\s)\]}>\"']+", merged, flags=re.IGNORECASE)
        urls.extend(Pipe._extract_attachment_urls(body))
        unique: list[str] = []
        for url in urls:
            normalized = url.strip().rstrip(".,;")
            if normalized and normalized not in unique:
                unique.append(normalized)
        return unique[:8]

    @staticmethod
    def _extract_attachment_urls(body: dict[str, Any]) -> list[str]:
        """
        Best-effort extraction for OpenWebUI file/image attachment URLs.
        This keeps compatibility across versions by checking several common shapes.
        """
        out: list[str] = []
        seen: set[str] = set()

        def add_url(raw: Any) -> None:
            text = str(raw or "").strip()
            if not text or not text.lower().startswith(("http://", "https://")):
                return
            text = text.rstrip(".,;")
            if text in seen:
                return
            seen.add(text)
            out.append(text)

        files = body.get("files", [])
        if isinstance(files, list):
            for item in files:
                if not isinstance(item, dict):
                    continue
                add_url(item.get("url"))
                file_obj = item.get("file")
                if isinstance(file_obj, dict):
                    add_url(file_obj.get("url"))
                    add_url(file_obj.get("web_url"))
                    add_url(file_obj.get("download_url"))

        messages = body.get("messages", [])
        if isinstance(messages, list):
            for message in messages:
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for entry in content:
                    if not isinstance(entry, dict):
                        continue
                    # Newer shape: {"type":"image_url","image_url":{"url":"..."}}
                    image_url = entry.get("image_url")
                    if isinstance(image_url, dict):
                        add_url(image_url.get("url"))
                    elif isinstance(image_url, str):
                        add_url(image_url)
                    add_url(entry.get("url"))
                    add_url(entry.get("web_url"))
                    file_obj = entry.get("file")
                    if isinstance(file_obj, dict):
                        add_url(file_obj.get("url"))
                        add_url(file_obj.get("web_url"))
                        add_url(file_obj.get("download_url"))

        return out

    def _collect_attachment_files(self, body: dict[str, Any], user: Any) -> list[dict[str, Any]]:
        candidates = self._iter_attachment_candidates(body)
        auth_headers = self._build_user_auth_headers(user)
        files: list[dict[str, Any]] = []
        seen: set[str] = set()
        for cand in candidates:
            url = cand.get("url", "").strip()
            if not url:
                continue
            resolved = self._resolve_url(url)
            if not resolved or resolved in seen:
                continue
            seen.add(resolved)
            try:
                resp = requests.get(resolved, headers=auth_headers, timeout=40)
                if resp.status_code == 401 and auth_headers:
                    resp = requests.get(resolved, timeout=40)
                resp.raise_for_status()
                content = resp.content
                if not content:
                    continue
                filename = str(cand.get("name") or self._guess_filename_from_url(resolved) or "attachment.bin")
                mime = str(cand.get("mime") or resp.headers.get("Content-Type") or "application/octet-stream")
                files.append({"name": filename, "mime": mime, "content": content})
            except Exception:
                continue
            if len(files) >= 4:
                break
        return files

    @staticmethod
    def _build_user_auth_headers(user: Any) -> dict[str, str]:
        if not isinstance(user, dict):
            return {}
        token = (
            str(user.get("token") or "")
            or str(user.get("access_token") or "")
            or str(user.get("jwt") or "")
            or str(user.get("api_key") or "")
        ).strip()
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    def _resolve_url(self, url: str) -> str:
        if url.lower().startswith(("http://", "https://")):
            return url
        base = (self.valves.openwebui_base_url or "").strip().rstrip("/")
        if not base:
            return ""
        return urljoin(base + "/", url.lstrip("/"))

    @staticmethod
    def _guess_filename_from_url(url: str) -> str:
        cleaned = url.split("?", 1)[0].rstrip("/")
        if not cleaned:
            return "attachment.bin"
        name = cleaned.split("/")[-1].strip()
        return name or "attachment.bin"

    @staticmethod
    def _iter_attachment_candidates(body: dict[str, Any]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []

        def push(url: Any, name: Any = "", mime: Any = "") -> None:
            value = str(url or "").strip()
            if not value:
                return
            out.append(
                {
                    "url": value,
                    "name": str(name or "").strip(),
                    "mime": str(mime or "").strip(),
                }
            )

        files = body.get("files", [])
        if isinstance(files, list):
            for item in files:
                if not isinstance(item, dict):
                    continue
                push(item.get("url"), item.get("name"), item.get("mime_type"))
                file_obj = item.get("file")
                if isinstance(file_obj, dict):
                    push(file_obj.get("url"), file_obj.get("name"), file_obj.get("mime_type"))
                    push(file_obj.get("web_url"), file_obj.get("name"), file_obj.get("mime_type"))
                    push(file_obj.get("download_url"), file_obj.get("name"), file_obj.get("mime_type"))

        messages = body.get("messages", [])
        if isinstance(messages, list):
            for message in messages:
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for entry in content:
                    if not isinstance(entry, dict):
                        continue
                    push(entry.get("url"), entry.get("name"), entry.get("mime_type"))
                    push(entry.get("web_url"), entry.get("name"), entry.get("mime_type"))
                    image_url = entry.get("image_url")
                    if isinstance(image_url, dict):
                        push(image_url.get("url"), entry.get("name"), entry.get("mime_type"))
                    elif isinstance(image_url, str):
                        push(image_url, entry.get("name"), entry.get("mime_type"))
                    file_obj = entry.get("file")
                    if isinstance(file_obj, dict):
                        push(file_obj.get("url"), file_obj.get("name"), file_obj.get("mime_type"))
                        push(file_obj.get("web_url"), file_obj.get("name"), file_obj.get("mime_type"))
                        push(file_obj.get("download_url"), file_obj.get("name"), file_obj.get("mime_type"))

        return out

    @staticmethod
    def _collect_requirements(user_texts: list[str]) -> dict[str, Any]:
        joined = "\n".join(user_texts)
        req: dict[str, Any] = {}

        # Label-style fields, e.g. "受众: 管理层"
        label_map = {
            "target_audience": ["受众", "目标受众", "audience"],
            "use_case": ["场景", "使用场景", "用途", "use case"],
            "color_hint": ["配色", "色彩", "色彩偏好", "color", "color hint"],
            "language": ["语言", "language"],
            "canvas_format": ["画幅", "比例", "canvas", "format"],
            "project_name": ["项目名", "项目名称", "标题", "project name"],
            "style_objective": ["风格", "style"],
            "image_strategy": ["图片策略", "图片", "生图策略", "image strategy"],
            "confirmation_mode": ["确认模式", "模式", "mode"],
            "page_count": ["页数", "pages", "page count"],
        }
        for key, aliases in label_map.items():
            pattern = rf"(?:^|\n)\s*(?:{'|'.join(re.escape(a) for a in aliases)})\s*[:：]\s*(.+)"
            matches = re.findall(pattern, joined, flags=re.IGNORECASE)
            if matches:
                req[key] = matches[-1].strip()

        # Page count from natural text.
        page_match = re.findall(r"(\d{1,2})\s*页", joined)
        if page_match:
            req["page_count"] = max(1, min(30, int(page_match[-1])))
        elif "page_count" in req:
            m = re.search(r"\d{1,2}", str(req["page_count"]))
            if m:
                req["page_count"] = max(1, min(30, int(m.group(0))))

        # Canvas normalization.
        canvas_text = str(req.get("canvas_format", "")).lower()
        if "4:3" in canvas_text or "ppt43" in canvas_text:
            req["canvas_format"] = "ppt43"
        elif "16:9" in canvas_text or "ppt169" in canvas_text:
            req["canvas_format"] = "ppt169"

        # Style normalization.
        style_text = str(req.get("style_objective", "") + "\n" + joined).lower()
        if any(token in style_text for token in ["top_consulting", "顶级咨询", "麦肯锡", "bain", "bcg"]):
            req["style_objective"] = "top_consulting"
        elif any(token in style_text for token in ["general_consulting", "咨询风", "consulting"]):
            req["style_objective"] = "general_consulting"
        elif any(token in style_text for token in ["general_versatile", "通用风", "通用", "versatile"]):
            req["style_objective"] = "general_versatile"

        # Language normalization.
        lang_text = str(req.get("language", "") + "\n" + joined).lower()
        if any(token in lang_text for token in ["中文", "chinese", "zh-cn", "zh"]):
            req["language"] = "zh-CN"
        elif any(token in lang_text for token in ["英文", "english", "en-us", "en"]):
            req["language"] = "en-US"

        # Image strategy normalization.
        image_text = str(req.get("image_strategy", "") + "\n" + joined).lower()
        if any(token in image_text for token in ["ai生图", "生图", "ai image", "image generation", "生成图片"]):
            req["image_strategy"] = "ai_generation"
        elif any(token in image_text for token in ["不生图", "不要图片", "纯文字", "placeholder", "no image"]):
            req["image_strategy"] = "placeholder"

        # Confirmation mode normalization.
        mode_text = str(req.get("confirmation_mode", "") + "\n" + joined).lower()
        if any(token in mode_text for token in ["full", "完整确认", "八项确认", "严格确认"]):
            req["confirmation_mode"] = "full"
        elif any(token in mode_text for token in ["lite", "轻确认", "简要确认"]):
            req["confirmation_mode"] = "lite"
        elif any(token in mode_text for token in ["auto", "直接生成", "自动", "不确认"]):
            req["confirmation_mode"] = "auto"

        # Simple default project name from first sentence.
        if not req.get("project_name"):
            first = user_texts[0] if user_texts else "openwebui_ppt"
            first = re.sub(r"\s+", "_", first.strip())[:40]
            first = re.sub(r"[^0-9a-zA-Z_\u4e00-\u9fff-]", "", first) or "openwebui_ppt"
            req["project_name"] = first
        return req

    @staticmethod
    def _missing_fields(req: dict[str, Any], mode: str) -> list[str]:
        lite_required = ["page_count", "style_objective", "image_strategy", "target_audience"]
        full_required = [
            "target_audience",
            "use_case",
            "page_count",
            "style_objective",
            "language",
            "image_strategy",
            "color_hint",
            "canvas_format",
        ]
        required = lite_required if mode == "lite" else full_required
        missing: list[str] = []
        for field in required:
            value = req.get(field)
            if value is None:
                missing.append(field)
                continue
            if isinstance(value, str) and not value.strip():
                missing.append(field)
        return missing

    @staticmethod
    def _render_missing_questions(mode: str, req: dict[str, Any], missing: list[str]) -> str:
        name_map = {
            "target_audience": "目标受众",
            "use_case": "使用场景",
            "page_count": "页数",
            "style_objective": "风格",
            "language": "语言",
            "image_strategy": "图片策略",
            "color_hint": "配色偏好",
            "canvas_format": "画幅比例",
        }
        current = [
            f"- 受众: {req.get('target_audience', '未提供')}",
            f"- 场景: {req.get('use_case', '未提供')}",
            f"- 页数: {req.get('page_count', '未提供')}",
            f"- 风格: {req.get('style_objective', '未提供')}",
            f"- 语言: {req.get('language', '未提供')}",
            f"- 图片策略: {req.get('image_strategy', '未提供')}",
            f"- 配色: {req.get('color_hint', '未提供')}",
            f"- 画幅: {req.get('canvas_format', '未提供')}",
        ]
        missing_text = "、".join(name_map[m] for m in missing)
        return (
            f"当前是 `{mode}` 确认模式，先补全信息再生成。\n\n"
            f"缺少：{missing_text}\n\n"
            "已识别信息：\n"
            + "\n".join(current)
            + "\n\n请按下面格式回复（可只改缺失项）：\n"
            "受众: \n"
            "场景: \n"
            "页数: \n"
            "确认模式: auto | lite | full\n"
            "风格: general_versatile | general_consulting | top_consulting\n"
            "语言: zh-CN | en-US\n"
            "图片策略: ai_generation | placeholder\n"
            "配色: \n"
            "画幅: ppt169 | ppt43"
        )

    @staticmethod
    def _render_full_confirmation(req: dict[str, Any]) -> str:
        return (
            "八项信息已齐全，待你确认后开始生成：\n"
            f"- 确认模式: full\n"
            f"- 受众: {req.get('target_audience', '')}\n"
            f"- 场景: {req.get('use_case', '')}\n"
            f"- 页数: {req.get('page_count', '')}\n"
            f"- 风格: {req.get('style_objective', '')}\n"
            f"- 语言: {req.get('language', '')}\n"
            f"- 图片策略: {req.get('image_strategy', '')}\n"
            f"- 配色: {req.get('color_hint', '')}\n"
            f"- 画幅: {req.get('canvas_format', '')}\n\n"
            "如果确认无误，请回复：`确认生成`"
        )

    @staticmethod
    def _is_explicit_confirm(text: str) -> bool:
        lowered = text.strip().lower()
        return any(token in lowered for token in ["确认生成", "开始生成", "confirm generate", "go generate"])

    def _resolve_confirmation_mode(self, parsed_mode: Any) -> str:
        if isinstance(parsed_mode, str):
            mode = parsed_mode.strip().lower()
            if mode in {"auto", "lite", "full"}:
                return mode
        mode = (self.valves.confirmation_mode or "auto").strip().lower()
        return mode if mode in {"auto", "lite", "full"} else "auto"

    @staticmethod
    def _wants_config_help(text: str) -> bool:
        lowered = text.strip().lower()
        markers = [
            "配置帮助",
            "使用说明",
            "怎么设置",
            "查看配置",
            "/ppt help",
            "/ppt config",
        ]
        return any(marker in lowered for marker in markers)

    @staticmethod
    def _render_config_help(parsed: dict[str, Any]) -> str:
        return (
            "你可以在聊天里直接指定本次生成配置（无需去后台改）：\n\n"
            "示例：\n"
            "确认模式: lite\n"
            "受众: 管理层\n"
            "场景: 季度经营复盘\n"
            "页数: 10\n"
            "风格: general_consulting\n"
            "语言: zh-CN\n"
            "图片策略: ai_generation\n"
            "配色: 蓝绿科技感\n"
            "画幅: ppt169\n"
            "然后写你的PPT需求正文。\n\n"
            "确认模式说明：\n"
            "- auto: 直接生成\n"
            "- lite: 缺关键项先追问\n"
            "- full: 八项齐全后，必须再发“确认生成”\n\n"
            f"当前已识别（本轮上下文）: 页数={parsed.get('page_count','未识别')}, 风格={parsed.get('style_objective','未识别')}, 图片策略={parsed.get('image_strategy','未识别')}"
        )
