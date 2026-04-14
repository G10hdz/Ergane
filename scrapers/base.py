"""
ergane/scrapers/base.py
Clase abstracta BaseScraper con manejo de Playwright, rate limiting y logging.
"""
import logging
import random
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from db.models import Job
from db.storage import log_run_end, log_run_start

logger = logging.getLogger(__name__)

# User agents para rotación
USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# Hardened browser args for production
BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu-compositing",
    "--disable-extensions",
    "--disable-background-timer-throttling",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-sync",
    "--metrics-recording-only",
    "--no-first-run",
    "--safebrowsing-disable-auto-update",
]

# Shared browser pool for reuse across scrapers
_shared_browser_lock = None
_shared_browser: Optional[Browser] = None
_shared_playwright: Optional[Playwright] = None


def get_shared_browser(headless: bool = True, timeout: int = 30) -> tuple[Browser, BrowserContext, Playwright]:
    """Get or create a shared browser instance for the pipeline."""
    global _shared_browser_lock, _shared_browser, _shared_playwright
    
    import threading
    if _shared_browser_lock is None:
        _shared_browser_lock = threading.Lock()
    
    with _shared_browser_lock:
        if _shared_browser is None or not _shared_browser.is_connected():
            _shared_playwright = sync_playwright().start()
            _shared_browser = _shared_playwright.chromium.launch(
                headless=headless,
                args=BROWSER_ARGS,
            )
            logger.info("Shared browser started (headless=%s)", headless)
    
    # Create a new context per scraper (isolated session)
    context = _shared_browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport={"width": 1920, "height": 1080},
    )
    context.set_default_timeout(timeout * 1000)
    
    return _shared_browser, context, _shared_playwright


def close_shared_browser() -> None:
    """Close the shared browser (call when pipeline completes)."""
    global _shared_browser_lock, _shared_browser, _shared_playwright
    
    import threading
    if _shared_browser_lock is None:
        _shared_browser_lock = threading.Lock()
    
    with _shared_browser_lock:
        if _shared_browser:
            try:
                _shared_browser.close()
            except:
                pass
            _shared_browser = None
        if _shared_playwright:
            try:
                _shared_playwright.stop()
            except:
                pass
            _shared_playwright = None
        logger.info("Shared browser closed")


class BaseScraper(ABC):
    """
    Clase abstracta para scrapers de empleos.
    
    Subclases deben implementar:
    - source_name: nombre de la fuente (ej: 'occ', 'techjobsmx')
    - scrape(): método que retorna list[Job]
    """

    source_name: str

    def __init__(
        self,
        db_path: str,
        headless: bool = True,
        rate_limit_min: float = 2.0,
        rate_limit_max: float = 5.0,
    ):
        """
        Args:
            db_path: Path a la base de datos SQLite
            headless: Si True, Playwright corre sin UI (producción)
            rate_limit_min: Mínimo segundos entre requests
            rate_limit_max: Máximo segundos entre requests
        """
        self.db_path = db_path
        self.headless = headless
        self.rate_limit_min = rate_limit_min
        self.rate_limit_max = rate_limit_max
        self.timeout = 30  # seconds per page operation
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._new_context_per_page = False  # Override per scraper if needed

    def _random_sleep(self) -> None:
        """Sleep aleatorio para rate limiting."""
        delay = random.uniform(self.rate_limit_min, self.rate_limit_max)
        logger.debug("Rate limit: sleeping %.2f seconds", delay)
        time.sleep(delay)

    def _get_user_agent(self) -> str:
        """Retorna un user-agent aleatorio."""
        return random.choice(USER_AGENTS)

    def __enter__(self) -> "BaseScraper":
        """Context manager: inicializa Playwright (own or shared)."""
        if hasattr(self, '_use_shared_browser') and self._use_shared_browser:
            # Use shared browser from pool
            self._browser, self._context, self._playwright = get_shared_browser(
                headless=self.headless,
                timeout=self.timeout,
            )
            self._owns_browser = False
            logger.info("[%s] Using shared browser (timeout=%ds)", self.source_name, self.timeout)
        else:
            # Own browser (default)
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=self.headless,
                args=BROWSER_ARGS,
            )
            self._context = self._browser.new_context(
                user_agent=self._get_user_agent(),
                viewport={"width": 1920, "height": 1080},
            )
            self._context.set_default_timeout(self.timeout * 1000)
            logger.info("[%s] Browser started (headless=%s, timeout=%ds)", self.source_name, self.headless, self.timeout)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager: close browser/context with timeout."""
        # Always close the context (isolates scraper sessions)
        if self._context:
            try:
                self._context.close(timeout=5000)
            except Exception as e:
                logger.warning("[%s] Context close error: %s", self.source_name, e)
        # Only close browser if we own it (not shared)
        if self._owns_browser and self._browser:
            try:
                self._browser.close()
            except Exception as e:
                logger.warning("[%s] Browser close error: %s", self.source_name, e)
        if self._owns_browser and self._playwright:
            try:
                self._playwright.stop()
            except Exception as e:
                logger.warning("[%s] Playwright stop error: %s", self.source_name, e)
        logger.info("[%s] Browser cleaned up (owns=%s)", self.source_name, self._owns_browser)

    def page(self) -> Page:
        """Crea una nueva página en el contexto con timeout."""
        if not self._context:
            raise RuntimeError("Browser no iniciado. Usa el context manager.")
        page = self._context.new_page()
        page.set_default_timeout(self.timeout * 1000)
        return page

    @abstractmethod
    def scrape(self) -> list[Job]:
        """
        Scrapea empleos de la fuente.
        
        Returns:
            Lista de objetos Job
        """
        pass

    def run(self) -> tuple[int, int]:
        """
        Ejecuta el scraping con logging de runs.
        
        Returns:
            (jobs_nuevos, jobs_duplicados)
        """
        from db.storage import bulk_insert_jobs, is_duplicate

        run_id = log_run_start(self.db_path, self.source_name)
        jobs_found = 0
        jobs_new = 0

        try:
            jobs = self.scrape()
            jobs_found = len(jobs)
            
            # Filtrar duplicados antes de insertar
            unique_jobs = []
            for job in jobs:
                if not is_duplicate(self.db_path, job.url):
                    unique_jobs.append(job)
                else:
                    logger.debug("[%s] Duplicado descartado: %s", self.source_name, job.title)

            jobs_new, jobs_dupes = bulk_insert_jobs(self.db_path, unique_jobs)
            log_run_end(self.db_path, run_id, jobs_found, jobs_new, "success")
            return jobs_new, jobs_dupes

        except Exception as e:
            logger.exception("[%s] Error en scraping: %s", self.source_name, e)
            log_run_end(self.db_path, run_id, 0, 0, "error", str(e))
            raise