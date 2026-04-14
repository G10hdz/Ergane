"""
ergane/db/migrate_tracking.py
Migration: add applied, applied_at, application_notes, reminded columns to jobs table.
Run once on existing databases. Idempotent — safe to run multiple times.
"""
import logging
import sqlite3

logger = logging.getLogger(__name__)


def migrate(db_path: str = "./ergane.db") -> None:
    """Add tracking columns to jobs table if they don't exist."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check existing columns
    cursor.execute("PRAGMA table_info(jobs)")
    existing = {row[1] for row in cursor.fetchall()}

    columns_to_add = {
        "applied": "INTEGER DEFAULT 0",
        "applied_at": "TEXT",
        "application_notes": "TEXT",
        "reminded": "INTEGER DEFAULT 0",
    }

    for col, col_type in columns_to_add.items():
        if col not in existing:
            cursor.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type}")
            logger.info("Added column: %s", col)
        else:
            logger.debug("Column already exists: %s", col)

    conn.commit()
    conn.close()
    logger.info("Migration complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
