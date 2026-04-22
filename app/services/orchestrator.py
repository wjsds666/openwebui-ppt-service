from __future__ import annotations

import json
import os
import re
import shutil
import sys
import hashlib
from urllib.parse import urlparse
from pathlib import Path
from textwrap import dedent
from typing import Any

import requests

from app.core.command_runner import run_command
from app.core.job_store import JobStore
from app.core.runtime_config import RuntimeConfigStore
from app.core.settings import Settings
from app.schemas.jobs import (
    JobInput,
    PlanResult,
    SlidePlan,
    ensure_svg_file_name,
)
from app.services.llm_client import LLMClient, extract_code_block


STYLE_FILE_MAP = {
    "general_versatile": "executor-general.md",
    "general_consulting": "executor-consultant.md",
    "top_consulting": "executor-consultant-top.md",
}


class PPTOrchestrator:
    def __init__(self, settings: Settings, job_store: JobStore) -> None:
        self.settings = settings
        self.job_store = job_store
        self.runtime_config = RuntimeConfigStore(settings)
        self.llm = LLMClient(settings, self.runtime_config)
        self.skill_dir = settings.repo_root / "skills" / "ppt-master"
        self.references_dir = self.skill_dir / "references"
        self.templates_dir = self.skill_dir / "templates"
        self.tools_python = os.getenv("PPT_MASTER_PYTHON", sys.executable)

    def run_job(self, job: dict[str, Any]) -> dict[str, Any]:
        job_id = job["job_id"]
        payload = JobInput(**job["payload"])
        self._apply_image_toggle(job_id, payload)
        project_path = self._prepare_project(job_id, payload)
        source_markdown = self._load_source_markdown(project_path)
        try:
            plan = self._create_plan(job_id, payload, source_markdown)
        except Exception as exc:  # noqa: BLE001
            self.job_store.append_log(
                job_id,
                f"Planner failed, fallback plan activated: {exc}",
            )
            plan = self._build_fallback_plan(payload, source_markdown)
        self._write_design_spec(project_path, payload, plan)
        self._copy_template_assets(project_path, payload)
        source_assets = self._collect_source_image_assets(job_id, project_path)
        markdown_assets = self._collect_markdown_image_assets(job_id, project_path)
        generated_assets = self._maybe_generate_ai_images(job_id, project_path, payload, plan)
        image_assets = self._merge_assets(source_assets, markdown_assets, generated_assets)
        self._generate_svg_pages(job_id, project_path, payload, plan, image_assets)
        self._generate_notes(job_id, project_path, payload, plan)
        artifacts = self._finalize_exports(job_id, project_path)
        return artifacts

    def _apply_image_toggle(self, job_id: str, payload: JobInput) -> None:
        runtime = self.runtime_config.load()
        ai_image_enabled = bool(runtime.get("ai_image_enabled", False))
        requested = (payload.image_strategy or "").strip().lower()
        wants_ai = requested in {"ai_generation", "ai_generate", "ai", "generate"}
        if not ai_image_enabled and wants_ai:
            payload.image_strategy = "placeholder"
            self.job_store.append_log(
                job_id,
                "AI image is disabled in /admin. Falling back to placeholder image strategy.",
            )
            return
        if ai_image_enabled and wants_ai and not str(runtime.get("image_api_key") or "").strip():
            raise RuntimeError(
                "AI image is enabled but image_api_key is empty. "
                "Please fill it in /admin before enabling AI image generation."
            )

    def _prepare_project(self, job_id: str, payload: JobInput) -> Path:
        job_paths = self.job_store.get_paths(job_id)
        projects_base = job_paths.project_root
        projects_base.mkdir(parents=True, exist_ok=True)

        init_output = run_command(
            [
                self.tools_python,
                str(self.skill_dir / "scripts" / "project_manager.py"),
                "init",
                payload.project_name,
                "--format",
                payload.canvas_format,
                "--dir",
                str(projects_base),
            ],
            cwd=self.settings.repo_root,
            job_store=self.job_store,
            job_id=job_id,
        )
        project_path = self._extract_project_path(init_output)
        self.job_store.append_log(job_id, f"Project workspace: {project_path}")

        source_items = [item.strip() for item in payload.source_items if item.strip()]
        if payload.uploaded_file_path and payload.uploaded_file_path not in source_items:
            source_items.append(payload.uploaded_file_path)
        if payload.source_url and payload.source_url not in source_items:
            source_items.append(payload.source_url)

        if source_items:
            run_command(
                [
                    self.tools_python,
                    str(self.skill_dir / "scripts" / "project_manager.py"),
                    "import-sources",
                    str(project_path),
                    *source_items,
                    "--move",
                ],
                cwd=self.settings.repo_root,
                job_store=self.job_store,
                job_id=job_id,
            )
            self.job_store.append_log(job_id, f"Imported source items: {len(source_items)}")
        elif payload.source_text:
            source_path = project_path / "sources" / "source_text.md"
            source_path.write_text(payload.source_text, encoding="utf-8")
            self.job_store.append_log(job_id, f"Wrote inline source to {source_path}")
        else:
            raise RuntimeError("No source content was provided.")

        return project_path

    def _load_source_markdown(self, project_path: Path) -> str:
        candidates = sorted(project_path.glob("sources/**/*.md"))
        if not candidates:
            candidates = sorted(project_path.glob("sources/**/*.txt"))
        parts: list[str] = []
        for path in candidates:
            if path.name == "README.md":
                continue
            parts.append(f"\n# Source: {path.name}\n\n{path.read_text(encoding='utf-8', errors='replace')}")
        if not parts:
            raise RuntimeError("No normalized markdown source was found in sources/.")
        return "\n".join(parts)[:50000]

    def _create_plan(self, job_id: str, payload: JobInput, source_markdown: str) -> PlanResult:
        strategist = (self.references_dir / "strategist.md").read_text(encoding="utf-8")
        design_spec_reference = (self.templates_dir / "design_spec_reference.md").read_text(encoding="utf-8")
        system_prompt = dedent(
            """
            You are the Strategist for PPT Master.
            Produce a single JSON object only.
            Follow the repository constraints:
            - Respect the eight confirmations from strategist.md, but auto-decide based on user input.
            - Create a concise but executable slide plan.
            - Keep page count close to the requested value.
            - Use safe, realistic icon names from tabler-outline or tabler-filled only.
            - Avoid fabricated precise statistics not present in the source.
            - Use consultant style titles that are conclusion-driven when possible.
            """
        ).strip()
        user_prompt = dedent(
            f"""
            Repository guidance:
            <strategist>
            {strategist[:16000]}
            </strategist>

            Design spec reference:
            <design_spec_reference>
            {design_spec_reference[:8000]}
            </design_spec_reference>

            User request:
            - project_name: {payload.project_name}
            - canvas_format: {payload.canvas_format}
            - page_count: {payload.page_count}
            - target_audience: {payload.target_audience or "auto"}
            - use_case: {payload.use_case or "auto"}
            - style_objective: {payload.style_objective}
            - color_hint: {payload.color_hint or "auto"}
            - image_strategy: {payload.image_strategy}
            - icon_style: {payload.icon_style}
            - template_name: {payload.template_name or "none"}
            - notes_style: {payload.notes_style}
            - preferred_language: {payload.language or "auto"}

            Source markdown:
            <source_markdown>
            {source_markdown}
            </source_markdown>

            Return JSON with this shape:
            {{
              "project_summary": "...",
              "language": "zh-CN",
              "canvas_format": "{payload.canvas_format}",
              "page_count": {payload.page_count},
              "target_audience": "...",
              "use_case": "...",
              "style_objective": "{payload.style_objective}",
              "theme_mode": "light",
              "tone": "...",
              "color_scheme": {{
                "background": "#FFFFFF",
                "secondary_bg": "#F8FAFC",
                "primary": "#0F62FE",
                "accent": "#16A34A",
                "secondary_accent": "#38BDF8",
                "body_text": "#0F172A",
                "secondary_text": "#475569",
                "tertiary_text": "#94A3B8",
                "border": "#CBD5E1",
                "success": "#16A34A",
                "warning": "#DC2626"
              }},
              "typography": {{
                "preset": "P1",
                "title_font": "Microsoft YaHei",
                "body_font": "Microsoft YaHei",
                "emphasis_font": "SimHei",
                "english_title_font": "Arial",
                "english_body_font": "Calibri",
                "body_size": "18",
                "content_title_size": "30"
              }},
              "spacing": {{
                "margins": "left/right 60px, top 50px, bottom 40px",
                "card_gap": "24",
                "card_padding": "24",
                "border_radius": "16"
              }},
              "icon_usage": {{
                "mode": "built-in",
                "library": "{payload.icon_style}",
                "notes": "..."
              }},
              "image_usage": {{
                "mode": "{payload.image_strategy}",
                "notes": "..."
              }},
              "chart_refs": [
                {{"chart_type": "bar_chart", "used_in": "03_xxx", "reason": "..."}}
              ],
              "notes_plan": {{
                "total_duration": "12 minutes",
                "notes_style": "{payload.notes_style}",
                "purpose": "inform"
              }},
              "slides": [
                {{
                  "index": 1,
                  "title": "Cover Title",
                  "page_role": "cover",
                  "file_name": "01_cover.svg",
                  "layout": "full-screen cover",
                  "takeaway": "Core message",
                  "bullets": ["...", "..."],
                  "chart": "",
                  "source_note": "",
                  "image_needs": [],
                  "template_mapping": "free design"
                }}
              ]
            }}

            Rules:
            - page_role should be one of: cover, agenda, chapter, content, ending.
            - slides length must equal page_count.
            - file_name must be unique and end with .svg.
            - use source-grounded wording and avoid hallucinated references.
            """
        ).strip()
        result = self.llm.complete_json(system_prompt, user_prompt)
        slides = [
            SlidePlan(
                index=int(item["index"]),
                title=item["title"],
                page_role=item["page_role"],
                file_name=item.get("file_name") or ensure_svg_file_name(int(item["index"]), item["title"]),
                layout=item["layout"],
                takeaway=item.get("takeaway", ""),
                bullets=list(item.get("bullets", [])),
                chart=item.get("chart", ""),
                source_note=item.get("source_note", ""),
                image_needs=list(item.get("image_needs", [])),
                template_mapping=item.get("template_mapping", "free design"),
            )
            for item in result["slides"]
        ]
        if len(slides) != int(result["page_count"]):
            raise RuntimeError("Planner returned slide count inconsistent with page_count.")
        return PlanResult(
            project_summary=result["project_summary"],
            language=result["language"],
            canvas_format=result["canvas_format"],
            page_count=int(result["page_count"]),
            target_audience=result["target_audience"],
            use_case=result["use_case"],
            style_objective=result["style_objective"],
            theme_mode=result["theme_mode"],
            tone=result["tone"],
            color_scheme=result["color_scheme"],
            typography=result["typography"],
            spacing=result["spacing"],
            icon_usage=result["icon_usage"],
            image_usage=result["image_usage"],
            chart_refs=list(result.get("chart_refs", [])),
            notes_plan=result["notes_plan"],
            slides=slides,
        )

    def _build_fallback_plan(self, payload: JobInput, source_markdown: str) -> PlanResult:
        page_count = max(3, min(30, int(payload.page_count or 8)))
        key_lines = self._extract_key_lines(source_markdown, limit=max(8, page_count * 2))

        def line_at(idx: int, default: str) -> str:
            return key_lines[idx] if idx < len(key_lines) else default

        slides: list[SlidePlan] = []
        for idx in range(1, page_count + 1):
            if idx == 1:
                role = "cover"
                title = payload.project_name or "演示文稿"
                bullets = [line_at(0, "基于源资料自动生成"), line_at(1, "结构化呈现关键内容")]
            elif idx == page_count:
                role = "ending"
                title = "结论与下一步"
                bullets = [line_at(idx + 1, "总结核心发现"), "明确行动建议与落地路径"]
            elif idx == 2:
                role = "agenda"
                title = "目录"
                bullets = ["背景与现状", "关键分析", "改进建议", "执行计划"]
            else:
                role = "content"
                title = f"关键内容 {idx - 2}"
                bullets = [
                    line_at(idx + 1, f"内容要点 {idx - 2}"),
                    line_at(idx + 2, "补充证据与说明"),
                    line_at(idx + 3, "影响与建议"),
                ]
            slides.append(
                SlidePlan(
                    index=idx,
                    title=title,
                    page_role=role,
                    file_name=ensure_svg_file_name(idx, title),
                    layout="structured content layout",
                    takeaway=bullets[0] if bullets else title,
                    bullets=bullets,
                    chart="bar_chart" if role == "content" and idx % 2 == 0 else "",
                    source_note="auto-fallback-plan",
                    image_needs=[f"{title} related illustrative image"] if role in {"cover", "content"} else [],
                    template_mapping="free design",
                )
            )

        return PlanResult(
            project_summary=(key_lines[0] if key_lines else "基于源资料的自动生成演示文稿"),
            language=payload.language or "zh-CN",
            canvas_format=payload.canvas_format or "ppt169",
            page_count=page_count,
            target_audience=payload.target_audience or "通用受众",
            use_case=payload.use_case or "汇报",
            style_objective=payload.style_objective or "general_consulting",
            theme_mode="light",
            tone="professional",
            color_scheme={
                "background": "#FFFFFF",
                "secondary_bg": "#F8FAFC",
                "primary": "#0F62FE",
                "accent": "#0EA5A4",
                "secondary_accent": "#38BDF8",
                "body_text": "#0F172A",
                "secondary_text": "#475569",
                "tertiary_text": "#94A3B8",
                "border": "#CBD5E1",
                "success": "#16A34A",
                "warning": "#DC2626",
            },
            typography={
                "preset": "P1",
                "title_font": "Microsoft YaHei",
                "body_font": "Microsoft YaHei",
                "emphasis_font": "SimHei",
                "english_title_font": "Arial",
                "english_body_font": "Calibri",
                "body_size": "18",
                "content_title_size": "30",
            },
            spacing={
                "margins": "left/right 60px, top 50px, bottom 40px",
                "card_gap": "24",
                "card_padding": "24",
                "border_radius": "16",
            },
            icon_usage={
                "mode": "built-in",
                "library": payload.icon_style or "tabler-outline",
                "notes": "Fallback mode",
            },
            image_usage={
                "mode": payload.image_strategy or "placeholder",
                "notes": "Fallback planner image strategy",
            },
            chart_refs=[{"chart_type": "bar_chart", "used_in": "content", "reason": "fallback structure"}],
            notes_plan={
                "total_duration": f"{max(8, page_count)} minutes",
                "notes_style": payload.notes_style or "professional",
                "purpose": "inform",
            },
            slides=slides,
        )

    @staticmethod
    def _extract_key_lines(source_markdown: str, limit: int = 12) -> list[str]:
        lines: list[str] = []
        for raw in source_markdown.splitlines():
            text = raw.strip()
            if not text:
                continue
            if text.startswith("#"):
                text = text.lstrip("#").strip()
            text = re.sub(r"\s+", " ", text)
            if len(text) < 8:
                continue
            if text not in lines:
                lines.append(text[:120])
            if len(lines) >= limit:
                break
        return lines

    def _write_design_spec(self, project_path: Path, payload: JobInput, plan: PlanResult) -> None:
        chart_rows = "\n".join(
            f"| {row.get('chart_type', '')} | {row.get('chart_type', '')}.svg | {row.get('used_in', '')} |"
            for row in plan.chart_refs
        ) or "| None | - | - |"
        slide_sections = []
        for slide in plan.slides:
            bullets = "\n".join(f"  - {item}" for item in slide.bullets) or "  - TBD"
            chart_line = f"- **Chart**: {slide.chart}\n" if slide.chart else ""
            slide_sections.append(
                dedent(
                    f"""
                    #### Slide {slide.index:02d} - {slide.title}

                    - **Layout**: {slide.layout}
                    - **Template mapping**: {slide.template_mapping}
                    - **Takeaway**: {slide.takeaway}
                    {chart_line}- **Content**:
                    {bullets}
                    """
                ).strip()
            )
        slide_outline = "\n\n".join(slide_sections)

        design_spec = dedent(
            f"""
            # {payload.project_name} - Design Spec

            ## I. Project Information

            | Item | Value |
            | ---- | ----- |
            | **Project Name** | {payload.project_name} |
            | **Canvas Format** | {plan.canvas_format} |
            | **Page Count** | {plan.page_count} |
            | **Design Style** | {plan.style_objective} |
            | **Target Audience** | {plan.target_audience} |
            | **Use Case** | {plan.use_case} |

            ---

            ## II. Canvas Specification

            | Property | Value |
            | -------- | ----- |
            | **Format** | {plan.canvas_format} |
            | **Margins** | {plan.spacing.get("margins", "")} |

            ---

            ## III. Visual Theme

            - **Theme**: {plan.theme_mode}
            - **Tone**: {plan.tone}
            - **Summary**: {plan.project_summary}

            | Role | HEX | Purpose |
            | ---- | --- | ------- |
            | **Background** | `{plan.color_scheme.get("background", "")}` | Page background |
            | **Secondary bg** | `{plan.color_scheme.get("secondary_bg", "")}` | Card background |
            | **Primary** | `{plan.color_scheme.get("primary", "")}` | Main emphasis |
            | **Accent** | `{plan.color_scheme.get("accent", "")}` | Highlight |
            | **Secondary accent** | `{plan.color_scheme.get("secondary_accent", "")}` | Gradient / secondary highlight |
            | **Body text** | `{plan.color_scheme.get("body_text", "")}` | Main body text |
            | **Secondary text** | `{plan.color_scheme.get("secondary_text", "")}` | Notes |
            | **Tertiary text** | `{plan.color_scheme.get("tertiary_text", "")}` | Meta text |
            | **Border/divider** | `{plan.color_scheme.get("border", "")}` | Borders |
            | **Success** | `{plan.color_scheme.get("success", "")}` | Positive |
            | **Warning** | `{plan.color_scheme.get("warning", "")}` | Risk |

            ---

            ## IV. Typography System

            - **Preset**: {plan.typography.get("preset", "")}
            - **Title font**: {plan.typography.get("title_font", "")}
            - **Body font**: {plan.typography.get("body_font", "")}
            - **Emphasis font**: {plan.typography.get("emphasis_font", "")}
            - **Body size**: {plan.typography.get("body_size", "")}px
            - **Content title size**: {plan.typography.get("content_title_size", "")}px

            ---

            ## V. Layout Principles

            - **Card gap**: {plan.spacing.get("card_gap", "")}px
            - **Card padding**: {plan.spacing.get("card_padding", "")}px
            - **Border radius**: {plan.spacing.get("border_radius", "")}px

            ---

            ## VI. Icon Usage Specification

            - **Mode**: {plan.icon_usage.get("mode", "")}
            - **Library**: {plan.icon_usage.get("library", "")}
            - **Notes**: {plan.icon_usage.get("notes", "")}

            ---

            ## VII. Chart Reference List

            | Chart Type | Reference Template | Used In |
            | ---------- | ------------------ | ------- |
            {chart_rows}

            ---

            ## VIII. Image Resource List

            | Filename | Dimensions | Ratio | Purpose | Type | Status | Generation Description |
            | -------- | ---------- | ----- | ------- | ---- | ------ | --------------------- |
            | auto | auto | auto | {plan.image_usage.get("notes", "")} | Mixed | {plan.image_usage.get("mode", "")} | {plan.image_usage.get("notes", "")} |

            ---

            ## IX. Content Outline

            {slide_outline}

            ---

            ## X. Speaker Notes Plan

            - **Total duration**: {plan.notes_plan.get("total_duration", "")}
            - **Style**: {plan.notes_plan.get("notes_style", "")}
            - **Purpose**: {plan.notes_plan.get("purpose", "")}
            """
        ).strip() + "\n"
        (project_path / "design_spec.md").write_text(design_spec, encoding="utf-8")

    def _copy_template_assets(self, project_path: Path, payload: JobInput) -> None:
        if not payload.template_name:
            return
        source_dir = self.templates_dir / "layouts" / payload.template_name
        if not source_dir.exists():
            raise RuntimeError(f"Template not found: {payload.template_name}")
        target_dir = project_path / "templates"
        for path in source_dir.iterdir():
            if path.is_file():
                shutil.copy2(path, target_dir / path.name)

    def _generate_svg_pages(
        self,
        job_id: str,
        project_path: Path,
        payload: JobInput,
        plan: PlanResult,
        image_assets: list[str],
    ) -> None:
        executor_base = (self.references_dir / "executor-base.md").read_text(encoding="utf-8")
        shared = (self.references_dir / "shared-standards.md").read_text(encoding="utf-8")
        style_reference = self._load_style_reference(plan.style_objective)
        image_context = (
            "\n".join(f"- {name}" for name in image_assets)
            if image_assets
            else "- No generated images. Use pure vector layout or placeholders."
        )
        for slide in plan.slides:
            template_content = self._load_template_reference(project_path, slide.page_role)
            self.job_store.append_log(job_id, f"Generating slide {slide.index:02d}: {slide.title}")
            base_prompt = dedent(
                f"""
                Common executor rules:
                <executor_base>
                {executor_base[:10000]}
                </executor_base>

                Shared technical standards:
                <shared_standards>
                {shared[:10000]}
                </shared_standards>

                Style reference:
                <style_reference>
                {style_reference[:7000]}
                </style_reference>

                Design spec:
                <design_spec>
                {(project_path / "design_spec.md").read_text(encoding="utf-8")[:16000]}
                </design_spec>

                Template reference:
                <template_reference>
                {template_content}
                </template_reference>

                Available project image assets (in ../images/):
                {image_context}

                Generate exactly one SVG page.
                Requirements:
                - Output raw SVG only, no prose.
                - File name: {slide.file_name}
                - Page role: {slide.page_role}
                - Page title: {slide.title}
                - Layout: {slide.layout}
                - Takeaway: {slide.takeaway}
                - Bullet points: {json.dumps(slide.bullets, ensure_ascii=False)}
                - Chart: {slide.chart or "none"}
                - Source note: {slide.source_note or "none"}
                - Image needs: {json.dumps(slide.image_needs, ensure_ascii=False)}
                - Use {plan.icon_usage.get("library", payload.icon_style)} icons only when necessary.
                - Keep the SVG PowerPoint-safe: no clipPath, no mask, no style tag, no class, no foreignObject.
                - Add logical <g> groups for editable PowerPoint groups.
                - Include a background rect.
                - Prefer source-derived assets (files prefixed with "src_") when they fit the slide semantics.
                - If suitable, reference image assets via <image href="../images/<filename>" .../>.
                """
            ).strip()
            if image_assets and slide.page_role in {"cover", "content"}:
                base_prompt += dedent(
                    """

                    Additional hard rule for this page:
                    - You MUST include at least one project image asset from ../images/ using an <image ...> tag.
                    - Keep text away from the image focal area and ensure readability.
                    """
                ).strip()
            svg_text = self._generate_single_svg_with_retry(base_prompt)
            (project_path / "svg_output" / slide.file_name).write_text(svg_text + "\n", encoding="utf-8")

    def _maybe_generate_ai_images(
        self,
        job_id: str,
        project_path: Path,
        payload: JobInput,
        plan: PlanResult,
    ) -> list[str]:
        requested = (payload.image_strategy or "").strip().lower()
        wants_ai = requested in {"ai_generation", "ai_generate", "ai", "generate"}
        if not wants_ai:
            return []

        runtime = self.runtime_config.load()
        if not bool(runtime.get("ai_image_enabled", False)):
            self.job_store.append_log(job_id, "AI image disabled; skip image generation.")
            return []

        backend = str(runtime.get("image_backend") or "openai").strip().lower()
        api_key = str(runtime.get("image_api_key") or "").strip()
        if not api_key:
            raise RuntimeError("AI image generation requested but image_api_key is empty.")

        image_model = str(runtime.get("image_model") or "").strip()
        image_base_url = str(runtime.get("image_base_url") or "").strip()
        images_dir = project_path / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        image_targets = self._collect_image_targets(plan)
        if not image_targets:
            self.job_store.append_log(job_id, "No image targets detected in plan; skip image generation.")
            return []

        self.job_store.append_log(
            job_id,
            f"AI image generation enabled. backend={backend}, targets={len(image_targets)}",
        )

        generated: list[str] = []
        for index, item in enumerate(image_targets, start=1):
            safe_stem = self._safe_image_stem(item["name"], index)
            prompt = item["prompt"]
            before_files = {p.name for p in images_dir.iterdir() if p.is_file()}
            command = [
                self.tools_python,
                str(self.skill_dir / "scripts" / "image_gen.py"),
                prompt,
                "--aspect_ratio",
                "16:9",
                "--image_size",
                "1K",
                "--backend",
                backend,
                "-o",
                str(images_dir),
                "--filename",
                safe_stem,
            ]
            env = self._image_env(backend=backend, api_key=api_key, model=image_model, base_url=image_base_url)
            try:
                run_command(
                    command,
                    cwd=self.settings.repo_root,
                    job_store=self.job_store,
                    job_id=job_id,
                    extra_env=env,
                )
            except Exception as exc:  # noqa: BLE001
                self.job_store.append_log(
                    job_id,
                    f"AI image generation failed for target {index} ({safe_stem}): {exc}",
                )
                continue
            after_files = [p.name for p in images_dir.iterdir() if p.is_file() and p.name not in before_files]
            if after_files:
                generated.extend(sorted(after_files))
            else:
                # Conservative fallback when backend overwrites an existing file with same name.
                generated.append(f"{safe_stem}.*")
        if generated:
            self.job_store.append_log(job_id, f"Generated {len(generated)} AI image(s): {', '.join(generated)}")
        else:
            self.job_store.append_log(
                job_id,
                "No AI image generated successfully. Continue with vector/placeholder layout.",
            )
        return generated

    def _collect_source_image_assets(self, job_id: str, project_path: Path) -> list[str]:
        """
        Collect source images imported from URLs/docs and copy them into project/images
        so Executor can reference them directly.
        """
        images_dir = project_path / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        sources_dir = project_path / "sources"
        if not sources_dir.exists():
            return []

        exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
        candidates: list[Path] = []
        for path in sorted(sources_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in exts:
                continue
            if path.stat().st_size < 1024:
                continue
            candidates.append(path)

        if not candidates:
            self.job_store.append_log(job_id, "No source images found in sources/.")
            return []

        copied: list[str] = []
        seen_hashes: set[str] = set()
        for idx, src in enumerate(candidates[:20], start=1):
            digest = hashlib.md5(src.read_bytes()).hexdigest()  # noqa: S324
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", src.stem).strip("_")[:36] or f"img_{idx:02d}"
            target_name = f"src_{idx:02d}_{stem}{src.suffix.lower()}"
            target_path = images_dir / target_name
            counter = 2
            while target_path.exists():
                target_name = f"src_{idx:02d}_{stem}_{counter}{src.suffix.lower()}"
                target_path = images_dir / target_name
                counter += 1
            shutil.copy2(src, target_path)
            copied.append(target_name)

        if copied:
            self.job_store.append_log(
                job_id,
                f"Imported {len(copied)} source image(s) into images/: {', '.join(copied[:8])}"
                + (" ..." if len(copied) > 8 else ""),
            )
        return copied

    def _collect_markdown_image_assets(self, job_id: str, project_path: Path) -> list[str]:
        """
        Download image URLs referenced in markdown/html source files into project/images.
        This helps reuse images from source web pages and markdown materials.
        """
        sources_dir = project_path / "sources"
        if not sources_dir.exists():
            return []
        images_dir = project_path / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        md_files = sorted(sources_dir.rglob("*.md")) + sorted(sources_dir.rglob("*.markdown"))
        if not md_files:
            return []

        url_pattern = re.compile(r"(https?://[^\s)\]>'\"`]+)", flags=re.IGNORECASE)
        collected_urls: list[str] = []
        for md in md_files:
            text = md.read_text(encoding="utf-8", errors="replace")
            # Markdown image syntax and generic URL fallback.
            for url in re.findall(r"!\[[^\]]*\]\((https?://[^)]+)\)", text, flags=re.IGNORECASE):
                normalized = url.strip().rstrip(".,;")
                if normalized and normalized not in collected_urls:
                    collected_urls.append(normalized)
            for url in url_pattern.findall(text):
                normalized = str(url).strip().rstrip(".,;")
                if not normalized or normalized in collected_urls:
                    continue
                lowered = normalized.lower()
                if any(lowered.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")):
                    collected_urls.append(normalized)

        if not collected_urls:
            return []

        copied: list[str] = []
        seen_hashes: set[str] = set()
        for idx, url in enumerate(collected_urls[:20], start=1):
            try:
                resp = requests.get(
                    url,
                    timeout=20,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
                        )
                    },
                )
                resp.raise_for_status()
                content_type = str(resp.headers.get("Content-Type", "")).lower()
                if "image" not in content_type and len(resp.content) < 1024:
                    continue
                digest = hashlib.md5(resp.content).hexdigest()  # noqa: S324
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)

                parsed = urlparse(url)
                ext = Path(parsed.path).suffix.lower()
                if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
                    if "png" in content_type:
                        ext = ".png"
                    elif "webp" in content_type:
                        ext = ".webp"
                    elif "gif" in content_type:
                        ext = ".gif"
                    elif "svg" in content_type:
                        ext = ".svg"
                    else:
                        ext = ".jpg"
                stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(parsed.path).stem).strip("_")[:32]
                if not stem:
                    stem = f"web_{idx:02d}"
                filename = f"src_web_{idx:02d}_{stem}{ext}"
                target = images_dir / filename
                counter = 2
                while target.exists():
                    filename = f"src_web_{idx:02d}_{stem}_{counter}{ext}"
                    target = images_dir / filename
                    counter += 1
                target.write_bytes(resp.content)
                copied.append(filename)
            except Exception as exc:  # noqa: BLE001
                self.job_store.append_log(job_id, f"Skip markdown image url ({url}): {exc}")

        if copied:
            self.job_store.append_log(
                job_id,
                f"Downloaded {len(copied)} markdown/web image(s) into images/: {', '.join(copied[:8])}"
                + (" ..." if len(copied) > 8 else ""),
            )
        return copied

    @staticmethod
    def _merge_assets(*groups: list[str]) -> list[str]:
        merged: list[str] = []
        for group in groups:
            for name in group:
                if name not in merged:
                    merged.append(name)
        return merged

    @staticmethod
    def _safe_image_stem(text: str, idx: int) -> str:
        clean = re.sub(r"[^a-zA-Z0-9_-]+", "_", text.strip().lower()).strip("_")
        if not clean:
            clean = f"image_{idx:02d}"
        return clean[:48]

    @staticmethod
    def _image_env(backend: str, api_key: str, model: str, base_url: str) -> dict[str, str]:
        env: dict[str, str] = {
            "IMAGE_BACKEND": backend,
        }
        if backend == "openai":
            env["OPENAI_API_KEY"] = api_key
            if model:
                env["OPENAI_MODEL"] = model
            if base_url:
                env["OPENAI_BASE_URL"] = base_url
        elif backend == "qwen":
            env["QWEN_API_KEY"] = api_key
            if model:
                env["QWEN_MODEL"] = model
            if base_url:
                env["QWEN_BASE_URL"] = base_url
        elif backend == "gemini":
            env["GEMINI_API_KEY"] = api_key
            if model:
                env["GEMINI_MODEL"] = model
            if base_url:
                env["GEMINI_BASE_URL"] = base_url
        elif backend == "siliconflow":
            env["SILICONFLOW_API_KEY"] = api_key
            if model:
                env["SILICONFLOW_MODEL"] = model
            if base_url:
                normalized = base_url.rstrip("/")
                if normalized.endswith("/v1"):
                    normalized = normalized[:-3]
                env["SILICONFLOW_BASE_URL"] = normalized
        else:
            # Generic fallback for other backends supported by image_gen.py
            env["IMAGE_API_KEY"] = api_key
            if model:
                env["IMAGE_MODEL"] = model
            if base_url:
                env["IMAGE_BASE_URL"] = base_url
        return env

    @staticmethod
    def _collect_image_targets(plan: PlanResult) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []
        # Prefer explicit image_needs from slide plan.
        for slide in plan.slides:
            for idx, need in enumerate(slide.image_needs, start=1):
                if isinstance(need, dict):
                    need_text = str(
                        need.get("prompt")
                        or need.get("description")
                        or need.get("text")
                        or ""
                    )
                else:
                    need_text = str(need)
                need_clean = need_text.strip()
                if not need_clean:
                    continue
                targets.append(
                    {
                        "name": f"{slide.index:02d}_{slide.title}_{idx}",
                        "prompt": need_clean,
                    }
                )
        if targets:
            return targets[:3]
        # Fallback: generate cover + one content image prompt from slide meaning.
        fallback: list[dict[str, str]] = []
        for slide in plan.slides:
            if slide.page_role in {"cover", "content"}:
                fallback.append(
                    {
                        "name": f"{slide.index:02d}_{slide.title}",
                        "prompt": (
                            f"{slide.title}; {slide.takeaway or ''}; "
                            "high-quality presentation background image, clean composition, no text"
                        ).strip(),
                    }
                )
            if len(fallback) >= 2:
                break
        return fallback
    def _generate_single_svg_with_retry(self, base_prompt: str) -> str:
        last_error: Exception | None = None
        for attempt in range(3):
            prompt = base_prompt
            if attempt > 0:
                prompt = (
                    f"{base_prompt}\n\n"
                    "IMPORTANT RETRY INSTRUCTION:\n"
                    "Return a complete <svg>...</svg> document only.\n"
                    "No markdown fences.\n"
                    "No explanation text.\n"
                    "The first non-space character must be '<'."
                )
            try:
                svg = self.llm.complete_text(
                    "You are the PPT Master Executor. Return one valid SVG document only.",
                    prompt,
                    temperature=0.15,
                )
                svg_text = extract_code_block(svg, "svg")
                self._validate_svg(svg_text)
                return svg_text
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("Failed to generate SVG page.")

    def _generate_notes(
        self,
        job_id: str,
        project_path: Path,
        payload: JobInput,
        plan: PlanResult,
    ) -> None:
        slides_json = [
            {
                "index": slide.index,
                "title": slide.title,
                "takeaway": slide.takeaway,
                "bullets": slide.bullets,
            }
            for slide in plan.slides
        ]
        prompt = dedent(
            f"""
            Create speaker notes for this PPT Master project.
            Language: {plan.language}
            Notes style: {plan.notes_plan.get("notes_style", payload.notes_style)}
            Purpose: {plan.notes_plan.get("purpose", "inform")}
            Total duration: {plan.notes_plan.get("total_duration", "10 minutes")}

            Slides:
            {json.dumps(slides_json, ensure_ascii=False, indent=2)}

            Output markdown only.
            Format:
            - Each page starts with "# <svg-file-name without .svg>"
            - Separate pages with "---"
            - Each page should have 2-5 natural sentences
            - Include localized "Key points:" and "Duration:" labels matching the slide language
            - From the second page onward, start with a localized transition marker
            """
        ).strip()
        notes = self.llm.complete_text(
            "You write concise, presentation-ready speaker notes in markdown only.",
            prompt,
            temperature=0.3,
        )
        normalized = notes.strip()
        if not any(line.startswith("# ") for line in normalized.splitlines()):
            normalized = self._build_fallback_notes(plan)
            self.job_store.append_log(
                job_id,
                "Notes fallback applied because model output missed '# ' headings required by total_md_split.py.",
            )
        (project_path / "notes" / "total.md").write_text(normalized + "\n", encoding="utf-8")
        self.job_store.append_log(job_id, "Speaker notes written to notes/total.md")

    @staticmethod
    def _build_fallback_notes(plan: PlanResult) -> str:
        sections: list[str] = []
        for slide in plan.slides:
            stem = Path(slide.file_name).stem
            bullets = slide.bullets[:3] if slide.bullets else [slide.takeaway or slide.title]
            bullet_line = "；".join(item for item in bullets if item) or slide.title
            sections.append(
                "\n".join(
                    [
                        f"# {stem}",
                        f"[过渡] 这一页聚焦：{slide.title}。",
                        f"重点说明：{bullet_line}。",
                        f"要点：① {slide.takeaway or slide.title} ② 信息支撑 ③ 下一步行动",
                        "时长：1 分钟",
                    ]
                )
            )
        return "\n\n---\n\n".join(sections)

    def _finalize_exports(self, job_id: str, project_path: Path) -> dict[str, Any]:
        for script_name in ("total_md_split.py", "finalize_svg.py"):
            run_command(
                [self.tools_python, str(self.skill_dir / "scripts" / script_name), str(project_path)],
                cwd=self.settings.repo_root,
                job_store=self.job_store,
                job_id=job_id,
            )
        run_command(
            [
                self.tools_python,
                str(self.skill_dir / "scripts" / "svg_to_pptx.py"),
                str(project_path),
                "-s",
                "final",
            ],
            cwd=self.settings.repo_root,
            job_store=self.job_store,
            job_id=job_id,
        )

        native_pptx = sorted(project_path.glob("*.pptx"))
        if not native_pptx:
            raise RuntimeError("No PPTX artifacts were generated.")

        artifacts: dict[str, Any] = {
            "project_path": str(project_path),
            "files": [],
        }
        for path in native_pptx:
            exported = self.job_store.export_file(job_id, path, path.name)
            file_kind = "svg_reference" if path.name.endswith("_svg.pptx") else "native"
            artifacts["files"].append(
                {
                    "kind": file_kind,
                    "name": path.name,
                    "path": str(exported),
                }
            )
        return artifacts

    @staticmethod
    def _extract_project_path(command_output: str) -> Path:
        for line in command_output.splitlines():
            if line.startswith("Project created:"):
                return Path(line.split("Project created:", 1)[1].strip())
        raise RuntimeError("Unable to parse project path from project_manager output.")

    def _load_style_reference(self, style_objective: str) -> str:
        file_name = STYLE_FILE_MAP.get(style_objective, "executor-consultant.md")
        return (self.references_dir / file_name).read_text(encoding="utf-8")

    @staticmethod
    def _validate_svg(svg_text: str) -> None:
        lowered = svg_text.lower()
        banned = ["<clippath", "<mask", "<style", " class=", "<foreignobject", "<script", "marker-end"]
        for token in banned:
            if token in lowered:
                raise RuntimeError(f"Generated SVG contains banned token: {token}")
        if "<svg" not in lowered:
            raise RuntimeError("Model response did not contain an SVG document.")

    @staticmethod
    def _load_template_reference(project_path: Path, page_role: str) -> str:
        template_dir = project_path / "templates"
        if not template_dir.exists():
            return "free design"
        role_map = {
            "cover": "01_cover.svg",
            "agenda": "02_toc.svg",
            "chapter": "02_chapter.svg",
            "content": "03_content.svg",
            "ending": "04_ending.svg",
        }
        template_name = role_map.get(page_role)
        if not template_name:
            return "free design"
        candidate = template_dir / template_name
        if not candidate.exists():
            return "free design"
        return candidate.read_text(encoding="utf-8")[:6000]
