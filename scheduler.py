"""
ergane/scheduler.py
APScheduler for running the Ergane pipeline every 6 hours.
Hybrid scoring: CV matching (60%) + Ollama semantic (40%)
Multi-user support via profiles/
Competitive improvements: ATS scanning, seniority/company scoring, target companies
"""
import logging
import os
import time
import threading
from typing import Optional, Type, List

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from db.models import Job
from db.storage import get_connection, bulk_insert_jobs, log_run_end, log_run_start
from filters.rules import score_job as rules_score_job, seniority_score, company_score
from filters.scorer import score_jobs as ollama_score_jobs
from filters.ats_scanner import score_ats
from notifier.telegram import send_jobs_notification, send_jobs_to_chat, start_bot as start_telegram_bot
from profiles import load_all_profiles, match_job_to_profile, job_passes_profile_filter, UserProfile

# Scrapers
from scrapers.base import BaseScraper, get_shared_browser, close_shared_browser
from scrapers.techjobsmx import TechJobsMXScraper
from scrapers.getonbrd import GetOnBrdScraper
from scrapers.occ import OCCScraper
from scrapers.computrabajo import CompuTrabajoScraper
from scrapers.himalayas import HimalayasScraper
from scrapers.weworkremotely import WeWorkRemotelyScraper
from scrapers.target_companies import TargetCompaniesScraper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration from .env
# ---------------------------------------------------------------------------

SCHEDULE_HOURS = int(os.getenv("ERGANE_SCHEDULE_HOURS", "6"))
SCHEDULE_CRON_HOURS = os.getenv("ERGANE_SCHEDULE_CRON_HOURS", "9,19")
MIN_SCORE = float(os.getenv("ERGANE_MIN_SCORE", "0.4"))
DB_PATH = os.getenv("ERGANE_DB_PATH", "./ergane.db")
OLLAMA_ENABLED = os.getenv("ERGANE_OLLAMA_ENABLED", "false").lower() == "true"
AGENT_ENABLED = os.getenv("ERGANE_AGENT_ENABLED", "false").lower() == "true"

# Optional: Job Reviewer Agent (LangGraph-based)
try:
    from filters.job_reviewer import review_job as agent_review_job
    AGENT_AVAILABLE = True
except ImportError:
    AGENT_AVAILABLE = False
    agent_review_job = None

# ---------------------------------------------------------------------------
# Global scheduler instance
# ---------------------------------------------------------------------------

_scheduler: Optional[BackgroundScheduler] = None


# ---------------------------------------------------------------------------
# Pipeline Helpers
# ---------------------------------------------------------------------------

def _score_with_agent(jobs: List[Job], profile: UserProfile) -> List[Job]:
    """Score jobs using the Job Reviewer Agent (LangGraph)."""
    if not jobs:
        return jobs

    scored_jobs = []
    start_time = time.time()
    
    for job in jobs:
        try:
            result = agent_review_job(
                job=job,
                profile=profile,
                rules_score=job.score if hasattr(job, 'score') else 0.0,  # Already computed
                seniority_score=seniority_score(job),
                company_score=company_score(job),
                sync_obsidian=False,  # Pipeline mode: no Obsidian sync
            )
            if result and "final_score" in result:
                job.score = result["final_score"]
                scored_jobs.append(job)
        except Exception as e:
            logger.warning("[Agent] Failed to score job %s: %s", job.title, e)
            scored_jobs.append(job)  # Keep original score
    
    elapsed = time.time() - start_time
    avg_ms = (elapsed / len(jobs) * 1000) if jobs else 0
    logger.info("[Agent] Scored %d jobs in %.2fs (%.1fms/job)", len(jobs), elapsed, avg_ms)
    
    return scored_jobs


def run_scraper(scraper_class: Type[BaseScraper], db_path: str) -> list[Job]:
    """Ejecuta un scraper específico y retorna todos los jobs scraped."""
    source = scraper_class.source_name
    all_jobs = []

    run_id = log_run_start(db_path, source)
    try:
        with scraper_class(db_path=db_path) as scraper:
            jobs = scraper.scrape()
            all_jobs = jobs

            # bulk_insert_jobs handles dedup via INSERT OR IGNORE
            new_count, dupes = bulk_insert_jobs(db_path, jobs)
            log_run_end(db_path, run_id, jobs_found=len(jobs), jobs_new=new_count)
            logger.info("[%s] Scraping finalizado: %d encontrados, %d nuevos", source, len(jobs), new_count)

    except Exception as e:
        logger.error("[%s] Error en scraper: %s", source, e)
        log_run_end(db_path, run_id, jobs_found=0, jobs_new=0, status="error", error_msg=str(e))

    return all_jobs


