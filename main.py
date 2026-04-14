"""
ergane/main.py
Entry point for Ergane job scraper.

Usage:
    python main.py           - Start scheduler (runs forever)
    python main.py --once    - Run pipeline once and exit (debug)
    python main.py --stats   - Print stats and exit
"""
import argparse
import atexit
import fcntl
import logging
import os
import sys
import tempfile
import time

from dotenv import load_dotenv

# Load .env ASAP before project imports
load_dotenv()

from db.storage import get_stats
from scheduler import run_pipeline, start_scheduler, stop_scheduler
from notifier.telegram import start_bot as start_telegram_bot

# ---------------------------------------------------------------------------
# Configure logging
# ---------------------------------------------------------------------------

LOG_LEVEL = os.getenv("ERGANE_LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Singleton lock — prevent duplicate Ergane processes
# ---------------------------------------------------------------------------

_LOCK_PATH = os.path.join(tempfile.gettempdir(), "ergane.lock")
_lock_fp = None


def acquire_singleton_lock() -> bool:
    """Acquire an exclusive OS-level lock. Returns False if another instance holds it."""
    global _lock_fp
    _lock_fp = open(_LOCK_PATH, "w")
    try:
        fcntl.flock(_lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    _lock_fp.write(str(os.getpid()))
    _lock_fp.flush()
    atexit.register(_release_singleton_lock)
    return True


def _release_singleton_lock() -> None:
    global _lock_fp
    if _lock_fp is not None:
        try:
            fcntl.flock(_lock_fp.fileno(), fcntl.LOCK_UN)
            _lock_fp.close()
        except Exception:
            pass
        _lock_fp = None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="ergane",
        description="Ergane - Automated job scraper for Mexico",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py           Start scheduler (runs every 6 hours)
  python main.py --once    Run pipeline once (debug mode)
  python main.py --stats   Show database statistics
        """,
    )
    
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run pipeline once and exit (debug mode)",
    )
    
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print database statistics and exit",
    )
    
    return parser.parse_args()


def print_stats() -> None:
    """Print database statistics."""
    db_path = os.getenv("ERGANE_DB_PATH", "./ergane.db")
    
    try:
        stats = get_stats(db_path)
    except Exception as e:
        logger.error("Failed to get stats: %s", e)
        print(f"Error: {e}")
        return
    
    print("\n" + "=" * 50)
    print("📊 Ergane Statistics")
    print("=" * 50)
    print(f"Total jobs:     {stats['total']}")
    print(f"Notified:       {stats['notified']}")
    print(f"Pending:        {stats['pending']}")
    print("\nBy source:")
    for source, count in stats.get("by_source", {}).items():
        print(f"  {source}: {count}")
    print("=" * 50 + "\n")


def main() -> int:
    """
    Main entry point.
    
    Returns:
        Exit code (0 for success, 1 for error)
    """
    args = parse_args()

    logger.info("Ergane starting...")

    if not args.stats and not args.once:
        if not acquire_singleton_lock():
            logger.error("Another Ergane instance is already running (lock: %s). Exiting.", _LOCK_PATH)
            return 1

    try:
        if args.stats:
            # Print stats and exit
            print_stats()
            return 0
        
        elif args.once:
            # Run once and exit (debug mode)
            logger.info("Running pipeline once (debug mode)...")
            run_pipeline()
            logger.info("Pipeline completed")
            return 0
        
        else:
            # Start scheduler (background)
            logger.info("Starting scheduler...")
            start_scheduler()

            # Start Telegram bot in main thread (runs forever)
            logger.info("Starting Telegram bot (blocks main thread)...")
            start_telegram_bot()
            return 0
                
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
        stop_scheduler()
        return 0
    
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        stop_scheduler()
        return 1


if __name__ == "__main__":
    sys.exit(main())
