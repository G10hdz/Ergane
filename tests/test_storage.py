import pytest
import sqlite3
from pathlib import Path
from db.models import Job
from db.storage import (
    init_db,
    get_connection,
    insert_job,
    bulk_insert_jobs,
    is_duplicate,
    get_unnotified_jobs,
    mark_notified,
    get_stats,
    log_run_start,
    log_run_end,
    save_decision,
    get_decision,
    get_user_decisions,
)

@pytest.fixture
def tmp_db_path(tmp_path):
    db_path = str(tmp_path / "test_ergane.db")
    init_db(db_path)
    return db_path

@pytest.fixture
def sample_job():
    return Job(
        url="https://example.com/job1",
        title="Backend Engineer",
        source="test_source",
        company="Test Co",
        location="Remote",
        score=0.85
    )

@pytest.fixture
def sample_job2():
    return Job(
        url="https://example.com/job2",
        title="MLOps Engineer",
        source="test_source",
        company="AI Corp",
        score=0.95
    )

def test_init_db(tmp_db_path):
    with get_connection(tmp_db_path) as conn:
        res = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = [r["name"] for r in res]
        assert "jobs" in tables
        assert "runs" in tables
        assert "job_decisions" in tables

def test_insert_job_and_duplicate(tmp_db_path, sample_job):
    # Insert new job
    inserted = insert_job(tmp_db_path, sample_job)
    assert inserted is True
    
    # Check it exists
    with get_connection(tmp_db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE url_hash = ?", (sample_job.url_hash,)).fetchone()
        assert row is not None
        assert row["title"] == "Backend Engineer"
        assert row["company"] == "Test Co"
    
    # Checking deduplication logic
    assert is_duplicate(tmp_db_path, sample_job.url) is True
    assert is_duplicate(tmp_db_path, "https://example.com/other") is False
    
    # Re-insert should return False
    inserted_again = insert_job(tmp_db_path, sample_job)
    assert inserted_again is False

def test_bulk_insert_jobs(tmp_db_path, sample_job, sample_job2):
    # Insert both
    new, dupes = bulk_insert_jobs(tmp_db_path, [sample_job, sample_job2])
    assert new == 2
    assert dupes == 0
    
    # Insert one new and one duplicate
    sample_job3 = Job(url="https://example.com/job3", title="Data Eng", source="test")
    new, dupes = bulk_insert_jobs(tmp_db_path, [sample_job2, sample_job3])
    assert new == 1
    assert dupes == 1

def test_unnotified_jobs_and_mark_notified(tmp_db_path, sample_job, sample_job2):
    bulk_insert_jobs(tmp_db_path, [sample_job, sample_job2])
    
    # Get unnotified jobs with min_score 0.9
    jobs_90 = get_unnotified_jobs(tmp_db_path, min_score=0.9)
    assert len(jobs_90) == 1
    assert jobs_90[0]["url_hash"] == sample_job2.url_hash
    
    # Get all unnotified
    all_jobs = get_unnotified_jobs(tmp_db_path, min_score=0.0)
    assert len(all_jobs) == 2
    
    # Mark one as notified
    mark_notified(tmp_db_path, [sample_job.url_hash])
    
    # Check again
    remaining = get_unnotified_jobs(tmp_db_path, min_score=0.0)
    assert len(remaining) == 1
    assert remaining[0]["url_hash"] == sample_job2.url_hash

def test_get_stats(tmp_db_path, sample_job, sample_job2):
    bulk_insert_jobs(tmp_db_path, [sample_job, sample_job2])
    mark_notified(tmp_db_path, [sample_job.url_hash])
    
    stats = get_stats(tmp_db_path)
    assert stats["total"] == 2
    assert stats["notified"] == 1
    assert stats["pending"] == 1
    assert stats["by_source"]["test_source"] == 2

def test_run_logging(tmp_db_path):
    run_id = log_run_start(tmp_db_path, "test_source")
    assert run_id > 0
    
    with get_connection(tmp_db_path) as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert row["status"] == "running"
        assert row["source"] == "test_source"
        
    log_run_end(tmp_db_path, run_id, jobs_found=10, jobs_new=5)
    
    with get_connection(tmp_db_path) as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert row["status"] == "success"
        assert row["jobs_found"] == 10
        assert row["jobs_new"] == 5
        assert row["finished_at"] is not None

def test_job_decisions(tmp_db_path):
    save_decision(
        db_path=tmp_db_path,
        url_hash="somehash123",
        title="DevOps Junior",
        company="StartupX",
        decision="interested",
        source="test",
        profile_name="mayte",
        score=0.8
    )
    
    decision = get_decision(tmp_db_path, "somehash123")
    assert decision is not None
    assert decision["decision"] == "interested"
    assert decision["profile_name"] == "mayte"
    
    user_decisions = get_user_decisions(tmp_db_path, profile_name="mayte")
    assert len(user_decisions) == 1
    
    none_decision = get_decision(tmp_db_path, "nonexistent")
    assert none_decision is None
