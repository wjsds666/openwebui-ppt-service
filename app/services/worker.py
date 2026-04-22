from __future__ import annotations

import time

from app.core.job_store import JobStore
from app.core.settings import Settings
from app.services.orchestrator import PPTOrchestrator


class Worker:
    def __init__(self, settings: Settings, job_store: JobStore) -> None:
        self.settings = settings
        self.job_store = job_store
        self.orchestrator = PPTOrchestrator(settings, job_store)

    def run_forever(self) -> None:
        self.job_store.requeue_running_jobs()
        next_cleanup_at = 0.0
        while True:
            now = time.time()
            if now >= next_cleanup_at:
                summary = self.job_store.cleanup_expired(self.settings.export_retention_days)
                if summary["removed_jobs"] or summary["removed_exports"]:
                    print(
                        "[cleanup] removed_jobs="
                        f"{summary['removed_jobs']} removed_exports={summary['removed_exports']}"
                    )
                next_cleanup_at = now + max(300, int(self.settings.cleanup_interval_seconds))

            pending = self.job_store.list_pending_jobs()
            if not pending:
                time.sleep(self.settings.job_poll_interval_seconds)
                continue

            for job in pending:
                claimed = self.job_store.claim_job(job["job_id"])
                if claimed.get("status") != "running":
                    continue
                self.job_store.append_log(job["job_id"], "Worker picked up job.")
                try:
                    artifacts = self.orchestrator.run_job(claimed)
                except Exception as exc:  # noqa: BLE001
                    self.job_store.append_log(job["job_id"], f"Job failed: {exc}")
                    self.job_store.mark_failed(job["job_id"], str(exc))
                else:
                    self.job_store.append_log(job["job_id"], "Job completed successfully.")
                    self.job_store.mark_succeeded(job["job_id"], artifacts)
