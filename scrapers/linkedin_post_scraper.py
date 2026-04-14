"""
ergane/scrapers/linkedin_post_scraper.py
Scraper for LinkedIn post URLs that contain job descriptions.
Handles posts where users share job opportunities in the post text.

Usage:
    scraper = LinkedInPostScraper(db_path='ergane.db')
    job = scraper.scrape_post_url('https://www.linkedin.com/posts/username_activity-123456')
"""
import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from urllib.parse import urlparse

from scrapling import StealthyFetcher

from db.models import Job

_executor = ThreadPoolExecutor(max_workers=1)

logger = logging.getLogger(__name__)


class LinkedInPostScraper:
    """Scraper for LinkedIn post URLs containing job descriptions."""

    source_name = "linkedin_post"

    def __init__(self, db_path: str, headless: bool = True):
        """
        Args:
            db_path: Path to SQLite database (kept for API compatibility)
            headless: Run browser in headless mode
        """
        self.db_path = db_path
        self.headless = headless
        self.fetcher = StealthyFetcher()

    def scrape_post_url(self, post_url: str) -> Optional[Job]:
        """
        Scrape a LinkedIn post URL and extract job information from the post content.

        Args:
            post_url: LinkedIn post URL
                Formats supported:
                - linkedin.com/posts/...
                - linkedin.com/feed/update/...
                - linkedin.com/pulse/... (articles)
                - linkedin.com/embed/feed/...

        Returns:
            Job object with extracted information or None if scraping fails
        """
        try:
            logger.info("[%s] Fetching post: %s", self.source_name, post_url)

            def _fetch():
                return self.fetcher.fetch(
                    post_url,
                    headless=self.headless,
                    timeout=90000,
                    wait=3000,
                    network_idle=True,
                )

            try:
                asyncio.get_running_loop()
                future = _executor.submit(_fetch)
                page = future.result(timeout=120)
            except RuntimeError:
                page = _fetch()

            if not page:
                logger.warning("[%s] No content received from LinkedIn", self.source_name)
                return None

            job = self._parse_post_page(page, post_url)

            if job:
                logger.info(
                    "[%s] Successfully scraped post: %s @ %s",
                    self.source_name, job.title, job.company or "Unknown"
                )
            else:
                logger.warning("[%s] Failed to parse job data from post", self.source_name)

            return job

        except Exception as e:
            logger.exception("[%s] Error scraping post: %s", self.source_name, e)
            return None

    def _parse_post_page(self, page, post_url: str) -> Optional[Job]:
        """Parse LinkedIn post page to extract job information."""
        try:
            # Extract all text content from the post
            post_text = self._extract_post_text(page)

            if not post_text:
                logger.warning("[%s] No text content found in post", self.source_name)
                return None

            # Parse job information from post text
            job_info = self._parse_job_from_text(post_text)

            if not job_info.get("title"):
                logger.warning("[%s] Could not extract job title from post", self.source_name)
                return None

            # Extract external links from the post (application links, company website, etc.)
            external_links = self._extract_external_links(page, post_url)

            # Build the Job object
            # Store external links in description if present
            full_description = post_text
            if external_links:
                full_description += "\n\n---\n🔗 Application Links:\n"
                for link in external_links:
                    full_description += f"• {link}\n"

            return Job(
                url=post_url,
                title=job_info.get("title", "Unknown"),
                source=self.source_name,
                company=job_info.get("company"),
                location=job_info.get("location"),
                salary_min=job_info.get("salary_min"),
                salary_max=job_info.get("salary_max"),
                salary_raw=job_info.get("salary_raw"),
                description=full_description,
                tags=job_info.get("tags", []),
                remote=job_info.get("remote", False),
            )

        except Exception as e:
            logger.exception("[%s] Error parsing post page: %s", self.source_name, e)
            return None

    def _extract_post_text(self, page) -> str:
        """Extract text content from a LinkedIn post page."""
        try:
            # Try multiple selectors for post content
            # LinkedIn uses different class names for post text
            selectors = [
                '[data-test-id="main-text"]',  # Post main text
                '.update-components-text',  # Update component text
                '[class*="feed-shared-inline-show-more-text"]',  # Show more text
                'div[class*="update-components-text"]',
                'span[class*="break-words"]',
                '.feed-shared-update-v2__description-text',
                '#feed-shared-inline-show-more-text',
            ]

            for selector in selectors:
                try:
                    element = page.css_first(selector)
                    if element and element.text:
                        text = element.text.strip()
                        if len(text) > 50:  # Minimum text length to be valid
                            return text
                except:
                    continue

            # Fallback: try to get text from any text-containing elements
            texts = []
            for tag in ['p', 'span']:
                elements = page.css(tag)
                for el in elements[:30]:  # Limit to first 30 elements
                    try:
                        text = el.text.strip() if el.text else ""
                        if text and len(text) > 20:
                            texts.append(text)
                    except:
                        continue

            if texts:
                return "\n".join(texts[:10])  # Take first 10 meaningful text blocks

            return ""

        except Exception as e:
            logger.error("[%s] Error extracting post text: %s", self.source_name, e)
            return ""

    def _parse_job_from_text(self, text: str) -> dict:
        """
        Parse job information from LinkedIn post text.
        Uses pattern matching to extract title, company, location, etc.
        """
        job_info = {
            "title": None,
            "company": None,
            "location": None,
            "salary_min": None,
            "salary_max": None,
            "salary_raw": None,
            "tags": [],
            "remote": False,
        }

        # Job title patterns
        title_patterns = [
            r'(?:vacante|posición|puesto|role|position)\s*[:\-]\s*(.+?)(?:\n|$)',
            r'(?:job\s+title|position)\s*[:\-]\s*(.+?)(?:\n|$)',
            r'Oferta\s*[:\-]\s*(.+?)(?:\n|$)',
            r'Busco\s+(.+?)\s+que\s',
            r'(?:estamos buscando|buscamos|hiring|looking for|seeking|we\'re looking for)\s+(?:a\s+)?(.+?)(?:\n|que\s)',
            r'Busco\s+(.+?)(?:\n\n)',
            r'(?:job\s*title|position)\s*[:\-]\s*(.+?)(?:\n|$)',
        ]

        for pattern in title_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                if len(title) < 100:  # Sanity check
                    job_info["title"] = title
                    break

        if not job_info["title"]:
            # Try to extract from hashtags or keywords
            title_keywords = re.findall(
                r'(#\w+)',
                text
            )
            for kw in title_keywords:
                kw_clean = kw.replace("#", "").lower()
                if any(word in kw_clean for word in ["devops", "developer", "engineer", "ing", "analyst"]):
                    job_info["title"] = kw.replace("#", "")
                    break

        if not job_info["title"]:
            # Try Busco X que... pattern - stop at "que"
            busco_match = re.search(
                r'Busco\s+(.+?)\s+que\s',
                text,
                re.IGNORECASE
            )
            if busco_match:
                potential_title = busco_match.group(1).strip()
                if len(potential_title) < 80:
                    job_info["title"] = potential_title
            else:
                # Generic job titles from first meaningful line
                title_match = re.search(
                    r'^(.+?(?:Engineer|Developer|DevOps|MLOps|Cloud|Analyst|Architect|Manager|Coordinator|Consultant|SRE|Ingenier)[^\n]*)',
                    text,
                    re.IGNORECASE | re.MULTILINE
                )
                if title_match:
                    job_info["title"] = title_match.group(1).strip()

        # Company name patterns
        company_patterns = [
            r'(?:en|at|for|@)\s+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑ0-9\s&.,]+?)(?:\s|$|\n)',
            r'(?:empresa|company)\s*:\s*(.+?)(?:\n|$)',
            r'#([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑ0-9\s&.]+)(?=\s|$)',
        ]

        for pattern in company_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                company = match.group(1).strip()
                if len(company) < 50:
                    job_info["company"] = company
                    break

        # Location patterns
        location_patterns = [
            r'(?:en|in|from)\s+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑ0-9\s,.-]+?)(?:\s+(?:remoto|remote|$|\n))',
            r'(?:ubicación|location|cdmx|méxico|remote)\s*:\s*(.+?)(?:\n|$)',
        ]

        for pattern in location_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                location = match.group(1).strip()
                if len(location) < 100:
                    job_info["location"] = location
                    break

        # Salary patterns
        salary_patterns = [
            r'(?:salario|salary|sueldo|compensación)\s*:\s*(.+?)(?:\n|$)',
            r'(\$[\d,.\s]+(?:\s*-\s*\$[\d,.\s]+)?(?:\s*(?:usd|mxn|pesos|dólares))?)',
            r'(\$[\d,.\s]+)\s*(?:a|al|to|-)\s*(\$[\d,.\s]+)',
        ]

        for pattern in salary_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                salary_raw = match.group(0).strip()
                job_info["salary_raw"] = salary_raw
                job_info["salary_min"], job_info["salary_max"] = self._parse_salary(salary_raw)
                break

        # Extract skills/technologies from text
        tech_keywords = re.findall(
            r'\b([Aa][Ww][Ss]|[Dd]ocker|[Kk]ubernetes|[Tt]erraform|[Pp]ython|[Jj]ava|[Gg]o|[Rr]eact|'
            r'[Nn]ode\.?[Jj]s|[Ss]ql|[Nn]o[Ss][Qq][Ll]|[Gg]it|[Cc][Ii]/[Cc][Dd]|[Ll]inux|[Aa]nsible|'
            r'[Pp]ostgres|[Mm]ongo[Dd][Bb]|[Rr]edis|[Cc]loud|[Dd]ev[Oo]ps|[Aa]zure|[Gg]CP|[Tt]ypescript|'
            r'[Jj]ava[Ss]cript|[Hh]tml|[Cc][Ss][Ss]|[Ss]3|[Ll]ambda|[Dd]ynamo[Dd][Bb]|'
            r'[Mm]achine [Ll]earning|[Dd]ata [Ss]cience|[Ss]crum|[Aa]gile)\b',
            text
        )

        if tech_keywords:
            job_info["tags"] = list(set(tech_keywords))  # Remove duplicates

        # Check if remote
        remote_keywords = ["remoto", "remote", "teletrabajo", "home office", "work from home"]
        text_lower = text.lower()
        job_info["remote"] = any(kw in text_lower for kw in remote_keywords)

        # If no title was found, try to generate one from the content
        if not job_info["title"]:
            # Look for role-related words in the text
            role_match = re.search(
                r'(devops|developer|engineer|ing\.?|developer|programador|analista|arquitecto|coordinator|manager)',
                text,
                re.IGNORECASE
            )
            if role_match:
                job_info["title"] = role_match.group(0).capitalize()
            else:
                # Last resort: use first meaningful phrase as title
                job_info["title"] = "Job Opportunity"

        return job_info

    def _extract_external_links(self, page, post_url: str) -> list[str]:
        """Extract external links from the post (application links, company pages, etc.)."""
        try:
            links = []
            post_domain = urlparse(post_url).netloc

            # Find all anchor tags
            anchors = page.css('a[href]')
            for anchor in anchors:
                # Scrapling v0.3+ uses .get() instead of .attrs
                href = anchor.get('href', '')
                if not href:
                    continue

                # Skip LinkedIn internal links
                if 'linkedin.com' in href and post_domain in href:
                    continue

                # Skip relative LinkedIn links
                if href.startswith('/feed/') or href.startswith('/posts/'):
                    continue

                # Keep only valid external URLs
                if href.startswith(('http://', 'https://')):
                    parsed = urlparse(href)
                    # Skip LinkedIn tracking URLs
                    if 'linkedin.com' in parsed.netloc and '/redir/' in parsed.path:
                        continue
                    links.append(href)

            return list(set(links))  # Remove duplicates

        except Exception as e:
            logger.error("[%s] Error extracting external links: %s", self.source_name, e)
            return []

    def _parse_salary(self, salary_str: str) -> tuple[Optional[int], Optional[int]]:
        """Parse salary string to numeric values."""
        if not salary_str:
            return None, None

        # Extract numbers from salary string
        nums = re.findall(r'[\d,]+', salary_str.replace(",", ""))
        if not nums:
            return None, None

        vals = [int(n) for n in nums[:2]]
        if len(vals) == 1:
            return vals[0], vals[0]
        return vals[0], vals[1]


def is_linkedin_post_url(url: str) -> bool:
    """Check if URL is a LinkedIn post URL (not a jobs URL)."""
    # Must be a LinkedIn URL but NOT a jobs URL
    if "linkedin.com" not in url or "linkedin.com/jobs" in url:
        return False

    # Check for post-related path patterns
    post_patterns = [
        "/posts/",
        "/feed/update/",
        "/pulse/",
        "/embed/feed/",
        "/feed/",
        "/publish/",
    ]

    return any(pattern in url for pattern in post_patterns)
