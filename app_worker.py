from app.core.job_store import JobStore
from app.core.settings import load_settings
from app.services.worker import Worker


def main() -> None:
    settings = load_settings()
    store = JobStore(settings.storage_dir)
    worker = Worker(settings, store)
    worker.run_forever()


if __name__ == "__main__":
    main()
