from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class JobPaths:
    root: Path
    uploads_dir: Path
    project_root: Path
    logs_path: Path
    metadata_path: Path


class JobStore:
    def __init__(self, storage_dir: Path) -> None:
        self.storage_dir = storage_dir
        self.jobs_dir = storage_dir / "jobs"
        self.exports_dir = storage_dir / "exports"
        self.logs_dir = storage_dir / "logs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        paths = self.get_paths(job_id)
        paths.uploads_dir.mkdir(parents=True, exist_ok=True)
        paths.project_root.mkdir(parents=True, exist_ok=True)
        metadata = {
            "job_id": job_id,
            "status": "pending",
            "created_at": utcnow_iso(),
            "updated_at": utcnow_iso(),
            "payload": payload,
            "artifacts": {},
            "error": None,
        }
        self._write_json(paths.metadata_path, metadata)
        paths.logs_path.write_text("", encoding="utf-8")
        return metadata

    def get_paths(self, job_id: str) -> JobPaths:
        root = self.jobs_dir / job_id
        return JobPaths(
            root=root,
            uploads_dir=root / "uploads",
            project_root=root / "project",
            logs_path=root / "events.log",
            metadata_path=root / "job.json",
        )

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._read_json(self.get_paths(job_id).metadata_path)

    def list_pending_jobs(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        for metadata_path in sorted(self.jobs_dir.glob("*/job.json")):
            job = self._read_json(metadata_path)
            if job.get("status") == "pending":
                jobs.append(job)
        return jobs

    def list_running_jobs(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        for metadata_path in sorted(self.jobs_dir.glob("*/job.json")):
            job = self._read_json(metadata_path)
            if job.get("status") == "running":
                jobs.append(job)
        return jobs

    def requeue_running_jobs(self) -> list[str]:
        """
        Recover jobs that were left in "running" after an unexpected worker restart.
        """
        recovered: list[str] = []
        for job in self.list_running_jobs():
            job_id = str(job.get("job_id") or "")
            if not job_id:
                continue
            self.update_job(job_id, status="pending")
            self.append_log(job_id, "Recovered from stale running state after worker restart.")
            recovered.append(job_id)
        return recovered

    def claim_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job.get("status") != "pending":
            return job
        job["status"] = "running"
        job["started_at"] = utcnow_iso()
        job["updated_at"] = utcnow_iso()
        self._write_json(self.get_paths(job_id).metadata_path, job)
        return job

    def append_log(self, job_id: str, message: str) -> None:
        log_line = f"[{utcnow_iso()}] {message.rstrip()}\n"
        with self.get_paths(job_id).logs_path.open("a", encoding="utf-8") as handle:
            handle.write(log_line)

    def update_job(self, job_id: str, **updates: Any) -> dict[str, Any]:
        job = self.get_job(job_id)
        for key, value in updates.items():
            job[key] = value
        job["updated_at"] = utcnow_iso()
        self._write_json(self.get_paths(job_id).metadata_path, job)
        return job

    def mark_failed(self, job_id: str, error: str) -> dict[str, Any]:
        return self.update_job(
            job_id,
            status="failed",
            error=error,
            finished_at=utcnow_iso(),
        )

    def mark_succeeded(self, job_id: str, artifacts: dict[str, Any]) -> dict[str, Any]:
        return self.update_job(
            job_id,
            status="succeeded",
            artifacts=artifacts,
            error=None,
            finished_at=utcnow_iso(),
        )

    def read_logs(self, job_id: str) -> str:
        path = self.get_paths(job_id).logs_path
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def export_file(self, job_id: str, source_path: Path, target_name: str) -> Path:
        target_dir = self.exports_dir / job_id
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = target_dir / target_name
        shutil.copy2(source_path, destination)
        return destination

    def cleanup_expired(self, retention_days: int) -> dict[str, int]:
        """
        Delete stale finished jobs and their exports to control disk usage.
        """
        retention_days = max(1, int(retention_days))
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        removed_jobs = 0
        removed_exports = 0

        for metadata_path in sorted(self.jobs_dir.glob("*/job.json")):
            try:
                job = self._read_json(metadata_path)
            except Exception:  # noqa: BLE001
                continue

            status = str(job.get("status") or "").lower()
            if status not in {"succeeded", "failed"}:
                continue
            ts = self._job_terminal_time(job)
            if ts is None or ts >= cutoff:
                continue

            job_id = str(job.get("job_id") or metadata_path.parent.name).strip()
            job_root = metadata_path.parent
            export_root = self.exports_dir / job_id
            if job_root.exists():
                shutil.rmtree(job_root, ignore_errors=True)
                removed_jobs += 1
            if export_root.exists():
                shutil.rmtree(export_root, ignore_errors=True)
                removed_exports += 1

        return {"removed_jobs": removed_jobs, "removed_exports": removed_exports}

    @staticmethod
    def _job_terminal_time(job: dict[str, Any]) -> datetime | None:
        for key in ("finished_at", "updated_at", "created_at"):
            value = str(job.get(key) or "").strip()
            if not value:
                continue
            try:
                normalized = value.replace("Z", "+00:00")
                dt = datetime.fromisoformat(normalized)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                return dt
            except ValueError:
                continue
        return None

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
