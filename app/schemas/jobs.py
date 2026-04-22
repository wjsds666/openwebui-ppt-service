from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class JobInput:
    project_name: str
    source_text: str = ""
    source_url: str = ""
    source_items: list[str] = field(default_factory=list)
    canvas_format: str = "ppt169"
    page_count: int = 8
    target_audience: str = ""
    use_case: str = ""
    style_objective: str = "general_consulting"
    color_hint: str = ""
    image_strategy: str = "placeholder"
    icon_style: str = "tabler-outline"
    template_name: str = ""
    notes_style: str = "professional"
    language: str = ""
    uploaded_file_path: str = ""
    uploaded_file_name: str = ""


@dataclass
class SlidePlan:
    index: int
    title: str
    page_role: str
    file_name: str
    layout: str
    takeaway: str
    bullets: list[str] = field(default_factory=list)
    chart: str = ""
    source_note: str = ""
    image_needs: list[str] = field(default_factory=list)
    template_mapping: str = ""


@dataclass
class PlanResult:
    project_summary: str
    language: str
    canvas_format: str
    page_count: int
    target_audience: str
    use_case: str
    style_objective: str
    theme_mode: str
    tone: str
    color_scheme: dict[str, str]
    typography: dict[str, str]
    spacing: dict[str, str]
    icon_usage: dict[str, str]
    image_usage: dict[str, str]
    chart_refs: list[dict[str, str]]
    notes_plan: dict[str, str]
    slides: list[SlidePlan]


def safe_filename(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in name.strip().lower())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned[:48] or "slide"


def ensure_svg_file_name(index: int, title: str) -> str:
    return f"{index:02d}_{safe_filename(title)}.svg"


def resolve_path(value: str) -> Path:
    return Path(value).expanduser().resolve()
