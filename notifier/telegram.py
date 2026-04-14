"""
ergane/notifier/telegram.py
Telegram bot for sending job notifications and interactive commands.
Uses python-telegram-bot library with flood wait handling.
"""
import asyncio
import atexit
import fcntl
import inspect
import logging
import os
import signal
import sys
import re
from pathlib import Path
from typing import List, Dict, Optional

from telegram import Bot, Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import RetryAfter

from db.storage import mark_notified
from db.models import Job
from scrapers.linkedin_single import LinkedInSingleScraper
from scrapers.linkedin_post_scraper import LinkedInPostScraper, is_linkedin_post_url
from bs4 import BeautifulSoup
from filters.cv_matcher import match_cv
from filters.cv_generator import generate_cv, generate_cv_word
from filters.rules import detect_ambiguity
from profiles import load_all_profiles, match_job_to_profile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton single-instance enforcement — OS-level fcntl.flock
# The kernel auto-releases the lock if the process dies (even SIGKILL)
# ---------------------------------------------------------------------------

_LOCK_HANDLE = None
_BOT_APP = None  # global reference for graceful shutdown


def _acquire_singleton_lock() -> None:
    """
    Prevent multiple local Ergane polling instances for the same token.

    Uses fcntl.flock (advisory lock at kernel level).
    The lock is automatically released by the OS if the process is killed
    (SIGKILL, segfault, OOM killer, etc.).

    If the lock is already held, reads the PID from the lock file and
    reports it to the user before exiting.

    If the PID is dead (stale lock from crash), removes the stale lock
    and retries.
    """
    global _LOCK_HANDLE

    if _LOCK_HANDLE is not None:
        return

    lock_path = Path(
        os.getenv("ERGANE_TELEGRAM_LOCK_FILE", str(Path.home() / ".ergane" / "telegram_bot.lock"))
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing PID BEFORE opening (opening with "w" truncates!)
    old_pid_str = ""
    if lock_path.exists():
        try:
            old_pid_str = lock_path.read_text(encoding="utf-8").strip()
        except Exception:
            old_pid_str = ""

    handle = lock_path.open("w", encoding="utf-8")

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        # Lock is held by another process — check if it's still alive
        handle.close()

        if old_pid_str.isdigit():
            old_pid = int(old_pid_str)
            try:
                os.kill(old_pid, 0)  # signal 0 = check if alive
                logger.error(
                    "Ergane Telegram bot is already running (PID %d).\n"
                    "Stop it first:  kill %d\n"
                    "Force kill:      kill -9 %d",
                    old_pid, old_pid, old_pid,
                )
                sys.exit(1)
            except OSError:
                # Process is dead — stale lock, remove and retry
                lock_path.unlink(missing_ok=True)
                logger.warning("Stale lock file (PID %d is dead). Retrying...", old_pid)
                _acquire_singleton_lock()
                return
        else:
            logger.error(
                "Ergane Telegram bot is already running.\n"
                "Stop the other instance before starting a new one."
            )
            sys.exit(1)

    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    _LOCK_HANDLE = handle

    logger.info("Singleton lock acquired (PID %d, lock: %s)", os.getpid(), lock_path)


def _release_singleton_lock() -> None:
    """Release polling singleton lock."""
    global _LOCK_HANDLE

    if _LOCK_HANDLE is None:
        return

    lock_path = Path(
        os.getenv("ERGANE_TELEGRAM_LOCK_FILE", str(Path.home() / ".ergane" / "telegram_bot.lock"))
    )

    try:
        fcntl.flock(_LOCK_HANDLE.fileno(), fcntl.LOCK_UN)
        _LOCK_HANDLE.close()
        lock_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.debug("Failed to release lock: %s", exc)
    finally:
        _LOCK_HANDLE = None
        logger.info("Singleton lock released")


# ---------------------------------------------------------------------------
# Graceful shutdown via SIGTERM / SIGINT
# ---------------------------------------------------------------------------

def _register_signal_handlers() -> None:
    """Register signal handlers for graceful bot shutdown."""

    def _shutdown_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info("Received %s — shutting down gracefully...", sig_name)
        _graceful_shutdown()

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

    logger.debug("Signal handlers registered for SIGTERM, SIGINT")


def _graceful_shutdown() -> None:
    """Stop the Telegram bot, release lock, and exit cleanly."""
    global _BOT_APP

    if _BOT_APP is not None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_BOT_APP.stop())
            loop.close()
            logger.info("Telegram bot stopped")
        except Exception as exc:
            logger.warning("Error during bot stop: %s", exc)

    _release_singleton_lock()

    logger.info("Graceful shutdown complete")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Async Playwright-based job scraper (JS-rendered content support)
# ---------------------------------------------------------------------------

