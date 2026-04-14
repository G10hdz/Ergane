"""
ergane/scrapers/himalayas.py
Scraper for Himalayas.app (https://himalayas.app) using their public API.
No browser needed - direct API access.
"""
import logging
import requests
from typing import Optional

from db.models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

API_URL = "https://himalayas.app/jobs/api/search"


class HimalayasScraper(BaseScraper):
    """API-based scraper for Himalayas remote jobs."""

    source_name = "himalayas"

    def __init__(self, db_path: str, headless: bool = True):
        """
        Args:
            db_path: Path to SQLite database
            headless: Ignored (API-based, no browser)
        """
        # Don't call super().__init__() — we don't need Playwright
        self.db_path = db_path
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self) -> "HimalayasScraper":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    def scrape(self) -> list[Job]:
        """Fetch jobs from Himalayas API."""
        jobs = []

        try:
            logger.info("[%s] Fetching from API: %s", self.source_name, API_URL)

            # Fetch remote jobs in Mexico - API doesn't filter well by keyword
            # so we'll filter with CV matching later in the pipeline
            params = {
                "country": "MX",
                "limit": 100,  # Fetch more jobs, CV matcher will filter
            }
            
            response = requests.get(API_URL, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            total = data.get("totalCount", 0)
            logger.info("[%s] API returned %d total jobs", self.source_name, total)
            
            for job_data in data.get("jobs", []):
                try:
                    job = self._parse_job(job_data)
                    if job:
                        jobs.append(job)
                except Exception as e:
                    logger.debug("[%s] Error parsing job: %s", self.source_name, e)
                    continue

        except Exception as e:
            logger.exception("[%s] Error during scraping: %s", self.source_name, e)

        logger.info("[%s] Scraping completed: %d jobs extracted", self.source_name, len(jobs))
        return jobs

    def _parse_job(self, job_data: dict) -> Optional[Job]:
        """Parse a job from Himalayas API response."""
        try:
            title = job_data.get("title", "")
            if not title:
                return None

            company = job_data.get("companyName", "")
            job_url = job_data.get("applicationLink", "")
            if not job_url:
                return None

            # Location restrictions
            location_restrictions = job_data.get("locationRestrictions", [])
            location = "Remote" if location_restrictions else None
            if "Mexico" in location_restrictions:
                location = "Remote (Mexico)"

            # Salary
            salary_min = job_data.get("minSalary")
            salary_max = job_data.get("maxSalary")
            currency = job_data.get("currency", "USD")

            # Convert USD to MXN if needed (approximate rate)
            if currency == "USD" and (salary_min or salary_max):
                if salary_min:
                    salary_min = int(salary_min * 20)  # Approximate USD to MXN
                if salary_max:
                    salary_max = int(salary_max * 20)

            # Categories/tags
            tags = job_data.get("categories", [])
            seniority = job_data.get("seniority", [])
            if seniority:
                tags.extend(seniority)

            # Employment type
            employment_type = job_data.get("employmentType", "")
            if employment_type:
                tags.append(employment_type)

            # Check if remote
            remote = "Remote" in (location or "") or bool(location_restrictions)

            # Extract description (HTML, but better than nothing)
            description = job_data.get("description", "")
            if description:
                # Strip HTML tags for cleaner text
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(description, "html.parser")
                description = soup.get_text(separator=" ", strip=True)

            return Job(
                url=job_url,
                title=title,
                source=self.source_name,
                company=company,
                location=location,
                salary_min=salary_min,
                salary_max=salary_max,
                salary_raw=f"{salary_min}-{salary_max} MXN" if salary_min else None,
                tags=tags,
                remote=remote,
                description=description if description else None,
            )

        except Exception as e:
            logger.debug("[%s] Error parsing job data: %s", self.source_name, e)
            return None
