"""
ergane/scrapers/linkedin_single.py
Scraper for single LinkedIn job URLs (for Telegram bot review feature).
Uses Scrapling StealthyFetcher for anti-detection.

Usage:
    scraper = LinkedInSingleScraper(db_path='ergane.db')
    job = scraper.scrape_job_url('https://www.linkedin.com/jobs/view/123456789')
"""
import logging
import re
from typing import Optional

from scrapling import StealthyFetcher

from db.models import Job

logger = logging.getLogger(__name__)


class LinkedInSingleScraper:
    """Scraper for individual LinkedIn job URLs."""

    source_name = "linkedin"

    def __init__(self, db_path: str, headless: bool = True):
        """
        Args:
            db_path: Path to SQLite database (kept for API compatibility)
            headless: Run browser in headless mode
        """
        self.db_path = db_path
        self.headless = headless
        self.fetcher = StealthyFetcher()

    def scrape_job_url(self, job_url: str) -> Optional[Job]:
        """
        Scrape a single LinkedIn job URL.

        Args:
            job_url: LinkedIn job URL (e.g., https://www.linkedin.com/jobs/view/123456789)

        Returns:
            Job object or None if scraping fails
        """
        try:
            logger.info("[%s] Fetching job: %s", self.source_name, job_url)

            # Fetch the job page
            page = self.fetcher.fetch(
                job_url,
                headless=self.headless,
                timeout=60,  # 60 seconds
                wait=3000,  # Wait 3 seconds after page load
                network_idle=True,
            )

            if not page:
                logger.warning("[%s] No content received from LinkedIn", self.source_name)
                return None

            # Extract job data
            job = self._parse_job_page(page, job_url)

            if job:
                logger.info("[%s] Successfully scraped: %s @ %s", 
                           self.source_name, job.title, job.company or "Unknown")
            else:
                logger.warning("[%s] Failed to parse job data", self.source_name)

            return job

        except Exception as e:
            logger.exception("[%s] Error scraping job: %s", self.source_name, e)
            return None

    def _parse_job_page(self, page, job_url: str) -> Optional[Job]:
        """
        Parse a LinkedIn job page into a Job object.
        """
        try:
            # Try multiple selectors for job title (LinkedIn changes these frequently)
            title_selectors = [
                'h1[class*="job-title"]',
                'h1.job-title',
                '[class*="job-title"] h1',
                'h2[class*="job-title"]',
            ]

            title = None
            for selector in title_selectors:
                title_el = page.css_first(selector)
                if title_el and title_el.text:
                    title = title_el.text.strip()
                    break

            if not title:
                # Fallback: try to find any h1/h2 with job-like text
                for tag in ['h1', 'h2']:
                    els = page.css(tag)
                    for el in els:
                        text = el.text.strip() if el.text else ""
                        if text and len(text) < 200:
                            title = text
                            break
                    if title:
                        break

            if not title:
                logger.warning("[%s] Could not find job title", self.source_name)
                return None

            # Company name
            company_selectors = [
                '[class*="company-name"]',
                '[class*="company"] a[href*="/company"]',
                'a[href*="/company"]',
                '[data-test-company-name]',
            ]

            company = None
            for selector in company_selectors:
                company_el = page.css_first(selector)
                if company_el and company_el.text:
                    company = company_el.text.strip()
                    break

            # Location
            location_selectors = [
                '[class*="location"]',
                '[data-test-location]',
                '[class*="workplace-type"]',
            ]

            location = None
            for selector in location_selectors:
                location_el = page.css_first(selector)
                if location_el and location_el.text:
                    location = location_el.text.strip()
                    break

            # Description
            description_selectors = [
                '[class*="job-description"]',
                '[data-test-job-description]',
                '#job-details',
                '[class*="show-more-less"]',
            ]

            description = None
            for selector in description_selectors:
                desc_el = page.css_first(selector)
                if desc_el:
                    # Get all text content from description
                    description = desc_el.text.strip() if desc_el.text else None
                    if description and len(description) > 100:
                        break

            # If description not found, try to get all paragraph text
            if not description:
                paragraphs = page.css('p')
                desc_parts = []
                for p in paragraphs[:20]:  # Limit to first 20 paragraphs
                    text = p.text.strip() if p.text else ""
                    if text and len(text) > 50:
                        desc_parts.append(text)
                if desc_parts:
                    description = "\n\n".join(desc_parts[:10])  # Limit to first 10 parts

            # Tags/skills
            tags = []
            tag_selectors = [
                '[class*="skill"]',
                '[class*="requirement"]',
                '.job-keyword',
                '[data-test-job-posting] li',
            ]

            for selector in tag_selectors:
                tag_els = page.css(selector)
                for tag_el in tag_els[:15]:  # Limit tags
                    tag_text = tag_el.text.strip() if tag_el.text else ""
                    if tag_text and 2 < len(tag_text) < 50:
                        tags.append(tag_text)

            # Check if remote
            remote = self._is_remote(title, location, tags, description)

            # Salary (LinkedIn rarely shows salary, but try anyway)
            salary_min, salary_max, salary_raw = self._extract_salary(page)

            return Job(
                url=job_url,
                title=title,
                source=self.source_name,
                company=company,
                location=location,
                salary_min=salary_min,
                salary_max=salary_max,
                salary_raw=salary_raw,
                description=description,
                tags=tags,
                remote=remote,
            )

        except Exception as e:
            logger.exception("[%s] Error parsing job page: %s", self.source_name, e)
            return None

    def _extract_salary(self, page) -> tuple[Optional[int], Optional[int], Optional[str]]:
        """Extract salary information if available."""
        try:
            salary_selectors = [
                '[class*="salary"]',
                '[data-test-salary]',
                '.salary-range',
                '[class*="compensation"]',
            ]

            for selector in salary_selectors:
                salary_el = page.css_first(selector)
                if salary_el and salary_el.text:
                    salary_raw = salary_el.text.strip()
                    if salary_raw:
                        salary_min, salary_max = self._parse_salary(salary_raw)
                        return salary_min, salary_max, salary_raw

            return None, None, None

        except Exception:
            return None, None, None

    def _parse_salary(self, salary_str: str) -> tuple[Optional[int], Optional[int]]:
        """Parse salary string to numeric values."""
        if not salary_str:
            return None, None

        # Extract numbers
        nums = re.findall(r'[\d,]+', salary_str.replace(",", ""))
        if not nums:
            return None, None

        vals = [int(n) for n in nums[:2]]
        if len(vals) == 1:
            return vals[0], vals[0]
        return vals[0], vals[1]

    def _is_remote(self, title: str, location: Optional[str], tags: list[str], 
                   description: Optional[str]) -> bool:
        """Determine if job is remote."""
        keywords = ["remote", "remoto", "work from home", "home office", "teletrabajo", 
                   "hybrid", "híbrido"]
        
        text = f"{title} {location or ''} {' '.join(tags)} {description or ''}".lower()
        return any(kw in text for kw in keywords)
