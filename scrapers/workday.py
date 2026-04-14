"""
ergane/scrapers/workday.py
Scraper for Workday-powered job sites using Playwright.
Workday sites (wd12.myworkdayjobs.com) require JS rendering.

Usage:
    scraper = WorkdayScraper(db_path='ergane.db')
    job = scraper.scrape_job_url('https://rappi.wd12.myworkdayjobs.com/...')
"""
import logging
import re
from typing import Optional

from db.models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class WorkdayScraper(BaseScraper):
    """Playwright scraper for Workday job sites."""

    source_name = "workday"

    def __init__(self, db_path: str, headless: bool = True):
        super().__init__(db_path, headless=headless, rate_limit_min=2.0, rate_limit_max=4.0)

    def scrape(self) -> list[Job]:
        """Not used — WorkdayScraper is for single-URL scraping only."""
        return []

    def scrape_job_url(self, job_url: str) -> Optional[Job]:
        """
        Scrape a single Workday job URL.

        Args:
            job_url: Workday job URL (e.g., https://rappi.wd12.myworkdayjobs.com/...)

        Returns:
            Job object or None if scraping fails
        """
        page = self.page()
        try:
            logger.info("[%s] Fetching job: %s", self.source_name, job_url)

            page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(4000)

            job = self._parse_job_page(page, job_url)

            if job:
                logger.info(
                    "[%s] Successfully scraped: %s @ %s",
                    self.source_name, job.title, job.company or "Unknown"
                )
            else:
                logger.warning("[%s] Failed to parse job data", self.source_name)

            return job

        except Exception as e:
            logger.exception("[%s] Error scraping job: %s", self.source_name, e)
            return None

        finally:
            page.close()

    def _parse_job_page(self, page, job_url: str) -> Optional[Job]:
        """Parse Workday job page into a Job object."""
        try:
            title = self._extract_title(page)
            if not title:
                logger.warning("[%s] Could not find job title", self.source_name)
                return None

            company = self._extract_company(page, job_url)
            location = self._extract_location(page)
            description = self._extract_description(page)
            salary_raw = self._extract_salary(page)
            salary_min, salary_max = self._parse_salary(salary_raw)
            tags = self._extract_tags(page, description)
            remote = self._is_remote(title, location, description)

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

    def _extract_title(self, page) -> Optional[str]:
        """Extract job title from Workday page."""
        selectors = [
            'h1[data-automation-id="jobTitle"]',
            'h1[class*="jobTitle"]',
            '[data-automation-id="jobTitle"]',
            'h1',
            'h2[class*="title"]',
            '[class*="job-title"]',
        ]

        for selector in selectors:
            el = page.query_selector(selector)
            if el:
                text = el.inner_text().strip()
                if text and len(text) < 200:
                    return text

        return None

    def _extract_company(self, page, job_url: str) -> Optional[str]:
        """Extract company name from Workday page."""
        selectors = [
            'span[data-automation-id="companyName"]',
            '[data-automation-id="companyName"]',
            '[class*="company"]',
            '[class*="employer"]',
            'a[href*="/company"]',
        ]

        for selector in selectors:
            el = page.query_selector(selector)
            if el:
                text = el.inner_text().strip()
                if text and len(text) < 100:
                    return text

        try:
            from urllib.parse import urlparse
            parsed = urlparse(job_url)
            domain = parsed.netloc
            company = domain.split('.')[0]
            if company and company not in ['www', 'wd12']:
                return company.capitalize()
        except Exception:
            pass

        return None

    def _extract_location(self, page) -> Optional[str]:
        """Extract location from Workday page."""
        selectors = [
            'span[data-automation-id="jobLocation"]',
            '[data-automation-id="jobLocation"]',
            '[class*="location"]',
            '[class*="place"]',
        ]

        for selector in selectors:
            el = page.query_selector(selector)
            if el:
                text = el.inner_text().strip()
                if text and len(text) < 150:
                    return text

        return None

    def _extract_description(self, page) -> Optional[str]:
        """Extract job description from Workday page."""
        selectors = [
            '[data-automation-id="jobDescription"]',
            '[class*="description"]',
            '[class*="content"]',
            '[class*="details"]',
            'article',
            'section[class*="job"]',
        ]

        for selector in selectors:
            el = page.query_selector(selector)
            if el:
                text = el.inner_text().strip()
                if len(text) > 100:
                    return text

        body_text = page.inner_text("body")[:5000]
        return body_text if len(body_text) > 100 else None

    def _extract_salary(self, page) -> Optional[str]:
        """Extract salary information from Workday page."""
        selectors = [
            '[data-automation-id="compensation"]',
            '[class*="salary"]',
            '[class*="pay"]',
            '[class*="compensation"]',
        ]

        for selector in selectors:
            el = page.query_selector(selector)
            if el:
                text = el.inner_text().strip()
                if text:
                    return text

        return None

    def _extract_tags(self, page, description: Optional[str]) -> list[str]:
        """Extract skills/technologies from page."""
        tags = []

        skill_selectors = [
            '[data-automation-id="skills"]',
            '[class*="skill"]',
            '[class*="requirement"]',
        ]

        for selector in skill_selectors:
            els = page.query_selector_all(selector)
            for el in els[:15]:
                text = el.inner_text().strip()
                if text and 2 < len(text) < 50:
                    tags.append(text)

        if description:
            tech_keywords = re.findall(
                r'\b([Aa]WS?|[Mm]icrosoft [Aa]zure|[Gg]CP|[Pp]ython|[Jj]ava|'
                r'[Ss]park|[Hh]adoop|[Kk]ubernetes|[Dd]ocker|[Tt]erraform|'
                r'[Pp]ostgreSQL|[Mm]ySQL|[Mm]ongoDB|[Rr]edis|[Ee]lasticsearch|'
                r'[Gg]it|[Cc][Ii]/[Cc][Dd]|[Pp]ipeline|[Aa]nsible|[Pp]rometheus|'
                r'[Gg]rafana|[Ll]inux|[Jj]enkins|[Cc][Ii]|[Dd]ev[Oo]ps|'
                r'[Mm]achine [Ll]earning|[Aa]rtificial [Ii]ntelligence|[Ll]angChain|'
                r'[Ff]astAPI|[Dd]jango|[Ss]pring|[Nn]ode\.?[Jj]s|[Aa]PI|'
                r'[Ss]erverless|[Ll]ambda|[Ee]cs|[Ee]ks|[Gg]ke|[Cc]loud|'
                r'[Kk]afka|[Rr]abbitMQ|[Aa]pache|[Nn]ginx|[Cc][Nncf]|[Pp]y[Tt]orch|'
                r'[Tt]ensorFlow|[Ss]cikit|[Pp]andas|[Nn]umPy|[Ss]QL|[Nn]oSQL|'
                r'[Cc]hat[Gg]pt|[Gg]pt|[Cc]laude|[Oo]penAI|[Aa]nthropic)\b',
                description
            )
            tags.extend(list(set(tech_keywords))[:20])

        return list(set(tags))[:15]

    def _is_remote(self, title: str, location: Optional[str], description: Optional[str]) -> bool:
        """Determine if job is remote."""
        keywords = [
            "remote", "remoto", "work from home", "home office", "teletrabajo",
            "hybrid", "híbrido", "flexible", "anywhere", "any location",
            "100% remote", "fully remote", "remote-first",
        ]
        text = f"{title} {location or ''} {description or ''}".lower()
        return any(kw in text for kw in keywords)

    def _parse_salary(self, salary_str: Optional[str]) -> tuple[Optional[int], Optional[int]]:
        """Parse salary string to numeric values."""
        if not salary_str:
            return None, None

        nums = re.findall(r'[\d,]+(?:\.\d+)?', salary_str.replace(",", ""))
        if not nums:
            return None, None

        try:
            vals = [int(float(n)) for n in nums[:2]]
            if len(vals) == 1:
                return vals[0], vals[0]
            return vals[0], vals[1]
        except ValueError:
            return None, None