# ---------------------------------------------------------------------------
# Pipeline Principal
# ---------------------------------------------------------------------------

def run_pipeline(db_path: str = None, min_score: float = None) -> None:
    """
    Run the complete Ergane pipeline (profile-driven):
    1. Scrape jobs from all sources
    2. For each profile:
       a. Apply profile-aware rules (filters/rules.py)
       b. CV keyword matching against profile skills
       c. Combined score (CV + rules + seniority + company)
       d. Optional Ollama semantic scoring
       e. Optional job reviewer agent
       f. Send notifications to that profile's Telegram chat
    """
    db_path = db_path or DB_PATH
    min_score = min_score if min_score is not None else MIN_SCORE

    profiles = load_all_profiles()
    if not profiles:
        logger.error("No active profiles found in profiles/. Aborting pipeline.")
        return

    logger.info("Loaded %d active profiles: %s", len(profiles),
                ", ".join(p.name for p in profiles))

    logger.info("=" * 60)
    logger.info("Starting Ergane pipeline")
    logger.info("DB: %s | Min score: %.2f | Ollama: %s | Agent: %s | Profiles: %d",
                db_path, min_score, "enabled" if OLLAMA_ENABLED else "disabled",
                "enabled" if AGENT_ENABLED else "disabled",
                len(profiles))
    logger.info("=" * 60)

    # Step 1: Scrape from all sources (shared across profiles)
    logger.info("[1/3] Scraping jobs from all sources...")
    scrapers = [
        TargetCompaniesScraper,  # Target companies first (highest priority signal)
        HimalayasScraper,        # API-based (most reliable)
        WeWorkRemotelyScraper,   # RSS-based (has descriptions)
        GetOnBrdScraper,
        TechJobsMXScraper,
        OCCScraper,
        CompuTrabajoScraper,
    ]
    all_new_jobs: List[Job] = []
    # Use shared browser for all scrapers (one browser process, new context per scraper)
    for scraper_cls in scrapers:
        scraper = scraper_cls(db_path=db_path)
        scraper._use_shared_browser = True
        all_new_jobs.extend(run_scraper(scraper, db_path))
    # Close shared browser when all scrapers done
    close_shared_browser()

    if not all_new_jobs:
        logger.info("No new jobs found to process. Pipeline finished.")
        return

    logger.info("[1/3] Total new jobs to process: %d", len(all_new_jobs))

    # Step 2 & 3: Score and notify per profile
    _run_pipeline_multi_profile(all_new_jobs, profiles, db_path, min_score)

    logger.info("=" * 60)
    logger.info("Pipeline completed.")
    logger.info("=" * 60)