async def _scrape_job_async(job_url: str) -> Optional[Job]:
    """Scrape a job page using async Playwright — renders JavaScript content."""
    from playwright.async_api import async_playwright
    from urllib.parse import urlparse

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
            )
            page = await context.new_page()

            # Navigate and wait for network to be mostly idle
            await page.goto(job_url, wait_until="networkidle", timeout=30000)

            # Extra wait for lazy-loaded content (Workday, LinkedIn, etc.)
            await page.wait_for_timeout(2000)

            # Get the rendered HTML
            html = await page.content()
            text_content = await page.inner_text("body")

            await browser.close()

        # Parse with BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # Extract title
        title = None
        for sel in ["h1", "title"]:
            el = soup.find(sel)
            if el and el.get_text(strip=True):
                title = el.get_text(strip=True)[:200]
                break

        # Extract description from main content areas
        description = None
        for sel in [
            {"attrs": {"data-automation-id": "jobDescription"}},
            {"name": "article"},
            {"name": "main"},
            {"attrs": {"role": "main"}},
            {"name": "section"},
        ]:
            el = soup.find(**sel)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    description = text[:5000]
                    break
        if not description:
            description = text_content[:5000] if text_content else None

        # Extract company
        company = None
        og_site = soup.find("meta", property="og:site_name")
        if og_site and og_site.get("content"):
            company = og_site["content"].strip()
        if not company:
            domain = urlparse(job_url).netloc
            parts = domain.split(".")
            company = parts[0].capitalize() if parts[0] not in ("www", "wd12") else None

        # Extract location
        location = None
        loc_el = soup.find(attrs={"data-automation-id": "jobLocation"})
        if loc_el:
            location = loc_el.get_text(strip=True)

        # Detect remote
        text_blob = f"{title or ''} {location or ''} {description or ''}".lower()
        remote = any(kw in text_blob for kw in [
            "remote", "remoto", "home office", "teletrabajo", "hybrid", "híbrido",
        ])

        # Extract tech tags
        tags = []
        if description:
            tags = list(set(re.findall(
                r'\b(AWS|Azure|GCP|Python|Java|Kubernetes|Docker|Terraform|'
                r'PostgreSQL|MySQL|MongoDB|Redis|Git|DevOps|FastAPI|Django|'
                r'Node\.?js|React|TypeScript|Go|Rust|Kafka|Linux|Jenkins|'
                r'LangChain|Machine Learning|CI/CD|SQL|NoSQL|Spark|Hadoop)\b',
                description, re.IGNORECASE,
            )))[:15]

        if not title:
            return None

        return Job(
            url=job_url,
            title=title,
            source="generic",
            company=company,
            location=location,
            description=description,
            tags=tags,
            remote=remote,
        )

    except Exception as e:
        logger.error("async playwright scrape failed for %s: %s", job_url, e)
        return None


# ---------------------------------------------------------------------------
# Configuration from .env
# ---------------------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Max retries for flood wait
MAX_FLOOD_RETRIES = 3

# Characters that need escaping in MarkdownV2
_MD_ESCAPE_RE = re.compile(r'([_*\[\]()~`>#+\-=|{}.!\\])')


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    if not text:
        return ""
    return _MD_ESCAPE_RE.sub(r'\\\1', str(text))


# ---------------------------------------------------------------------------
# Main functions
# ---------------------------------------------------------------------------

def send_jobs_notification(jobs: List[Dict], db_path: str) -> bool:
    """
    Send job notifications to Telegram.

    Args:
        jobs: List of job dicts from get_unnotified_jobs()
        db_path: Path to SQLite database

    Returns:
        True if all sent successfully, False otherwise
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram credentials not configured in .env")
        return False

    if not jobs:
        logger.debug("No jobs to notify")
        return True

    # Sort: high priority (>=0.8) first, then by score DESC
    sorted_jobs = sorted(
        jobs,
        key=lambda x: (x.get("score", 0) >= 0.8, x.get("score", 0)),
        reverse=True,
    )

    logger.info("Sending %d job notifications to Telegram", len(sorted_jobs))

    notified_ids = []

    async def _send_all():
        """Send all messages in a single async context."""
        for job in sorted_jobs:
            message = _format_job_message(job)
            try:
                await _send_with_flood_handling_async(message)
                notified_ids.append(job["id"])
                logger.debug("Sent job: %s @ %s", job["title"], job.get("company", "Unknown"))
            except Exception as e:
                logger.error("Failed to send job %s: %s", job["title"], e)

    try:
        asyncio.run(_send_all())
    except Exception as e:
        logger.error("Error in send_jobs_notification: %s", e)

    # Mark notified jobs in DB
    if notified_ids:
        try:
            mark_notified(db_path, notified_ids)
            logger.info("Marked %d jobs as notified", len(notified_ids))
        except Exception as e:
            logger.error("Failed to mark jobs as notified: %s", e)

    return len(notified_ids) == len(sorted_jobs)


def send_reminder_notifications(db_path: str, chat_id: str = None) -> int:
    """
    Re-notify about high-score jobs that haven't been applied to in 3+ days.
    Only sends ONE reminder per job (reminded=0 -> reminded=1).

    Returns:
        Number of reminders sent
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Telegram bot token not configured")
        return 0

    try:
        with get_connection(db_path) as conn:
            cursor = conn.execute(
                """
                SELECT url_hash, title, company, score, scraped_at
                FROM jobs
                WHERE score >= 0.7
                  AND notified = 1
                  AND applied = 0
                  AND reminded = 0
                  AND julianday('now') - julianday(scraped_at) >= 3
                ORDER BY score DESC
                LIMIT 10
                """,
            )
            rows = cursor.fetchall()

        if not rows:
            return 0

        logger.info("Sending %d reminder notifications", len(rows))
        reminded_ids = []

        async def _send_reminders():
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            target_chat = chat_id or TELEGRAM_CHAT_ID
            for url_hash, title, company, score, _ in rows:
                score_str = f"{score:.2f}".replace(".", "\\.")
                title_esc = _escape_md(title)
                company_esc = _escape_md(company or "Unknown")

                message = (
                    f"⏰ _Recordatorio:_\n\n"
                    f"🔥 *{title_esc}*\n"
                    f"🏢 {company_esc}\n"
                    f"⭐ Score: {score_str}\n\n"
                    f"⚡ _Still pending — consider applying today_"
                )

                try:
                    await _send_to_chat_async(bot, target_chat, message)
                    reminded_ids.append(url_hash)
                except Exception as e:
                    logger.error("Failed to send reminder for %s: %s", title, e)

        asyncio.run(_send_reminders())

        # Mark as reminded
        if reminded_ids:
            with get_connection(db_path) as conn:
                conn.executemany(
                    "UPDATE jobs SET reminded = 1 WHERE url_hash = ?",
                    [(hid,) for hid in reminded_ids],
                )
            logger.info("Marked %d jobs as reminded", len(reminded_ids))

        return len(reminded_ids)

    except Exception as e:
        logger.exception("Error in reminder notifications: %s", e)
        return 0


