"""
ergane/scrapers/generic_job_scraper.py
Generic scraper for job pages from any website.
Uses Scrapling StealthyFetcher for anti-detection.

Usage:
    scraper = GenericJobScraper(db_path='ergane.db')
    job = scraper.scrape_job_url('https://example.com/jobs/devops-engineer')
"""
import logging
import re
from typing import Optional
from urllib.parse import urlparse, urljoin

from scrapling import StealthyFetcher

from db.models import Job

logger = logging.getLogger(__name__)

# Keywords that suggest a page is job-related
JOB_KEYWORDS = [
    "hiring", "job", "vacante", "empleo", "trabajo", "apply", "aplicar",
    "position", "posición", "career", "carrera", "opportunity", "oportunidad",
    "we're looking", "buscamos", "estamos buscando", "join our team",
    "job description", "requisitos", "requirements", "responsibilities",
    "benefits", "beneficios", "salary", "salario", "compensación",
    "full-time", "medio tiempo", "remote", "remoto", "hybrid", "híbrido",
    "experience", "experiencia", "qualifications", "calificaciones",
    "skills", "habilidades", "apply now", "apply today", "postulate",
]

# Keywords that suggest a page is NOT job-related
NON_JOB_KEYWORDS = [
    "login", "sign in", "dashboard", "panel", "settings", "configuración",
    "404", "page not found", "not found", "no encontrado",
    "cart", "carrito", "checkout", "payment", "pago",
    "privacy policy", "términos", "terms of service",
    "cookie", "newsletter", "suscribe", "suscríbete",
]