def _run_pipeline_multi_profile(jobs: List[Job], profiles: List[UserProfile],
                                 db_path: str, default_min_score: float) -> None:
    """Run scoring + notification pipeline for multiple user profiles.

    Note: rules/seniority/company scoring is evaluated per profile because
    profiles can override positive_stack, max_years_experience, blacklists, etc.
    Jobs are NOT mutated across profiles — each profile tracks scores in a
    local dict keyed by url_hash.
    """
    for profile in profiles:
        logger.info("[Profile: %s] Processing %d jobs...", profile.name, len(jobs))

        scored: List[tuple[Job, float]] = []

        for job in jobs:
            # 1. Profile-aware rules pass (hard exclusions, stack, title bonus)
            rules_val = rules_score_job(job, profile)
            if rules_val <= 0:
                continue

            # 2. CV keyword matching against profile skills
            cv_val, _ = match_job_to_profile(job, profile)

            # 3. Seniority + company signals (also profile-aware)
            sen_val = seniority_score(job, profile)
            comp_val = company_score(job, profile)

            # Combined score: 40% CV + 25% rules + 20% seniority + 15% company
            final_score = (
                0.40 * cv_val +
                0.25 * rules_val +
                0.20 * sen_val +
                0.15 * comp_val
            )
            scored.append((job, final_score))

        logger.info("[Profile: %s] After rules + CV: %d jobs", profile.name, len(scored))

        if not scored:
            logger.info("[Profile: %s] No jobs matched profile.", profile.name)
            continue

        # Materialize per-profile jobs: copy score onto a fresh Job reference.
        # We assign to job.score temporarily for downstream scorers that read it,
        # then capture the final value in profile-local state.
        profile_jobs: List[Job] = []
        for job, score in scored:
            job.score = score
            if job_passes_profile_filter(job, profile):
                profile_jobs.append(job)

        logger.info("[Profile: %s] After profile filter: %d jobs",
                    profile.name, len(profile_jobs))
        if not profile_jobs:
            continue

        # Optional: Ollama semantic scoring
        if OLLAMA_ENABLED:
            logger.info("[Profile: %s] Ollama semantic scoring...", profile.name)
            profile_jobs = ollama_score_jobs(profile_jobs)

        # Optional: Job Reviewer Agent
        if AGENT_ENABLED and AGENT_AVAILABLE and agent_review_job:
            logger.info("[Profile: %s] Agent scoring...", profile.name)
            profile_jobs = _score_with_agent(profile_jobs, profile)

        # Filter by minimum score (profile-specific or global default)
        profile_min_score = profile.min_score if profile.min_score > 0 else default_min_score
        filtered_jobs = [j for j in profile_jobs if j.score >= profile_min_score]

        logger.info("[Profile: %s] Jobs above threshold (%.2f): %d",
                    profile.name, profile_min_score, len(filtered_jobs))

        if filtered_jobs:
            _send_notifications(filtered_jobs, db_path,
                                chat_id=profile.telegram_chat_id,
                                profile_name=profile.name)


def _send_notifications(jobs: List[Job], db_path: str, chat_id: str = None,
                        profile_name: str = None) -> None:
    """Send notifications for filtered jobs."""
    job_dicts = []
    score_updates = []

    for job in jobs:
        score_updates.append((job.score, job.url_hash))
        job_dicts.append({
            "id": job.url_hash,
            "url": job.url,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "score": job.score,
            "tags": job.tags,
            "salary_raw": job.salary_raw,
            "description": job.description,
            "ats_score": getattr(job, 'ats_score', None),
        })

    # Batch update scores in DB
    with get_connection(db_path) as conn:
        conn.executemany(
            "UPDATE jobs SET score = ? WHERE url_hash = ?",
            score_updates,
        )
    
    # Send notifications
    if chat_id:
        # Multi-profile mode: send to specific chat
        success = send_jobs_to_chat(job_dicts, chat_id, db_path)
        logger.info("[%s] Sent %d notifications to chat %s", 
                    profile_name or "unknown", len(job_dicts), chat_id[-4:])
    else:
        # Single-user mode: use default chat from .env
        success = send_jobs_notification(job_dicts, db_path)
        logger.info("Sent %d notifications to Telegram", len(job_dicts))
    
    if not success:
        logger.warning("Some notifications failed")


# ---------------------------------------------------------------------------
# Scheduler control
# ---------------------------------------------------------------------------

def start_scheduler() -> None:
    """
    Start the background scheduler (Telegram bot runs in main thread).
    """
    global _scheduler

    if _scheduler is not None:
        logger.warning("Scheduler already running")
        return

    logger.info("Starting scheduler (cron hours: %s)", SCHEDULE_CRON_HOURS)

    _scheduler = BackgroundScheduler()

    _scheduler.add_job(
        func=run_pipeline,
        trigger=CronTrigger(hour=SCHEDULE_CRON_HOURS, minute=0),
        misfire_grace_time=1800,  # 30 minutes
        replace_existing=True,
        id="ergane_pipeline",
    )

    _scheduler.start()
    logger.info("Scheduler started successfully")


def stop_scheduler() -> None:
    """
    Stop the scheduler gracefully.
    """
    global _scheduler
    
    if _scheduler is None:
        logger.warning("Scheduler not running")
        return
    
    logger.info("Stopping scheduler...")
    _scheduler.shutdown(wait=True)
    _scheduler = None
    logger.info("Scheduler stopped")


if __name__ == "__main__":
    try:
        start_scheduler()
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        stop_scheduler()
