"""
ergane/scrapers/occ.py
Scraper for OCC Mundial (https://www.occ.com.mx) using Playwright.
Job cards identified by [data-id] attribute.
"""
import logging
import re
from typing import Optional

from db.models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.occ.com.mx"

SEARCH_KEYWORDS = ["devops", "cloud", "python", "mlops", "ai", "data engineer"]


def _build_search_urls(keywords: list[str]) -> list[str]:
    return [f"{BASE_URL}/empleos/?q={kw}" for kw in keywords]


class OCCScraper(BaseScraper):
    """Playwright scraper for OCC Mundial Mexico."""

    source_name = "occ"

    def __init__(self, db_path: str, headless: bool = True, max_pages: int = 2):
        super().__init__(db_path, headless=headless, rate_limit_min=2.0, rate_limit_max=4.0)
        self.max_pages = max_pages

    def scrape(self) -> list[Job]:
        jobs = []
        seen_urls = set()
        search_urls = _build_search_urls(SEARCH_KEYWORDS)
        page = self.page()

        try:
            page.set_extra_http_headers({"Accept-Language": "es-MX,es;q=0.9"})

            for search_url in search_urls:
                try:
                    for page_num in range(1, self.max_pages + 1):
                        if page_num > 1:
                            page_url = f"{search_url}&p={page_num}"
                        else:
                            page_url = search_url

                        logger.info("[%s] Navigating to %s (page %d)", self.source_name, page_url, page_num)
                        page.goto(page_url, wait_until="networkidle", timeout=45000)
                        page.wait_for_timeout(5000)

                        cards = page.query_selector_all("[data-id]")
                        if not cards:
                            logger.info("[%s] No cards on page %d at %s", self.source_name, page_num, page_url)
                            break

                        logger.info("[%s] Found %d job cards", self.source_name, len(cards))

                        for card in cards:
                            try:
                                job = self._parse_card(card)
                                if job and job.url not in seen_urls:
                                    seen_urls.add(job.url)
                                    # Fetch description from detail page
                                    try:
                                        desc_url = f"{BASE_URL}/empleo/oferta/?id={card.get_attribute('data-id')}"
                                        job.description = self._fetch_description(page, desc_url)
                                    except Exception as e:
                                        logger.debug("[%s] Failed to fetch description: %s", self.source_name, e)
                                    jobs.append(job)
                            except Exception as e:
                                logger.debug("[%s] Error parsing card: %s", self.source_name, e)

                        self._random_sleep()
                except Exception as e:
                    logger.warning("[%s] Error on %s: %s", self.source_name, search_url, e)
                    continue

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

        for selector in [".job-description", "[class*='description']", ".description", "section"]:
            el = page.query_selector(selector)
            if el:
                text = el.inner_text().strip()
                if len(text) > 50:
                    return text

        body_text = page.inner_text("body")[:2000]
        return body_text if body_text else None

    def _parse_card(self, card) -> Optional[Job]:
        data_id = card.get_attribute("data-id")
        if not data_id:
            return None

        job_url = f"{BASE_URL}/empleo/oferta/?id={data_id}"

        # Title
        h2 = card.query_selector("h2")
        title = h2.inner_text().strip() if h2 else ""
        if not title:
            return None

        # Salary — span whose text starts with "$" or "Sueldo"
        salary_raw = None
        for span in card.query_selector_all("span"):
            text = span.inner_text().strip()
            if text.startswith("$") or text.lower().startswith("sueldo"):
                salary_raw = text
                break

        salary_min, salary_max = self._parse_salary(salary_raw)

        # Company — <a class*="it-blank">
        company_el = card.query_selector('a[class*="it-blank"]')
        company = company_el.inner_text().strip() if company_el else None
        if company and company.lower() == "empresa confidencial":
            company = None

        # Location — <p class*="text-sm">
        loc_el = card.query_selector('p[class*="text-sm"]')
        location = loc_el.inner_text().strip() if loc_el else None

        remote = self._is_remote(title, location)

        return Job(
            url=job_url,
            title=title,
            source=self.source_name,
            company=company,
            location=location,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_raw=salary_raw,
            remote=remote,
        )

    def _parse_salary(self, salary_str: Optional[str]) -> tuple[Optional[int], Optional[int]]:
        if not salary_str or not salary_str.startswith("$"):
            return None, None
        nums = re.findall(r'[\d,]+', salary_str.replace(",", ""))
        vals = [int(n) for n in nums[:2] if n]
        if not vals:
            return None, None
        return (vals[0], vals[0]) if len(vals) == 1 else (vals[0], vals[1])

    def _is_remote(self, title: str, location: Optional[str]) -> bool:
        keywords = ["remote", "remoto", "home office", "teletrabajo"]
        text = f"{title} {location or ''}".lower()
        return any(kw in text for kw in keywords)