class GenericJobScraper:
    """Scraper for job pages from any website."""

    source_name = "generic"

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
        Scrape a job page from any website.

        Args:
            job_url: URL of the job posting

        Returns:
            Job object or None if page is not job-related or scraping fails
        """
        try:
            logger.info("[%s] Fetching job: %s", self.source_name, job_url)

            page = self.fetcher.fetch(
                job_url,
                headless=self.headless,
                timeout=60,
                wait=3000,
                network_idle=True,
            )

            if not page:
                logger.warning("[%s] No content received", self.source_name)
                return None

            # Check if page looks like a job posting
            page_text = self._extract_page_text(page)
            if not self._is_job_page(page_text):
                logger.warning("[%s] Page does not appear to be job-related", self.source_name)
                return None

            # Parse job information
            job = self._parse_job_page(page, job_url, page_text)

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

    def _extract_page_text(self, page) -> str:
        """Extract all meaningful text from the page."""
        try:
            # Try common content containers first
            selectors = [
                'article', 'main', '[role="main"]',
                '.job-details', '.job-description', '#job-details', '#job-description',
                '.career', '.position', '.vacancy',
                'section[class*="job"]', 'section[class*="career"]',
            ]

            for selector in selectors:
                element = page.css_first(selector)
                if element and element.text:
                    text = element.text.strip()
                    if len(text) > 100:
                        return text

            # Fallback: get text from body
            body = page.css_first('body')
            if body and body.text:
                return body.text.strip()

            # Last resort: concatenate all text from p, div, span
            texts = []
            for tag in ['p', 'div', 'span', 'li']:
                elements = page.css(tag)
                for el in elements[:50]:
                    if el.text:
                        text = el.text.strip()
                        if text and len(text) > 20:
                            texts.append(text)

            return "\n".join(texts[:30])

        except Exception as e:
            logger.error("[%s] Error extracting page text: %s", self.source_name, e)
            return ""

    def _is_job_page(self, text: str) -> bool:
        """Check if page content appears to be job-related."""
        if not text:
            return False

        text_lower = text.lower()

        # Check for non-job keywords first (negative signal)
        non_job_score = sum(1 for kw in NON_JOB_KEYWORDS if kw in text_lower)
        if non_job_score >= 3:
            return False

        # Check for job-related keywords
        job_score = sum(1 for kw in JOB_KEYWORDS if kw in text_lower)
        if job_score >= 2:
            return True

        # Check for job-like patterns
        job_patterns = [
            r'job\s*(title|description|summary)',
            r'vacante[s]?\s*[:.]',
            r'estamos\s+buscando',
            r'we(\'re| are)\s+(hiring|looking|seeking)',
            r'(apply|postulate)\s+(now|today|here)',
            r'salary\s*[:.]\s*\$?',
            r'requisitos?\s*[:.]',
            r'requirements?\s*[:.]',
        ]

        return any(re.search(p, text_lower) for p in job_patterns)

    def _parse_job_page(self, page, job_url: str, page_text: str) -> Optional[Job]:
        """Parse job information from page."""
        try:
            job_info = {
                "title": None,
                "company": None,
                "location": None,
                "salary_min": None,
                "salary_max": None,
                "salary_raw": None,
                "description": page_text,
                "tags": [],
                "remote": False,
            }

            # Try to extract title from page
            job_info["title"] = self._extract_title(page, page_text)
            if not job_info["title"]:
                # Fallback: use page title or URL
                title_el = page.css_first('title')
                if title_el and title_el.text:
                    job_info["title"] = title_el.text.strip()
                else:
                    parsed = urlparse(job_url)
                    job_info["title"] = parsed.path.strip('/').replace('-', ' ').replace('_', ' ').title()

            # Try to extract company
            job_info["company"] = self._extract_company(page, page_text)

            # Try to extract location
            job_info["location"] = self._extract_location(page, page_text)

            # Try to extract salary
            salary_raw = self._extract_salary_text(page, page_text)
            if salary_raw:
                job_info["salary_raw"] = salary_raw
                job_info["salary_min"], job_info["salary_max"] = self._parse_salary(salary_raw)

            # Extract skills/technologies
            job_info["tags"] = self._extract_skills(page_text)

            # Check if remote
            job_info["remote"] = self._is_remote(page_text)

            # Extract application links
            app_links = self._extract_application_links(page, job_url)
            description = page_text
            if app_links:
                description += "\n\n---\n🔗 Application Links:\n"
                for link in app_links:
                    description += f"• {link}\n"

            return Job(
                url=job_url,
                title=job_info["title"],
                source=self.source_name,
                company=job_info["company"],
                location=job_info["location"],
                salary_min=job_info["salary_min"],
                salary_max=job_info["salary_max"],
                salary_raw=job_info["salary_raw"],
                description=description,
                tags=job_info["tags"],
                remote=job_info["remote"],
            )

        except Exception as e:
            logger.exception("[%s] Error parsing job page: %s", self.source_name, e)
            return None

    def _extract_title(self, page, page_text: str) -> Optional[str]:
        """Extract job title from page."""
        # Try common selectors
        selectors = [
            'h1', 'h1[class*="title"]', 'h1[class*="job"]',
            '[class*="job-title"]', '[class*="position-title"]',
            'meta[property="og:title"]',
        ]

        for selector in selectors:
            if selector.startswith('meta'):
                el = page.css_first(selector)
                if el:
                    title = el.attrs.get('content', '')
                    if title:
                        return title.strip()
            else:
                el = page.css_first(selector)
                if el and el.text:
                    title = el.text.strip()
                    if title and len(title) < 150:
                        return title

        # Try to find title from patterns in text
        title_patterns = [
            r'(?:job\s*title|position|role|vacante|puesto)\s*[:\-]\s*(.+?)(?:\n|$)',
            r'(?:we(\'re| are)\s+hiring\s*[a|an]?\s*)(.+?)(?:\n|$)',
            r'(?:buscamos|estamos\s+buscando)\s+(?:un|una)?\s*(.+?)(?:\n|$)',
        ]

        for pattern in title_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                if title and len(title) < 150:
                    return title

        return None

    def _extract_company(self, page, page_text: str) -> Optional[str]:
        """Extract company name from page."""
        # Try common selectors
        selectors = [
            '[class*="company"]', '[class*="employer"]',
            'meta[property="og:site_name"]',
            'a[href*="/company"]', 'a[href*="/about"]',
        ]

        for selector in selectors:
            if selector.startswith('meta'):
                el = page.css_first(selector)
                if el:
                    company = el.attrs.get('content', '')
                    if company:
                        return company.strip()
            else:
                el = page.css_first(selector)
                if el and el.text:
                    company = el.text.strip()
                    if company and len(company) < 100:
                        return company

        # Try patterns in text
        company_patterns = [
            r'(?:en|at|for|@|by)\s+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑ0-9\s&.,-]+?)(?:\s+is|\s+has|\n|$)',
            r'(?:company|empresa|employer)\s*[:\-]\s*(.+?)(?:\n|$)',
            r'(?:©|Copyright)\s*(?:\d{4}\s+)?([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑ0-9\s&.,-]+)',
        ]

        for pattern in company_patterns:
            match = re.search(pattern, page_text)
            if match:
                company = match.group(1).strip()
                if company and len(company) < 80:
                    return company

        return None

    def _extract_location(self, page, page_text: str) -> Optional[str]:
        """Extract location from page."""
        selectors = [
            '[class*="location"]', '[class*="place"]',
            'meta[property="job:location"]',
            '[class*="city"]', '[class*="address"]',
        ]

        for selector in selectors:
            el = page.css_first(selector)
            if el and el.text:
                location = el.text.strip()
                if location and len(location) < 100:
                    return location

        # Try patterns
        location_patterns = [
            r'(?:location|ubicación|lugar|city|ciudad)\s*[:\-]\s*(.+?)(?:\n|$)',
            r'(?:en|in)\s+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑ0-9\s,.-]+?)(?:\s+remoto|\s+remote|\n|$)',
        ]

        for pattern in location_patterns:
            match = re.search(pattern, page_text)
            if match:
                location = match.group(1).strip()
                if location and len(location) < 100:
                    return location

        return None

    def _extract_salary_text(self, page, page_text: str) -> Optional[str]:
        """Extract salary text from page."""
        selectors = [
            '[class*="salary"]', '[class*="compensation"]',
            '[class*="pay"]', '[class*="remuneration"]',
        ]

        for selector in selectors:
            el = page.css_first(selector)
            if el and el.text:
                salary = el.text.strip()
                if salary:
                    return salary

        # Try patterns
        salary_patterns = [
            r'(?:salary|salario|sueldo|compensación|pay|pago)\s*[:\-]\s*(.+?)(?:\n|$)',
            r'(\$[\d,.\s]+(?:\s*(?:-\s*|\s+a\s+|\s+to\s+)\$[\d,.\s]+)?)',
        ]

        for pattern in salary_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                return match.group(0).strip()

        return None

    def _extract_skills(self, page_text: str) -> list[str]:
        """Extract skills/technologies from page text."""
        tech_keywords = re.findall(
            r'\b([Aa]ngular|[Aa]nalytics|[Aa]nsible|[Aa]WS|[Aa]zure|[Aa]rchitecture|'
            r'[Bb]ash|[Cc]loud|[Cc]ICD|[Cc]ontainerization|[Cc]ontainers|[Cc]SS|'
            r'[Dd]ata[Bb]ase|[Dd]ocker|[Dd]evOps|[Dd]jango|[Dd]ynamoDB|'
            r'[Ee]xpress|[Ff]astAPI|[Ff]irebase|[Gg]CP|[Gg]it|[Gg]o|[Gg]raphQL|'
            r'[Hh]elm|[Hh]TML|[Hh]adoop|[Hh]askell|'
            r'[Jj]ava[Ss]cript|[Jj]enkins|[Jj]inja|[Jj]ira|[Kk]afka|[Kk]ubernetes|'
            r'[Ll]inux|[Ll]lama|[Ll]angChain|[Mm]achine [Ll]earning|[Mm]atplotlib|'
            r'[Mm]ongoDB|[Mm]ySQL|[Nn]estJS|[Nn]ginx|[Nn]ode\.?[Jj]s|[Nn]oSQL|'
            r'[Nn]umPy|[Oo]penAI|[Pp]andas|[Pp]ostgreSQL|[Pp]yTorch|[Pp]ython|'
            r'[Rr]abbitMQ|[Rr]eact|[Rr]edis|[Rr]uby|[Rr]ust|[Ss]3|[Ss]cala|'
            r'[Ss]elenium|[Ss]elenium|[Ss]pring|[Ss]QL|[Ss]wagger|[Tt]ensorFlow|'
            r'[Tt]erraform|[Tt]ypeScript|[Vv]ue|[Ww]ebpack|[Ww]orkflow|[Zz]apier)\b',
            page_text
        )

        return list(set(tech_keywords))

    def _is_remote(self, page_text: str) -> bool:
        """Check if job is remote."""
        remote_keywords = [
            "remote", "remoto", "teletrabajo", "work from home", "home office",
            "trabajo remoto", "100% remote", "fully remote", "remote-first",
        ]
        text_lower = page_text.lower()
        return any(kw in text_lower for kw in remote_keywords)

    def _extract_application_links(self, page, job_url: str) -> list[str]:
        """Extract application-related links from page."""
        try:
            links = []
            job_domain = urlparse(job_url).netloc

            # Find all anchor tags
            anchors = page.css('a[href]')
            for anchor in anchors:
                href = anchor.attrs.get('href', '')
                if not href:
                    continue

                # Make absolute URL
                abs_href = urljoin(job_url, href)

                # Skip same-page links
                if abs_href == job_url or abs_href.startswith('#'):
                    continue

                # Check if link text suggests application
                link_text = (anchor.text or '').lower()
                is_app_link = any(kw in link_text for kw in [
                    "apply", "aplicar", "postulate", "postularme",
                    "submit", "enviar", "join", "únete",
                    "apply now", "apply today", "candidate form",
                ])

                # Also check if URL path suggests application
                parsed = urlparse(abs_href)
                is_app_url = any(kw in parsed.path.lower() for kw in [
                    "apply", "application", "career", "job", "vacante",
                    "postulate", "join", "form", "formulario",
                    "candidate", "talent", "hiring",
                ])

                if (is_app_link or is_app_url) and abs_href.startswith(('http://', 'https://')):
                    links.append(abs_href)

            return list(set(links))

        except Exception as e:
            logger.error("[%s] Error extracting application links: %s", self.source_name, e)
            return []

    def _parse_salary(self, salary_str: str) -> tuple[Optional[int], Optional[int]]:
        """Parse salary string to numeric values."""
        if not salary_str:
            return None, None

        nums = re.findall(r'[\d,]+', salary_str.replace(",", ""))
        if not nums:
            return None, None

        vals = [int(n) for n in nums[:2]]
        if len(vals) == 1:
            return vals[0], vals[0]
        return vals[0], vals[1]
