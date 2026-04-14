"""
ergane/db/storage.py
CRUD + deduplicación + logging de runs de scraping.
Todas las operaciones son síncronas (SQLite no necesita async aquí).
"""
import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from db.models import Job

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------

@contextmanager
def get_connection(db_path: str):
    """Context manager: abre conexión, hace commit/rollback automático."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # mejor concurrencia
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Inicialización
# ---------------------------------------------------------------------------

def init_db(db_path: str) -> None:
    """Crea tablas e índices si no existen."""
    schema = _SCHEMA_PATH.read_text(encoding="utf-8")
    with get_connection(db_path) as conn:
        conn.executescript(schema)
    logger.info("DB inicializada: %s", db_path)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def insert_job(db_path: str, job: Job) -> bool:
    """
    Inserta un Job. Retorna True si fue nuevo, False si ya existía (dedup).
    La deduplicación es por url_hash (UNIQUE en schema).
    """
    sql = """
        INSERT OR IGNORE INTO jobs
            (url_hash, url, title, company, location,
             salary_min, salary_max, salary_raw, description,
             tags, source, remote, score, notified, scraped_at, posted_at)
        VALUES
            (:url_hash, :url, :title, :company, :location,
             :salary_min, :salary_max, :salary_raw, :description,
             :tags, :source, :remote, :score, :notified, :scraped_at, :posted_at)
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(sql, job.to_dict())
        inserted = cursor.rowcount > 0

    if inserted:
        logger.debug("Nuevo job: [%s] %s @ %s", job.source, job.title, job.company)
    else:
        logger.debug("Duplicado ignorado: %s", job.url_hash[:12])

    return inserted


def bulk_insert_jobs(db_path: str, jobs: list[Job]) -> tuple[int, int]:
    """
    Inserta una lista de Jobs usando una sola conexión.
    Retorna (nuevos, duplicados).
    """
    if not jobs:
        return 0, 0

    sql = """
        INSERT OR IGNORE INTO jobs
            (url_hash, url, title, company, location,
             salary_min, salary_max, salary_raw, description,
             tags, source, remote, score, notified, scraped_at, posted_at)
        VALUES
            (:url_hash, :url, :title, :company, :location,
             :salary_min, :salary_max, :salary_raw, :description,
             :tags, :source, :remote, :score, :notified, :scraped_at, :posted_at)
    """
    new, dupes = 0, 0
    with get_connection(db_path) as conn:
        for job in jobs:
            cursor = conn.execute(sql, job.to_dict())
            if cursor.rowcount > 0:
                new += 1
                logger.debug("Nuevo job: [%s] %s @ %s", job.source, job.title, job.company)
            else:
                dupes += 1

    logger.info("Bulk insert: %d nuevos, %d duplicados", new, dupes)
    return new, dupes


def is_duplicate(db_path: str, url: str) -> bool:
    """Verifica si un URL ya existe antes de scrapear su detalle."""
    import hashlib
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE url_hash = ?", (url_hash,)
        ).fetchone()
    return row is not None


def get_unnotified_jobs(
    db_path: str,
    min_score: float = 0.0,
    limit: int = 50,
) -> list[dict]:
    """
    Retorna jobs con score >= min_score que no han sido notificados.
    Ordenados por score DESC, scraped_at DESC.
    """
    sql = """
        SELECT * FROM jobs
        WHERE notified = 0 AND score >= ?
        ORDER BY score DESC, scraped_at DESC
        LIMIT ?
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(sql, (min_score, limit)).fetchall()
    return [dict(r) for r in rows]


def mark_notified(db_path: str, job_ids: list[str]) -> None:
    """Marca jobs como notificados tras enviar a Telegram.
    
    Args:
        job_ids: List of url_hash values (not integer IDs).
    """
    if not job_ids:
        return
    placeholders = ",".join("?" * len(job_ids))
    with get_connection(db_path) as conn:
        conn.execute(
            f"UPDATE jobs SET notified = 1 WHERE url_hash IN ({placeholders})",
            job_ids,
        )
    logger.info("Marcados como notificados: %d jobs", len(job_ids))


def get_stats(db_path: str) -> dict:
    """Estadísticas rápidas para debug/monitoring."""
    with get_connection(db_path) as conn:
        total     = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        notified  = conn.execute("SELECT COUNT(*) FROM jobs WHERE notified=1").fetchone()[0]
        by_source = conn.execute(
            "SELECT source, COUNT(*) as n FROM jobs GROUP BY source"
        ).fetchall()
    return {
        "total":     total,
        "notified":  notified,
        "pending":   total - notified,
        "by_source": {r["source"]: r["n"] for r in by_source},
    }


# ---------------------------------------------------------------------------
# Runs (logging de ejecuciones del scheduler)
# ---------------------------------------------------------------------------

def log_run_start(db_path: str, source: str) -> int:
    """Registra inicio de un run. Retorna run_id."""
    sql = """
        INSERT INTO runs (source, started_at, status)
        VALUES (?, ?, 'running')
    """
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        cursor = conn.execute(sql, (source, now))
        run_id = cursor.lastrowid
    return run_id


def log_run_end(
    db_path: str,
    run_id: int,
    jobs_found: int = 0,
    jobs_new: int = 0,
    status: str = "success",
    error_msg: Optional[str] = None,
) -> None:
    """Actualiza un run al terminar."""
    sql = """
        UPDATE runs
        SET finished_at = ?, jobs_found = ?, jobs_new = ?,
            status = ?, error_msg = ?
        WHERE id = ?
    """
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(sql, (now, jobs_found, jobs_new, status, error_msg, run_id))
    logger.info(
        "Run #%d [%s] terminado: status=%s, nuevos=%d/%d",
        run_id, status, status, jobs_new, jobs_found,
    )


# ---------------------------------------------------------------------------
# Job decisions (manual overrides)
# ---------------------------------------------------------------------------

def save_decision(db_path: str, url_hash: str, title: str, decision: str,
                  company: str = None, source: str = "manual",
                  profile_name: str = None, score: float = 0.0,
                  notes: str = None) -> None:
    """
    Save a manual decision for a job (interested/skipped).

    Args:
        url_hash: SHA-256 hash of job URL
        title: Job title
        decision: 'interested' or 'skipped'
        company: Company name
        source: Job source
        profile_name: Which user profile made the decision
        score: Score at time of decision
        notes: Optional user notes
    """
    sql = """
        INSERT INTO job_decisions
            (url_hash, title, company, source, decision,
             profile_name, score_at_time, notes, decided_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(sql, (url_hash, title, company, source, decision,
                           profile_name, score, notes, now))
    logger.info("Decision saved: %s -> %s for '%s'", url_hash[:12], decision, title)


def get_decision(db_path: str, url_hash: str) -> Optional[dict]:
    """Get existing decision for a job, if any."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM job_decisions WHERE url_hash = ? ORDER BY decided_at DESC LIMIT 1",
            (url_hash,)
        ).fetchone()
    return dict(row) if row else None


def get_user_decisions(db_path: str, profile_name: str = None,
                       limit: int = 20) -> list[dict]:
    """Get recent decisions, optionally filtered by profile."""
    sql = "SELECT * FROM job_decisions"
    params: list = []

    if profile_name:
        sql += " WHERE profile_name = ?"
        params.append(profile_name)

    sql += " ORDER BY decided_at DESC LIMIT ?"
    params.append(limit)

    with get_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
