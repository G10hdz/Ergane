"""
ergane/scrapers/getonbrd.py
Scraper for GetOnBrd (https://www.getonbrd.com/jobs?query=devops&country=MX)
Sitio renderiza JS, requiere Playwright.
"""
import logging
import re
from typing import Optional

from db.models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.getonbrd.com"

SEARCH_KEYWORDS = ["devops", "cloud", "python", "mlops", "ai", "data-engineer"]


def _build_search_urls(keywords: list[str]) -> list[str]:
    """Build search URLs for each keyword."""
    return [
        f"https://www.getonbrd.com/jobs?query={kw}&country=MX"
        for kw in keywords
    ]


class GetOnBrdScraper(BaseScraper):
    """Scraper for GetOnBrd Mexico jobs."""

    source_name = "getonbrd"

    def __init__(self, db_path: str, headless: bool = True, max_pages: int = 2):
        super().__init__(db_path, headless=headless, rate_limit_min=2.0, rate_limit_max=5.0)
        self.max_pages = max_pages

    def scrape(self) -> list[Job]:
        """
        Scrape GetOnBrd jobs page using Playwright.
        Visits detail pages to fetch descriptions.
        """
        jobs = []
        seen_urls = set()
        search_urls = _build_search_urls(SEARCH_KEYWORDS)
        page = self.page()

        try:
            for search_url in search_urls:
                try:
                    for page_num in range(1, self.max_pages + 1):
                        if page_num > 1:
                            page_url = f"{search_url}&page={page_num}"
                        else:
                            page_url = search_url

                        logger.info("[%s] Navigating to %s (page %d)", self.source_name, page_url, page_num)
                        page.goto(page_url, wait_until="domcontentloaded", timeout=30000)

                        # Wait for job links
                        try:
                            page.wait_for_selector("a[href*='/jobs/']", timeout=10000)
                        except Exception:
                            logger.warning("[%s] No job links on page %d at %s", self.source_name, page_num, page_url)
                            break

                        # Collect job links
                        link_els = page.query_selector_all("a[href*='/jobs/']")
                        if not link_els:
                            logger.info("[%s] No links on page %d", self.source_name, page_num)
                            break

                        logger.info("[%s] Found %d job links", self.source_name, len(link_els))

                        # FIRST: Extract data from listing page before any navigation
                        listing_data = []
                        for link_el in link_els:
                            try:
                                href = link_el.get_attribute("href") or ""
                                # Normalize: must be a full job URL
                                if not href.startswith("http"):
                                    href = f"https://www.getonbrd.com{href}"
                                href = href.split("?")[0].rstrip("/")
                                if href.count("/") < 5:
                                    continue
                                if href in seen_urls:
                                    continue
                                seen_urls.add(href)

                                # Extract all card data NOW (before navigation)
                                card_data = self._extract_card_data(link_el, href)
                                if card_data:
                                    listing_data.append(card_data)
                            except Exception as e:
                                logger.debug("[%s] Error extracting card data: %s", self.source_name, e)
                                continue

                        # SECOND: Visit detail pages to get descriptions
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
                                    salary_min=card_data.get("salary_min"),
                                    salary_max=card_data.get("salary_max"),
                                    salary_raw=card_data.get("salary_raw"),
                                    description=description,
                                    tags=card_data.get("tags", []),
                                    remote=card_data.get("remote", False),
                                )
                                jobs.append(job)
                            except Exception as e:
                                logger.warning("[%s] Error building Job: %s", self.source_name, e)
                                continue

                        self._random_sleep()

                except Exception as e:
                    logger.warning("[%s] Error on %s: %s", self.source_name, search_url, e)
                    continue

        except Exception as e:
            logger.exception("[%s] Error general en scraping: %s", self.source_name, e)
            raise
        finally:
            page.close()

        logger.info("[%s] Scraping completado: %d jobs extraídos", self.source_name, len(jobs))
        return jobs

    def _fetch_description(self, page, job_url: str) -> str:
        """Visit a job detail page and extract description text."""
        page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2000)

        # Try common description containers
        for selector in [".job-description", "[class*='description']", ".description", "article section", "main"]:
            el = page.query_selector(selector)
            if el:
                text = el.inner_text().strip()
                if len(text) > 50:
                    return text

        # Fallback: get all text from the body section
        body_text = page.inner_text("body")[:2000]
        return body_text if body_text else None

    def _extract_card_data(self, link_el, job_url: str) -> Optional[dict]:
        """Extract all data from a job card element (before navigation)."""
        try:
            title_text = link_el.inner_text().strip().splitlines()[0].strip()
            if not title_text:
                return None

            lines = [l.strip() for l in link_el.inner_text().splitlines() if l.strip()]

            company = None
            location = None
            if len(lines) > 1:
                parts = lines[1].split(" — ", 1)
                company = parts[0].strip() or None
                location = parts[1].strip() if len(parts) > 1 else None

            tags = []
            tag_els = link_el.query_selector_all(".tag, .badge, [class*='tag-item']")
            for tag_el in tag_els:
                tag_text = tag_el.inner_text().strip()
                if tag_text and len(tag_text) < 40:
                    tags.append(tag_text)

            salary_min, salary_max, salary_raw = self._extract_salary(link_el)
            remote = self._is_remote(title_text, location, tags)

            return {
                "url": job_url,
                "title": title_text,
                "company": company,
                "location": location,
                "salary_min": salary_min,
                "salary_max": salary_max,
                "salary_raw": salary_raw,
                "tags": tags,
                "remote": remote,
            }
        except Exception as e:
            logger.debug("[%s] Error extracting card data: %s", self.source_name, e)
            return None

    def _extract_salary(self, card) -> tuple[Optional[int], Optional[int], Optional[str]]:
        """Extrae información salarial."""
        salary_el = card.query_selector("[class*='salary'], .job-salary")
        if not salary_el:
            return None, None, None

        salary_raw = salary_el.inner_text().strip()
        if not salary_raw:
            return None, None, None

        numbers = re.findall(r'[\d,]+\.?\d*', salary_raw.replace(",", ""))
        if not numbers:
            return None, None, salary_raw

        values = [float(n) for n in numbers[:2]]
        
        # Detectar USD
        multiplier = 17 if ("usd" in salary_raw.lower() or "$" in salary_raw) else 1
        
        # Detectar 'k'
        if "k" in salary_raw.lower():
            values = [v * 1000 for v in values]
            
        values = [int(v * multiplier) for v in values]
        
        if len(values) == 1:
            return values[0], values[0], salary_raw
        return values[0], values[1], salary_raw

    def _is_remote(self, title: str, location: Optional[str], tags: list[str]) -> bool:
        """Determina si es remoto."""
        remote_keywords = ["remote", "remoto", "work from home", "home office", "teletrabajo"]
        text = f"{title} {location or ''} {' '.join(tags)}".lower()
        return any(kw in text for kw in remote_keywords)
