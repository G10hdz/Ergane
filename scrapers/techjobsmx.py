"""
ergane/scrapers/techjobsmx.py
Scraper para TechJobs in Mexico (https://techjobsinmexico.com)
SPA React — usa Playwright via BaseScraper.
"""
import logging
import re
from typing import Optional

from db.models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://techjobsinmexico.com"
JOBS_URL = f"{BASE_URL}/jobs"

# Patterns to skip when parsing inner_text lines
_DATE_RE = re.compile(r'^\+?\d+|^(today|yesterday|hace|hoy|ayer|\d+ (day|hour|minute|week))', re.I)
_SKIP_LINE = {"", "remote", "on-site", "hybrid"}


class TechJobsMXScraper(BaseScraper):
    """Playwright scraper for TechJobs in Mexico."""

    source_name = "techjobsmx"

    def __init__(self, db_path: str, headless: bool = True):
        super().__init__(db_path, headless=headless, rate_limit_min=1.0, rate_limit_max=3.0)

    def scrape(self) -> list[Job]:
        jobs = []
        page = self.page()

        try:
            logger.info("[%s] Navigating to %s", self.source_name, JOBS_URL)
            page.goto(JOBS_URL, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)

            # Each job card is an <a href="/jobs/title-uuid">
            cards = page.query_selector_all('a[href*="/jobs/"]')
            logger.info("[%s] Found %d job cards", self.source_name, len(cards))

            seen_urls = set()
            
            # FIRST: Extract all card data from listing page
            listing_data = []
            for card in cards:
                try:
                    href = card.get_attribute("href") or ""
                    if not href or href.rstrip("/") == "/jobs":
                        continue
                    job_url = href if href.startswith("http") else f"{BASE_URL}{href}"
                    if job_url in seen_urls:
                        continue
                    seen_urls.add(job_url)

                    # Extract data NOW before navigation
                    card_data = self._extract_card_data(card, job_url)
                    if card_data:
                        listing_data.append(card_data)
                except Exception as e:
                    logger.debug("[%s] Error extracting card data: %s", self.source_name, e)

            # SECOND: Visit detail pages for descriptions
            for card_data in listing_data:
                try:
                    description = self._fetch_description(page, card_data["url"])
                except Exception as e:
                    logger.debug("[%s] Failed to fetch description: %s", self.source_name, e)
                    description = None

                # Build Job object
                try:
                    job = Job(
                        url=card_data["url"],
                        title=card_data["title"],
                        source=self.source_name,
                        company=card_data.get("company"),
                        location=card_data.get("location"),
                        tags=card_data.get("tags", []),
                        remote=card_data.get("remote", False),
                        description=description,
                    )
                    jobs.append(job)
                except Exception as e:
                    logger.debug("[%s] Error building Job: %s", self.source_name, e)

        except Exception as e:
            logger.exception("[%s] Scraping error: %s", self.source_name, e)
            raise
        finally:
            page.close()

        logger.info("[%s] Done: %d jobs extracted", self.source_name, len(jobs))
        return jobs

    def _fetch_description(self, page, job_url: str) -> Optional[str]:
        """Visit detail page and extract description text."""
        page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2000)

        for selector in [".job-description", "[class*='description']", ".description", "article", "main"]:
            el = page.query_selector(selector)
            if el:
                text = el.inner_text().strip()
                if len(text) > 50:
                    return text

        body_text = page.inner_text("body")[:2000]
        return body_text if body_text else None

    def _extract_card_data(self, card, job_url: str) -> Optional[dict]:
        """Extract all data from a job card element (before navigation)."""
        # inner_text() structure (one item per line):
        #   title
        #   Company Name.
        #   Location
        #   X days ago        <- skip
        #   Full-time         <- tag
        #   Mid Level         <- tag
        #   Skill1            <- tag
        #   +N                <- skip
        lines = [l.strip() for l in card.inner_text().splitlines() if l.strip()]

        if len(lines) < 2:
            return None

        title = lines[0]
        company = lines[1].rstrip(".") if len(lines) > 1 else None
        location = lines[2] if len(lines) > 2 else None

        tags = []
        for line in lines[3:]:
            if _DATE_RE.match(line):
                continue
            if line.lower() in _SKIP_LINE:
                continue
            tags.append(line)

        remote = self._is_remote(title, location, tags)

        return {
            "url": job_url,
            "title": title,
            "company": company,
            "location": location,
            "tags": tags,
            "remote": remote,
        }

    def _parse_card(self, card, job_url: str, description: Optional[str]) -> Optional[Job]:
        """DEPRECATED - use _extract_card_data instead."""

    def _is_remote(self, title: str, location: Optional[str], tags: list[str]) -> bool:
        keywords = ["remote", "remoto", "work from home", "home office", "teletrabajo"]
        text = f"{title} {location or ''} {' '.join(tags)}".lower()
        return any(kw in text for kw in keywords)