def send_jobs_to_chat(jobs: List[Dict], chat_id: str, db_path: str = None) -> bool:
    """
    Send job notifications to a specific Telegram chat.
    Multi-user version of send_jobs_notification.

    Args:
        jobs: List of job dicts
        chat_id: Telegram chat ID to send to
        db_path: Path to SQLite database (optional, for marking notified)

    Returns:
        True if all sent successfully, False otherwise
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Telegram bot token not configured in .env")
        return False

    if not chat_id:
        logger.error("No chat_id provided for send_jobs_to_chat")
        return False

    if not jobs:
        logger.debug("No jobs to notify")
        return True

    # Sort by score DESC
    sorted_jobs = sorted(jobs, key=lambda x: x.get("score", 0), reverse=True)

    logger.info("Sending %d job notifications to chat %s", len(sorted_jobs), chat_id[-4:])

    notified_ids = []

    async def _send_all():
        """Send all messages in a single async context."""
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        for job in sorted_jobs:
            message = _format_job_message(job)
            try:
                await _send_to_chat_async(bot, chat_id, message)
                notified_ids.append(job["id"])
                logger.debug("Sent job to %s: %s", chat_id[-4:], job["title"])
            except Exception as e:
                logger.error("Failed to send job %s to %s: %s", job["title"], chat_id[-4:], e)

    try:
        asyncio.run(_send_all())
    except Exception as e:
        logger.error("Error in send_jobs_to_chat: %s", e)

    # Mark notified jobs in DB (if db_path provided)
    if notified_ids and db_path:
        try:
            mark_notified(db_path, notified_ids)
            logger.info("Marked %d jobs as notified", len(notified_ids))
        except Exception as e:
            logger.error("Failed to mark jobs as notified: %s", e)

    return len(notified_ids) == len(sorted_jobs)


async def _send_to_chat_async(bot: Bot, chat_id: str, message: str, retry_count: int = 0) -> None:
    """
    Send message to a specific chat with flood handling.
    """
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )

    except RetryAfter as e:
        if retry_count >= MAX_FLOOD_RETRIES:
            logger.error("Max flood retries exceeded for chat %s", chat_id[-4:])
            raise

        retry_after = e.retry_after
        logger.warning("Flood wait for %s: sleeping %d seconds", chat_id[-4:], retry_after)
        await asyncio.sleep(retry_after)
        await _send_to_chat_async(bot, chat_id, message, retry_count + 1)

    except Exception as e:
        logger.error("Telegram send error to %s: %s", chat_id[-4:], e)
        raise


def _format_job_message(job: Dict) -> str:
    """
    Format a single job as MarkdownV2 message.
    All special chars are escaped.
    High-priority jobs (score >= 0.8) get 🔥 prefix and "apply today" line.
    """
    title = _escape_md(job.get("title", "No title"))
    company = _escape_md(job.get("company", "Unknown"))
    location = _escape_md(job.get("location", "Not specified"))
    score = job.get("score", 0.0)
    tags = job.get("tags", [])
    url = job.get("url", "")
    salary = _escape_md(job.get("salary_raw"))
    is_high_priority = score >= 0.8

    # Build message — MarkdownV2 requires escaping everything
    # Score needs escaping because decimal point is a reserved char
    score_str = f"{score:.2f}".replace(".", "\\.")

    # High-priority prefix
    prefix = "🔥 " if is_high_priority else ""

    lines = [
        f"{prefix}🔹 *{title}*",
        f"🏢 {company}",
        f"📍 {location}",
        f"⭐ Score: {score_str}",
    ]

    if is_high_priority:
        lines.insert(4, "⚡ _Alta prioridad — aplicar hoy_")

    if salary:
        lines.append(f"💰 {salary}")

    if tags:
        tags_str = _escape_md(", ".join(tags[:5]))
        lines.append(f"🏷️ {tags_str}")

    # For URLs in markdown links: don't escape the URL itself (only the link text)
    # URLs inside (...) should NOT be escaped
    escaped_title = _escape_md(job.get("title", "Apply"))
    lines.append(f"🔗 [{escaped_title}]({url})")

    return "\n".join(lines)


async def _send_with_flood_handling_async(message: str, retry_count: int = 0) -> None:
    """
    Send message with flood wait handling (async version).

    Raises:
        RetryAfter: If max retries exceeded
    """
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )

    except RetryAfter as e:
        # Telegram rate limiting - wait and retry
        if retry_count >= MAX_FLOOD_RETRIES:
            logger.error("Max flood retries exceeded")
            raise

        retry_after = e.retry_after
        logger.warning("Flood wait: sleeping %d seconds (retry %d/%d)",
                      retry_after, retry_count + 1, MAX_FLOOD_RETRIES)
        await asyncio.sleep(retry_after)

        await _send_with_flood_handling_async(message, retry_count + 1)

    except Exception as e:
        logger.error("Telegram send error: %s", e)
        raise


# ---------------------------------------------------------------------------
# Interactive Bot Commands
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    # Don't use parse_mode here - send plain text
    await update.message.reply_text(
        "👋 Welcome to Ergane - Job Search Assistant!\n\n"
        "Available commands:\n"
        "/review <job_url> - Analyze job match with CV\n"
        "/reviewtext <text> - Analyze job from pasted description\n"
        "/generate_cv <job_url> - Generate tailored CV + cover letter\n"
        "/generatecvtext <text> - Generate CV from pasted description\n"
        "/applied <job_id> - Mark a job as applied\n"
        "/pending - List high-score jobs not yet applied\n"
        "/stats - View application tracking stats\n"
        "/interview <job_url> - Generate interview questions\n"
        "/interested - Mark last reviewed job as worth applying\n"
        "/skip - Mark last reviewed job as not interested\n"
        "/decisions - Show recent job decisions\n"
        "/help - Show this help message\n\n"
        "Supported URL types:\n"
        "• LinkedIn Jobs: linkedin.com/jobs/view/...\n"
        "• LinkedIn Posts: linkedin.com/posts/...\n"
        "• Workday: *.myworkdayjobs.com (Rappi, Bimbo, etc.)\n"
        "• Any job page: getonbrd.com, indeed.com, company careers, etc.\n\n"
        "Just send me any job URL and I'll review it for you!\n\n"
        "💡 Tip: Use /reviewtext or /generatecvtext when scraping fails!\n"
        "💡 Tip: CVs are generated as downloadable Word documents!\n"
        "💡 Tip: /interested and /skip let you override scores manually!"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    await cmd_start(update, context)


async def cmd_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /review command - analyze job URL and return match score.
    Supports both LinkedIn jobs URLs and LinkedIn post URLs.
    """
    if not context.args:
        await update.message.reply_text(
            "Usage: /review <job_url>\n\n"
            "Examples:\n"
            "• Jobs: https://www.linkedin.com/jobs/view/123456789\n"
            "• Posts: https://www.linkedin.com/posts/username_activity-123456"
        )
        return

    job_url = context.args[0]

    # Determine URL type and use appropriate scraper
    is_post = is_linkedin_post_url(job_url)
    is_jobs_url = "linkedin.com/jobs" in job_url
    is_linkedin = "linkedin.com" in job_url
    is_workday = "myworkdayjobs.com" in job_url

    if not is_post and not is_jobs_url and not is_linkedin and not is_workday:
        # Generic URL - will use generic scraper after LinkedIn checks
        pass

    # Send processing message
    processing_msg = await update.message.reply_text("🔄 Analyzing job... Please wait.")

    try:
        db_path = os.getenv("ERGANE_DB_PATH", "./ergane.db")

        # Use appropriate scraper based on URL type
        if is_post:
            scraper = LinkedInPostScraper(db_path=db_path)
            job = scraper.scrape_post_url(job_url)
            source_label = "📝 LinkedIn Post"
        elif is_jobs_url:
            scraper = LinkedInSingleScraper(db_path=db_path)
            job = scraper.scrape_job_url(job_url)
            source_label = "💼 LinkedIn Job"
        elif is_workday:
            job = await _scrape_job_async(job_url)
            source_label = "🏢 Workday Job"
        else:
            job = await _scrape_job_async(job_url)
            source_label = "🌐 External Job"

        if not job:
            if is_linkedin:
                await processing_msg.edit_text(
                    "❌ Failed to scrape the LinkedIn job/post. Please check the URL and try again."
                )
            else:
                await processing_msg.edit_text(
                    "❌ This page doesn't appear to be a job posting, or scraping failed.\n\n"
                    "Make sure the URL points to a job/vacancy page."
                )
            return

        # Calculate CV match
        score, matched_skills = match_cv(job)

        # Format response - adjust for post URLs
        source_label = "📝 LinkedIn Post" if is_post else "💼 LinkedIn Job"

        message = (
            f"📊 *Job Analysis Report*\n"
            f"{source_label}\n\n"
            f"🔹 *{job.title}*\n"
            f"🏢 {job.company or 'Unknown company'}\n"
            f"📍 {job.location or 'Location not specified'}\n\n"
            f"⭐ *CV Match Score: {score:.2f}*\n\n"
            f"✅ *Matched Skills ({len(matched_skills)}):*\n"
            f"  {', '.join(matched_skills[:10])}\n\n"
        )

        # Add application links if from post
        if is_post and job.description and "🔗 Application Links:" in job.description:
            # Extract links from description
            desc_lines = job.description.split("\n")
            links_section = False
            links = []
            for line in desc_lines:
                if "🔗 Application Links:" in line:
                    links_section = True
                    continue
                if links_section and line.startswith("• "):
                    link = line[2:].strip()
                    if link.startswith("http"):
                        links.append(link)

            if links:
                message += "🔗 *Application Links:*\n"
                for link in links[:3]:
                    # Truncate long URLs
                    display_link = link[:60] + "..." if len(link) > 60 else link
                    message += f"  • {display_link}\n"
                message += "\n"

        if score >= 0.5:
            message += "🎉 *Great match!* Consider applying."
        elif score >= 0.3:
            message += "⚠️ *Moderate match.* Review skill gaps before applying."
        else:
            message += "❌ *Low match.* This role may not align with your profile."

        await processing_msg.edit_text(message, parse_mode="Markdown")

    except Exception as e:
        logger.exception("Error in /review command: %s", e)
        await processing_msg.edit_text(
            f"❌ Error analyzing job: {str(e)}\n\n"
            "Please try again or contact support."
        )


