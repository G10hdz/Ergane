"""
ergane/scrapers/weworkremotely.py
Scraper for We Work Remotely (https://weworkremotely.com) using RSS feeds.
No browser needed - RSS feed parsing.
"""
import logging
import feedparser
from typing import Optional
from datetime import datetime

from db.models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# RSS feed URLs for different categories (we'll use programming + devops)
RSS_FEEDS = [
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
]


class WeWorkRemotelyScraper(BaseScraper):
    """RSS-based scraper for We Work Remotely jobs."""

    source_name = "weworkremotely"

    def __init__(self, db_path: str, headless: bool = True):
        """
        Args:
            db_path: Path to SQLite database (kept for API compatibility)
            headless: Ignored (RSS-based, no browser)
        """
        # Don't call super().__init__() — we don't need Playwright
        self.db_path = db_path
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self) -> "WeWorkRemotelyScraper":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    def scrape(self) -> list[Job]:
        """Fetch jobs from We Work Remotely RSS feeds."""
        jobs = []
        seen_urls = set()

        for feed_url in RSS_FEEDS:
            try:
                logger.info("[%s] Fetching RSS: %s", self.source_name, feed_url)
                
                # Parse RSS feed
                feed = feedparser.parse(feed_url)
                
                if feed.bozo:
                    logger.warning("[%s] RSS feed parse error: %s", self.source_name, feed.bozo_exception)
                    continue
                
                logger.info("[%s] RSS feed returned %d entries", self.source_name, len(feed.entries))

                for entry in feed.entries:
                    try:
                        job = self._parse_entry(entry)
                        if job and job.url not in seen_urls:
                            seen_urls.add(job.url)
                            jobs.append(job)
                    except Exception as e:
                        logger.debug("[%s] Error parsing entry: %s", self.source_name, e)
                        continue

            except Exception as e:
                logger.exception("[%s] Error fetching RSS feed: %s", self.source_name, e)

        logger.info("[%s] Scraping completed: %d jobs extracted", self.source_name, len(jobs))
        return jobs

    def _parse_entry(self, entry) -> Optional[Job]:
        """Parse a job from RSS entry."""
        try:
            title = entry.get("title", "")
            if not title:
                return None

            # Extract company and role from title (format: "Company - Role")
            company = None
            role_title = title
            if " - " in title:
                parts = title.split(" - ", 1)
                if len(parts) == 2:
                    company = parts[0].strip()
                    role_title = parts[1].strip()

            job_url = entry.get("link", "")
            if not job_url:
                return None

            # Description (HTML, will be cleaned later if needed)
            description = entry.get("description", "")
            
            # Published date
            published_at = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published_at = datetime(*entry.published_parsed[:6]).isoformat()
                except Exception:
                    pass

            # Location (usually in summary or tags)
            location = "Remote"
            if hasattr(entry, "where") and entry.where:
                location = entry.where
            
            # Tags/categories
            tags = []
            if hasattr(entry, "tags"):
                for tag in entry.tags:
                    if hasattr(tag, "term"):
                        tags.append(tag.term)
            
            # Check if remote
            remote = "remote" in location.lower() or "anywhere" in location.lower()

            return Job(
                url=job_url,
                title=role_title,
                source=self.source_name,
                company=company,
                location=location,
                salary_min=None,
                salary_max=None,
                salary_raw=None,
                description=description,
                tags=tags,
                remote=remote,
                posted_at=published_at,
            )

        except Exception as e:
            logger.debug("[%s] Error parsing RSS entry: %s", self.source_name, e)
            return None
