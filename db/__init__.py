# ergane/db/__init__.py
"""Base de datos SQLite para Ergane."""

from .models import Job
from .storage import (
    init_db,
    insert_job,
    bulk_insert_jobs,
    is_duplicate,
    get_unnotified_jobs,
    mark_notified,
    get_stats,
    log_run_start,
    log_run_end,
)

__all__ = [
    "Job",
    "init_db",
    "insert_job",
    "bulk_insert_jobs",
    "is_duplicate",
    "get_unnotified_jobs",
    "mark_notified",
    "get_stats",
    "log_run_start",
    "log_run_end",
]