async def cmd_reviewtext(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /reviewtext command - analyze job from pasted text.
    User pastes the job description directly as argument(s).
    """
    # Extract text after the command - preserve newlines and formatting
    full_text = update.message.text or ""
    cmd_prefix = "/reviewtext"
    
    if full_text.lower().startswith(cmd_prefix):
        # Everything after the command, preserve newlines
        job_text = full_text[len(cmd_prefix):].strip()
    elif context.args:
        # Arguments passed - join with space (not ideal but preserve something)
        job_text = " ".join(context.args)
    else:
        job_text = ""

    if not job_text or len(job_text) < 50:
        await update.message.reply_text(
            "❌ Text too short. Please paste the full job description.\n\n"
            "Include: job title, company, requirements, location, etc."
        )
        return

    # Parse job info from text using LinkedInPostScraper's parser
    db_path = os.getenv("ERGANE_DB_PATH", "./ergane.db")
    scraper = LinkedInPostScraper(db_path=db_path)
    job_info = scraper._parse_job_from_text(job_text)

    if not job_info.get("title"):
        await update.message.reply_text(
            "⚠️ Could not extract a job title from the text.\n\n"
            "Make sure the description includes:\n"
            "• Job title/role\n"
            "• Company name\n"
            "• Requirements/skills\n\n"
            "Try pasting the full job post."
        )
        return

    # Build Job object
    job = Job(
        url="manual:text",
        title=job_info.get("title", "Unknown"),
        source="manual_text",
        company=job_info.get("company"),
        location=job_info.get("location"),
        salary_min=job_info.get("salary_min"),
        salary_max=job_info.get("salary_max"),
        salary_raw=job_info.get("salary_raw"),
        description=job_text,
        tags=job_info.get("tags", []),
        remote=job_info.get("remote", False),
    )

    # Load profiles and score against each
    profiles = load_all_profiles()

    # Escape all user-generated text for MarkdownV2
    title_esc = _escape_md(job.title or "Unknown")
    company_esc = _escape_md(job.company or "Unknown company")
    location_esc = _escape_md(job.location or "Location not specified")

    if profiles:
        # Multi-profile mode: show scores for all profiles
        message = (
            f"📊 Job Analysis Report \\(from text\\)\n\n"
            f"🔹 *{title_esc}*\n"
            f"🏢 {company_esc}\n"
            f"📍 {location_esc}\n\n"
        )

        for profile in profiles:
            score, matched = match_job_to_profile(job, profile)
            score_str = f"{score:.2f}".replace(".", "\\.")
            skills_str = _escape_md(", ".join(m[:8] if isinstance(m, str) else str(m) for m in (matched[:8] if matched else [])))
            profile_name_esc = _escape_md(profile.name)
            message += f"👤 *{profile_name_esc}:* {score_str}\n"
            message += f"  ✅ {skills_str}\n\n"

        # Use the highest score for the verdict
        best_score = max(match_job_to_profile(job, p)[0] for p in profiles)
    else:
        # Fallback to legacy single-user CV matching
        score, matched_skills = match_cv(job)
        best_score = score
        score_str = f"{score:.2f}".replace(".", "\\.")
        message = (
            f"📊 Job Analysis Report \\(from text\\)\n\n"
            f"🔹 *{title_esc}*\n"
            f"🏢 {company_esc}\n"
            f"📍 {location_esc}\n\n"
            f"⭐ CV Match Score: {score_str}\n\n"
            f"✅ Matched Skills ({len(matched_skills)}):\n"
            f"  {_escape_md(', '.join(matched_skills[:10]))}\n\n"
        )

    # Detect ambiguity (culture/values-heavy postings)
    ambiguity = detect_ambiguity(job)
    if ambiguity["is_ambiguous"]:
        reason_esc = _escape_md(ambiguity["reason"])
        message += (
            f"🔍 Low\\-signal posting detected\n"
            f"_{reason_esc}_\n\n"
            f"⚠️ Score may underestimate fit\\. Culture\\-focused postings "
            f"often lack technical keywords but can still be worth applying to\\.\n\n"
        )

    # Verdict
    if best_score >= 0.5:
        message += "🎉 *Great match\\!* Consider applying\\."
    elif best_score >= 0.3:
        message += "⚠️ *Moderate match\\.* Review skill gaps before applying\\."
    elif ambiguity["is_ambiguous"]:
        message += "🔍 *Low score but worth investigating\\.* This posting is culture\\-focused and may not reflect the actual role\\."
    else:
        message += "❌ *Low match\\.* This role may not align with your profile\\."

    message += (
        "\n\n"
        "💡 *Manual override:*\n"
        "Reply to this message with:\n"
        "• `/interested` \\— mark as worth applying\n"
        "• `/skip` \\— not interested"
    )

    # Store the job text in user_data for override commands
    context.user_data["last_reviewed_job"] = {
        "url_hash": job.url_hash,
        "title": job.title,
        "company": job.company,
        "source": job.source,
        "score": best_score,
        "description": job_text,
    }

    try:
        await update.message.reply_text(message, parse_mode="MarkdownV2")
    except Exception:
        logger.warning("MarkdownV2 failed in /reviewtext, falling back to plain text")
        plain = message.replace("\\.", ".").replace("\\-", "-").replace("\\!", "!").replace("\\(", "(").replace("\\)", ")").replace("\\—", "—")
        plain = re.sub(r'[_*`]', '', plain)
        await update.message.reply_text(plain)


async def cmd_interested(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /interested - mark last reviewed job as worth applying."""
    db_path = os.getenv("ERGANE_DB_PATH", "./ergane.db")
    job_data = context.user_data.get("last_reviewed_job")

    if not job_data:
        await update.message.reply_text(
            "⚠️ No recent job to mark\\. Use `/reviewtext` or `/review` first\\.",
            parse_mode="MarkdownV2",
        )
        return

    from db.storage import save_decision

    save_decision(
        db_path=db_path,
        url_hash=job_data["url_hash"],
        title=job_data["title"],
        company=job_data["company"],
        source=job_data["source"],
        decision="interested",
        score=job_data["score"],
    )

    title_esc = _escape_md(job_data["title"])
    await update.message.reply_text(
        f"✅ Marked *{title_esc}* as *interested*\\!\n\n"
        f"The job has been saved to your tracking database\\. "
        f"You can review it later when applying\\.",
        parse_mode="MarkdownV2",
    )
    # Clear from user_data
    context.user_data.pop("last_reviewed_job", None)


async def cmd_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /skip - mark last reviewed job as not interested."""
    db_path = os.getenv("ERGANE_DB_PATH", "./ergane.db")
    job_data = context.user_data.get("last_reviewed_job")

    if not job_data:
        await update.message.reply_text(
            "⚠️ No recent job to skip\\. Use `/reviewtext` or `/review` first\\.",
            parse_mode="MarkdownV2",
        )
        return

    from db.storage import save_decision

    save_decision(
        db_path=db_path,
        url_hash=job_data["url_hash"],
        title=job_data["title"],
        company=job_data["company"],
        source=job_data["source"],
        decision="skipped",
        score=job_data["score"],
    )

    title_esc = _escape_md(job_data["title"])
    await update.message.reply_text(
        f"⏭️ Skipped *{title_esc}*\\.\n\n"
        f"Noted\\. I won't suggest this one again\\.",
        parse_mode="MarkdownV2",
    )
    context.user_data.pop("last_reviewed_job", None)


async def cmd_decisions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /decisions - show recent manual job decisions."""
    db_path = os.getenv("ERGANE_DB_PATH", "./ergane.db")
    from db.storage import get_user_decisions

    decisions = get_user_decisions(db_path, limit=10)

    if not decisions:
        await update.message.reply_text(
            "📋 No decisions recorded yet\\.\n\n"
            "Use `/reviewtext` or `/review` followed by `/interested` or `/skip`\\.",
            parse_mode="MarkdownV2",
        )
        return

    message = "📋 Recent Job Decisions\n\n"
    for d in decisions:
        emoji = "✅" if d["decision"] == "interested" else "⏭️"
        company = d["company"] or "?"
        title_esc = _escape_md(d["title"])
        company_esc = _escape_md(company)
        message += f"{emoji} {title_esc} @ {company_esc} \\({d['score']:.2f}\\)\n"

    message += (
        f"\n_Total: {len(decisions)} decisions shown\\._"
    )

    await update.message.reply_text(message, parse_mode="MarkdownV2")


async def cmd_generatecvtext(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /generatecvtext command - generate CV from pasted job text.
    User pastes the job description directly as argument(s).
    """
    # Extract text after the command (supports multi-line pastes)
    full_text = update.message.text or ""
    cmd_prefix = "/generatecvtext"
    if full_text.lower().startswith(cmd_prefix):
        job_text = full_text[len(cmd_prefix):].strip()
    else:
        job_text = " ".join(context.args) if context.args else ""

    if not job_text or len(job_text) < 50:
        await update.message.reply_text(
            "❌ Text too short. Please paste the full job description."
        )
        return

    scraper = LinkedInPostScraper(db_path=os.getenv("ERGANE_DB_PATH", "./ergane.db"))
    job_info = scraper._parse_job_from_text(job_text)

    if not job_info.get("title"):
        await update.message.reply_text(
            "⚠️ Could not extract a job title. Paste the full job post."
        )
        return

    job = Job(
        url="manual:text",
        title=job_info.get("title", "Unknown"),
        source="manual_text",
        company=job_info.get("company"),
        location=job_info.get("location"),
        salary_min=job_info.get("salary_min"),
        salary_max=job_info.get("salary_max"),
        salary_raw=job_info.get("salary_raw"),
        description=job_text,
        tags=job_info.get("tags", []),
        remote=job_info.get("remote", False),
    )

    if not os.getenv("ANTHROPIC_API_KEY"):
        await update.message.reply_text(
            "❌ Anthropic API key not configured."
        )
        return

    processing_msg = await update.message.reply_text(
        "🔄 Generating tailored CV and cover letter... This may take 30-60 seconds."
    )

    try:
        cv_text, cover_letter = generate_cv(job)

        if not cv_text:
            await processing_msg.edit_text("❌ Failed to generate CV.")
            return

        word_path = generate_cv_word(job)

        await update.message.reply_text(
            "📄 Your Tailored CV (from text)\n\n"
            f"Position: {job.title}\n"
            f"Company: {job.company or 'Unknown'}\n\n"
            "Sending Word document below..."
        )

        if word_path:
            await update.message.reply_document(
                document=open(word_path, "rb"),
                filename=os.path.basename(word_path),
                caption=f"CV tailored for: {job.title or 'position'}"
            )

        if cover_letter:
            await update.message.reply_text(cover_letter)

        await processing_msg.delete()

    except Exception as e:
        logger.exception("Error in /generatecvtext command: %s", e)
        await processing_msg.edit_text(f"❌ Error: {str(e)}")


async def cmd_generate_cv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /generate_cv command - generate tailored CV + cover letter.
    Supports both LinkedIn jobs URLs and LinkedIn post URLs.
    """
    if not context.args:
        await update.message.reply_text(
            "Usage: /generate_cv <job_url>\n\n"
            "Examples:\n"
            "• Jobs: https://www.linkedin.com/jobs/view/123456789\n"
            "• Posts: https://www.linkedin.com/posts/username_activity-123456"
        )
        return

    job_url = context.args[0]

    is_post = is_linkedin_post_url(job_url)
    is_jobs_url = "linkedin.com/jobs" in job_url
    is_linkedin = "linkedin.com" in job_url
    is_workday = "myworkdayjobs.com" in job_url

    # Send processing message
    processing_msg = await update.message.reply_text(
        "🔄 Generating tailored CV and cover letter... This may take 30-60 seconds."
    )

    try:
        db_path = os.getenv("ERGANE_DB_PATH", "./ergane.db")

        # Use appropriate scraper
        if is_post:
            scraper = LinkedInPostScraper(db_path=db_path)
            job = scraper.scrape_post_url(job_url)
        elif is_jobs_url:
            scraper = LinkedInSingleScraper(db_path=db_path)
            job = scraper.scrape_job_url(job_url)
        elif is_workday:
            job = await _scrape_job_async(job_url)
        else:
            job = await _scrape_job_async(job_url)

        if not job:
            if is_linkedin:
                await processing_msg.edit_text(
                    "❌ Failed to scrape the LinkedIn job/post. Please check the URL."
                )
            else:
                await processing_msg.edit_text(
                    "❌ This page doesn't appear to be a job posting, or scraping failed."
                )
            return

        # Check if Anthropic is configured
        if not os.getenv("ANTHROPIC_API_KEY"):
            await processing_msg.edit_text(
                "❌ Anthropic API key not configured. Please add ANTHROPIC_API_KEY to your .env file."
            )
            return

        # Generate CV and cover letter
        cv_text, cover_letter = generate_cv(job)

        if not cv_text:
            await processing_msg.edit_text(
                "❌ Failed to generate CV. Please try again."
            )
            return

        # Generate Word document
        word_path = generate_cv_word(job)

        # Send CV
        await update.message.reply_text(
            "📄 *Your Tailored CV*\n\n"
            f"Position: {job.title}\n"
            f"Company: {job.company or 'Unknown'}\n\n"
            "Sending CV as Word document and text below... 👇",
            parse_mode="Markdown"
        )

        # Send Word document if generated
        if word_path:
            await update.message.reply_document(
                document=open(word_path, "rb"),
                filename=f"{job.company or 'CV'}_Tailored.docx",
                caption="📎 CV in Word format (.docx)"
            )

        # Send as code blocks for easy copying
        await update.message.reply_text(
            f"```markdown\n{cv_text}\n```",
            parse_mode="Markdown"
        )

        if cover_letter:
            await update.message.reply_text(
                f"📝 *Cover Letter*\n\n"
                f"```markdown\n{cover_letter}\n```",
                parse_mode="Markdown"
            )

        await processing_msg.delete()

    except Exception as e:
        logger.exception("Error in /generate_cv command: %s", e)
        await processing_msg.edit_text(
            f"❌ Error generating CV: {str(e)}\n\n"
            "Please try again or contact support."
        )


async def handle_url_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle messages containing job URLs (auto-review).
    Supports LinkedIn jobs, LinkedIn posts, and any job page URL.
    """
    text = update.message.text.strip()

    # Extract URL from message (first URL found)
    url_match = re.search(r'https?://[^\s]+', text)
    if not url_match:
        return

    url = url_match.group(0)

    # Determine URL type
    is_post = is_linkedin_post_url(url)
    is_jobs_url = "linkedin.com/jobs" in url
    is_linkedin = "linkedin.com" in url

    # Auto-trigger review for any URL (LinkedIn or generic)
    context.args = [url]
    await cmd_review(update, context)


# ---------------------------------------------------------------------------
# Application tracking commands
# ---------------------------------------------------------------------------

async def cmd_applied(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /applied command - mark a job as applied.
    Usage: /applied <job_id> or /applied <url_hash>
    """
    if not context.args:
        await update.message.reply_text(
            "Usage: /applied <job_id>\n\n"
            "Example: /applied abc123def456"
        )
        return

    job_id = context.args[0]
    db_path = os.getenv("ERGANE_DB_PATH", "./ergane.db")
    now = datetime.now(timezone.utc).isoformat()

    try:
        with get_connection(db_path) as conn:
            cursor = conn.execute(
                "SELECT title, company FROM jobs WHERE url_hash = ?",
                (job_id,),
            )
            row = cursor.fetchone()

            if not row:
                await update.message.reply_text("❌ Job not found in database.")
                return

            title, company = row
            conn.execute(
                "UPDATE jobs SET applied = 1, applied_at = ? WHERE url_hash = ?",
                (now, job_id),
            )

        await update.message.reply_text(
            f"✅ Marcado como aplicado: {title} @ {company or 'Unknown'}"
        )

    except Exception as e:
        logger.exception("Error in /applied command: %s", e)
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /pending command - list high-score jobs not yet applied.
    """
    db_path = os.getenv("ERGANE_DB_PATH", "./ergane.db")

    try:
        with get_connection(db_path) as conn:
            cursor = conn.execute(
                """
                SELECT title, company, score, scraped_at, url_hash
                FROM jobs
                WHERE score >= 0.8 AND applied = 0
                ORDER BY score DESC, scraped_at DESC
                LIMIT 10
                """,
            )
            rows = cursor.fetchall()

        if not rows:
            await update.message.reply_text("✅ No pending high-priority jobs. All caught up!")
            return

        lines = ["🔥 *Pending high-priority jobs:*"]
        for title, company, score, scraped_at, _ in rows:
            score_str = f"{score:.2f}".replace(".", "\\.")
            # Calculate days ago
            try:
                scraped_dt = datetime.fromisoformat(scraped_at.replace("+00:00", ""))
                days_ago = (datetime.now(timezone.utc) - scraped_dt).days
            except Exception:
                days_ago = "?"

            company_esc = _escape_md(company or "Unknown")
            title_esc = _escape_md(title)
            lines.append(
                f"🔥 {score_str} | {title_esc} @ {company_esc} | {days_ago} días"
            )

        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")

    except Exception as e:
        logger.exception("Error in /pending command: %s", e)
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /stats command - show application tracking stats.
    """
    db_path = os.getenv("ERGANE_DB_PATH", "./ergane.db")

    try:
        with get_connection(db_path) as conn:
            # Total jobs
            cursor = conn.execute("SELECT COUNT(*) FROM jobs")
            total = cursor.fetchone()[0]

            # Notified
            cursor = conn.execute("SELECT COUNT(*) FROM jobs WHERE notified = 1")
            notified = cursor.fetchone()[0]

            # Applied
            cursor = conn.execute("SELECT COUNT(*) FROM jobs WHERE applied = 1")
            applied = cursor.fetchone()[0]

            # Pending high-score (>=0.8, not applied)
            cursor = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE score >= 0.8 AND applied = 0"
            )
            pending_high = cursor.fetchone()[0]

        score_str = f"{applied}/{notified}" if notified > 0 else "0"
        message = (
            f"📊 *Ergane Stats*\n\n"
            f"📋 Total jobs: {total}\n"
            f"📩 Notified: {notified}\n"
            f"📊 Seguimiento: {applied} aplicados, {pending_high} pendientes score>=0\\.8\n"
            f"✅ Aplicación rate: {score_str}"
        )

        await update.message.reply_text(message, parse_mode="MarkdownV2")

    except Exception as e:
        logger.exception("Error in /stats command: %s", e)
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_interview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /interview command - generate interview questions for a job.
    Supports both LinkedIn jobs URLs and LinkedIn post URLs.
    Usage: /interview <job_url>
    """
    if not context.args:
        await update.message.reply_text(
            "Usage: /interview <job_url>\n\n"
            "Examples:\n"
            "• Jobs: https://www.linkedin.com/jobs/view/123456789\n"
            "• Posts: https://www.linkedin.com/posts/username_activity-123456"
        )
        return

    job_url = context.args[0]
    db_path = os.getenv("ERGANE_DB_PATH", "./ergane.db")

    # Try to find job in DB by URL
    try:
        with get_connection(db_path) as conn:
            cursor = conn.execute(
                "SELECT title, company, description FROM jobs WHERE url = ?",
                (job_url,),
            )
            row = cursor.fetchone()

        if not row:
            await update.message.reply_text(
                "❌ Job not found in database. Try scraping it first."
            )
            return

        title, company, description = row

        if not os.getenv("ANTHROPIC_API_KEY"):
            await update.message.reply_text(
                "❌ Anthropic API key not configured. Add ANTHROPIC_API_KEY to .env."
            )
            return

        # Send processing message
        processing_msg = await update.message.reply_text(
            "🔄 Generating interview questions... Please wait."
        )

        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), timeout=30)

        prompt = (
            f"You are an expert technical interviewer. Based on this job description, "
            f"generate 5-7 likely interview questions with suggested answers.\n\n"
            f"Title: {title}\nCompany: {company or 'Unknown'}\n\n"
            f"Job Description:\n{description or 'Not available'}\n\n"
            f"Return format: Numbered list. Each question followed by '💡 Answer: ' with "
            f"a concise suggested answer. Focus on technical skills and behavioral questions."
        )

        response = client.messages.create(
            model="claude-sonnet-4-5-20250514",
            max_tokens=2048,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )

        interview_text = response.content[0].text.strip()

        # Escape for markdown
        escaped_text = _escape_md(interview_text)
        title_esc = _escape_md(title)
        company_esc = _escape_md(company or "Unknown")

        message = (
            f"🎤 *Interview Prep*\n\n"
            f"🔹 *{title_esc}*\n"
            f"🏢 {company_esc}\n\n"
            f"{escaped_text}"
        )

        await processing_msg.edit_text(message, parse_mode="MarkdownV2")

    except Exception as e:
        logger.exception("Error in /interview command: %s", e)
        await update.message.reply_text(f"❌ Error: {str(e)}")


# ---------------------------------------------------------------------------
# Bot Runner
# ---------------------------------------------------------------------------

def start_bot():
    """
    Start the Telegram bot with all handlers.
    This function runs in the MAIN thread due to asyncio signal requirements.

    Uses OS-level singleton lock (fcntl.flock) + signal handlers for
    graceful shutdown. Prevents 409 Conflict from zombie processes.
    """
    global _BOT_APP

    if not TELEGRAM_BOT_TOKEN:
        logger.error("Telegram bot token not configured")
        return None

    # Step 1: Acquire the singleton lock — exits if already running
    _acquire_singleton_lock()

    # Step 2: Register signal handlers for graceful shutdown
    _register_signal_handlers()

    logger.info("Starting Telegram bot...")

    # Create application with conflict resolution
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)  # Handle multiple updates concurrently
        .build()
    )

    # Store global reference for graceful shutdown
    _BOT_APP = application

    # Add handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("review", cmd_review))
    application.add_handler(CommandHandler("reviewtext", cmd_reviewtext))
    application.add_handler(CommandHandler("interested", cmd_interested))
    application.add_handler(CommandHandler("skip", cmd_skip))
    application.add_handler(CommandHandler("decisions", cmd_decisions))
    application.add_handler(CommandHandler("generate_cv", cmd_generate_cv))
    application.add_handler(CommandHandler("generatecvtext", cmd_generatecvtext))
    application.add_handler(CommandHandler("applied", cmd_applied))
    application.add_handler(CommandHandler("pending", cmd_pending))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("interview", cmd_interview))

    # Handle messages with URLs
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r'https?://[^\s]+'),
            handle_url_message
        )
    )

    # Start polling (blocks, must run in main thread)
    print("\n" + "=" * 50)
    print("🤖 Bot is ready! Send commands on Telegram.")
    print("   Commands: /start /help /review /generate_cv")
    print("=" * 50 + "\n")

    run_kwargs = {
        "allowed_updates": Update.ALL_TYPES,
        "drop_pending_updates": True,
        "close_loop": True,
    }

    if "error_callback" in inspect.signature(application.run_polling).parameters:
        from telegram.error import Conflict, TelegramError

        def _polling_error_callback(exc: TelegramError) -> None:
            if isinstance(exc, Conflict):
                logger.error(
                    "Telegram conflict detected (409). Another process is polling this bot token. "
                    "Verify only one Ergane instance runs for this token."
                )
                _graceful_shutdown()
                return
            logger.warning("Polling error: %s", exc)

        run_kwargs["error_callback"] = _polling_error_callback

    try:
        application.run_polling(**run_kwargs)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except SystemExit:
        # Signal handler triggered sys.exit — this is expected
        raise
    finally:
        _graceful_shutdown()

    return application


# ---------------------------------------------------------------------------
# Standalone test function
# ---------------------------------------------------------------------------

def send_test_message(message: str = "Ergane test notification ✅") -> bool:
    """
    Send a test message to verify Telegram configuration.

    Returns:
        True if sent successfully
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram credentials not configured")
        return False

    try:
        asyncio.run(_send_with_flood_handling_async(message))
        logger.info("Test message sent successfully")
        return True

    except Exception as e:
        logger.error("Test message failed: %s", e)
        return False
