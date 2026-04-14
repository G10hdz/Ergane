"""
ergane/scrapers/target_companies.py
Scrapes jobs directly from target companies' career pages.
Detects ATS platform automatically (Greenhouse, Ashby, Workable).
"""
import logging
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from db.models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# ATS-specific selectors
ATS_SELECTORS = {
    "greenhouse": {
        "job_link": "a.opening__link",
        "job_title": ".opening__title",
        "job_list_container": ".openings",
        "fallback": "a[href*='boards.greenhouse.io']",
    },
    "ashby": {
        "job_link": "a.job",
        "job_title": ".job-title",
        "job_list_container": ".job-list",
        "fallback": "a[href*='jobs.ashbyhq.com']",
    },
    "workable": {
        "job_link": ".job-item a",
        "job_title": ".job-item__title",
        "job_list_container": ".jobs-list",
        "fallback": "a[href*='.workable.com']",
    },
}

# ATS URL patterns for auto-detection
ATS_URL_PATTERNS = {
    "greenhouse": ["boards.greenhouse.io", "greenhouse.io"],
    "ashby": ["jobs.ashbyhq.com", "ashby.com", "ashbyhq.com"],
    "workable": ["apply.workable.com", "workable.com"],
}


class TargetCompaniesScraper(BaseScraper):
    """
    Scraper for curated target companies.
    Reads companies from target_companies.yaml and scrapes their career pages.
    """

    source_name = "target_companies"

    def __init__(
        self,
        db_path: str,
        headless: bool = True,
        yaml_path: Optional[str] = None,
    ):
        super().__init__(db_path=db_path, headless=headless)
        self.yaml_path = yaml_path or os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "target_companies.yaml",
        )

    def load_companies(self) -> list[dict]:
        """Load companies from YAML file."""
        yaml_file = Path(self.yaml_path)
        if not yaml_file.exists():
            logger.warning("target_companies.yaml not found at %s", self.yaml_path)
            return []

        with open(yaml_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            return []

        companies = data.get("companies", [])
        logger.info("Loaded %d companies from target_companies.yaml", len(companies))
        return companies

    @staticmethod
    def detect_ats_platform(url: str, declared_platform: Optional[str] = None) -> str:
        """
        Detect ATS platform from URL patterns.
        Falls back to declared platform if URL doesn't match.
        """
        url_lower = url.lower()

        for platform, patterns in ATS_URL_PATTERNS.items():
            if any(p in url_lower for p in patterns):
                return platform

        return declared_platform or "unknown"

    def scrape_company(self, company: dict) -> list[Job]:
        """
        Scrape jobs from a single company's career page.

        Args:
            company: dict with name, careers_url, ats_platform, priority

        Returns:
            List of Job objects
        """
        name = company.get("name", "Unknown")
        url = company.get("careers_url", "")
        declared_platform = company.get("ats_platform")

        if not url:
            logger.warning("[%s] No careers_url, skipping", name)
            return []

        ats_platform = self.detect_ats_platform(url, declared_platform)
        logger.info("[%s] Scraping %s (ATS: %s)", self.source_name, name, ats_platform)

        selectors = ATS_SELECTORS.get(ats_platform, ATS_SELECTORS["greenhouse"])

        jobs = []
        try:
            page = self.page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)  # Let JS render

            # Try primary selectors first
            job_links = page.query_selector_all(selectors.get("job_link", "a"))

            # Fallback to generic links if primary fails
            if not job_links:
                job_links = page.query_selector_all(selectors.get("fallback", "a"))

            # Extract card data BEFORE navigating (handles get destroyed)
            card_data = []
            for link_el in job_links:
                href = link_el.get_attribute("href")
                title = (link_el.inner_text() or "").strip()
                if href and title and len(title) > 5:
                    card_data.append({"url": href, "title": title})

            logger.info("[%s] Found %d potential jobs on %s", self.source_name, len(card_data), name)

            # Now navigate to each job for details
            for card in card_data:
                job_url = card["url"]
                # Make URL absolute if relative
                if not job_url.startswith("http"):
                    from urllib.parse import urljoin
                    job_url = urljoin(url, job_url)

                # Try to get description
                try:
                    page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(2000)

                    # Try common description selectors
                    description = None
                    for selector in [
                        ".job-description", ".description", "#job-details",
                        ".job__description", ".opening__description",
                        ".job-details__description", "article",
                    ]:
                        el = page.query_selector(selector)
                        if el:
                            description = el.inner_text().strip()
                            if len(description) > 50:
                                break

                    # Fallback to page body
                    if not description or len(description) < 50:
                        body = page.query_selector("body")
                        if body:
                            description = body.inner_text().strip()[:2000]

                except Exception as e:
                    logger.debug("[%s] Failed to fetch job details for %s: %s", self.source_name, job_url, e)
                    description = ""

                job = Job(
                    url=job_url,
                    title=card["title"],
                    source=self.source_name,
                    company=name,
                    description=description or "",
                    remote="remote" in job_url.lower() or "remote" in card["title"].lower(),
                    scraped_at=datetime.now(timezone.utc).isoformat(),
                )
                jobs.append(job)

                # Rate limit between jobs
                self._random_sleep()

        except Exception as e:
            logger.error("[%s] Error scraping %s: %s", self.source_name, name, e)

        return jobs

    def scrape(self) -> list[Job]:
        """
        Scrape jobs from all target companies.
        """
        companies = self.load_companies()
        if not companies:
            logger.warning("No companies to scrape")
            return []

        # Sort by priority: high first
        priority_order = {"high": 0, "medium": 1, "low": 2}
        companies.sort(key=lambda c: priority_order.get(c.get("priority", "low"), 3))

        all_jobs = []
        for company in companies:
            jobs = self.scrape_company(company)
            all_jobs.extend(jobs)
            # Sleep between companies
            self._random_sleep()

        logger.info(
            "[%s] Total: %d jobs from %d companies",
            self.source_name, len(all_jobs), len(companies),
        )

        return all_jobs

    def __enter__(self) -> "TargetCompaniesScraper":
        """Override: only launch browser if not already running."""
        return super().__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Override: close browser."""
        return super().__exit__(exc_type, exc_val, exc_tb)
