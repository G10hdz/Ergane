"""
ergane/scrapers/computrabajo.py
Scraper for CompuTrabajo Mexico (https://mx.computrabajo.com) using Playwright.
Searches multiple tech keywords to maximize coverage.
"""
import logging
import re
from typing import Optional

from db.models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://mx.computrabajo.com"

SEARCH_URLS = [
    f"{BASE_URL}/trabajo-de-devops",
    f"{BASE_URL}/trabajo-de-cloud-engineer",
    f"{BASE_URL}/trabajo-de-mlops",
    f"{BASE_URL}/trabajo-de-site-reliability-engineer",
]


class CompuTrabajoScraper(BaseScraper):
    """Playwright scraper for CompuTrabajo Mexico."""

    source_name = "computrabajo"

    def __init__(self, db_path: str, headless: bool = True, max_pages: int = 2):
        super().__init__(db_path, headless=headless, rate_limit_min=3.0, rate_limit_max=6.0)
        self.max_pages = max_pages

    def scrape(self) -> list[Job]:
        jobs = []
        seen_urls = set()
        page = self.page()

        try:
            page.set_extra_http_headers({"Accept-Language": "es-MX,es;q=0.9"})

            for search_url in SEARCH_URLS:
                try:
                    for page_num in range(1, self.max_pages + 1):
                        if page_num > 1:
                            # Try to navigate to next page
                            page_url = f"{search_url}?page={page_num}"
                        else:
                            page_url = search_url

                        logger.info("[%s] Navigating to %s (page %d)", self.source_name, page_url, page_num)
                        page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(4000)

                        body_text = page.inner_text("body")[:500]
                        if "no hay ofertas" in body_text.lower():
                            logger.info("[%s] No results for %s", self.source_name, page_url)
                            break

                        articles = page.query_selector_all("article.box_offer")
                        if not articles:
                            logger.info("[%s] No articles on page %d at %s", self.source_name, page_num, page_url)
                            break

                        logger.info("[%s] Found %d cards at %s (page %d)", self.source_name, len(articles), search_url, page_num)

                        for article in articles:
                            try:
                                job = self._parse_card(article)
                                if job and job.url not in seen_urls:
                                    seen_urls.add(job.url)
                                    # Fetch description from detail page
                                    try:
                                        job.description = self._fetch_description(page, job.url)
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

        for selector in [".job-description", "[class*='description']", ".description", ".cv"]:
            el = page.query_selector(selector)
            if el:
                text = el.inner_text().strip()
                if len(text) > 50:
                    return text

        body_text = page.inner_text("body")[:2000]
        return body_text if body_text else None

    def _parse_card(self, card) -> Optional[Job]:
        title_link = card.query_selector("h2 a.js-o-link")
        if not title_link:
            return None

        title = title_link.inner_text().strip()
        if not title:
            return None

        href = title_link.get_attribute("href") or ""
        if not href:
            return None

        job_url = href if href.startswith("http") else f"{BASE_URL}{href}"
        job_url = job_url.split("#")[0]

        company = None
        company_el = card.query_selector("a[offer-grid-article-company-url]")
        if company_el:
            company = company_el.inner_text().strip() or None
        if not company:
            p_els = card.query_selector_all("p.fs16")
            for p in p_els:
                text = p.inner_text().strip()
                if text and "," not in text and "$" not in text:
                    company = text.rstrip(".")
                    break

        location = None
        loc_spans = card.query_selector_all("p.fs16 span.mr10")
        for span in loc_spans:
            text = span.inner_text().strip()
            if "," in text:
                location = text
                break

        salary_raw = None
        salary_el = card.query_selector("span.i_salary")
        if salary_el:
            parent = salary_el.evaluate("el => el.parentElement.textContent")
            if parent:
                salary_raw = parent.strip()

        salary_min, salary_max = self._parse_salary(salary_raw)
        remote = self._is_remote(card, title, location)

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
        if not salary_str:
            return None, None

        nums = re.findall(r'[\d,]+(?:\.\d+)?', salary_str.replace(",", ""))
        if not nums:
            return None, None

        vals = [int(float(n)) for n in nums[:2]]
        if len(vals) == 1:
            return vals[0], vals[0]
        return vals[0], vals[1]

    def _is_remote(self, card, title: str, location: Optional[str]) -> bool:
        card_text = card.inner_text().lower()
        keywords = ["remote", "remoto", "home office", "teletrabajo", "desde casa"]
        return any(kw in card_text for kw in keywords)
