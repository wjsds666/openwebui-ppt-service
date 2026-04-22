from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable

from app.core.job_store import JobStore


def run_command(
    args: Iterable[str],
    cwd: Path,
    job_store: JobStore,
    job_id: str,
    extra_env: dict[str, str] | None = None,
) -> str:
    args_list = list(args)
    job_store.append_log(job_id, f"$ {' '.join(args_list)}")
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    completed = subprocess.run(
        args_list,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if completed.stdout.strip():
        job_store.append_log(job_id, completed.stdout.strip())
    if completed.stderr.strip():
        job_store.append_log(job_id, completed.stderr.strip())
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"Command failed with exit code {completed.returncode}"
        )
    return completed.stdout
