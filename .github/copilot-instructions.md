# Ergane — Job Search Automation Tool

Intelligent job scraper for Mexico/LATAM tech market. Scrapes jobs, scores them against a CV using AI, and sends Telegram notifications with tailored CV generation.

---

## Build, Test, and Run Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env
# Edit .env with your credentials

# Run tests
pytest                          # Full test suite
pytest tests/test_storage.py    # Single test file
pytest -k "test_name"          # Single test by name

# Run application
python main.py                  # Start scheduler (runs forever, every 6 hours)
python main.py --once           # Single pipeline run (debug mode)
python main.py --stats          # Display database statistics

# Test scrapers
python test_implementation.py   # Test scraper implementations
python test_playwright.py       # Test Playwright setup

# Test CV generation
python test_cv_word.py          # Test Word CV generation
python test_cv_comparison.py    # Compare Claude models for CV quality
```

---

## Architecture Overview

### Pipeline Flow

```
Scrapers → Rules Filter → CV Matcher → Ollama Scorer → Telegram Notifier
   ↓           ↓              ↓             ↓                ↓
SQLite ←─────────────────────────────────────────────────────┘
```

1. **Scrapers** (`scrapers/`) - Each scraper produces `Job` objects from job boards
2. **Rules Filter** (`filters/rules.py`) - Explicit keyword/salary filters
3. **CV Matcher** (`filters/cv_matcher.py`) - Fast keyword matching (60% weight)
4. **Ollama Scorer** (`filters/scorer.py`) - Semantic LLM analysis (40% weight, optional)
5. **Telegram Bot** (`notifier/telegram.py`) - Sends notifications, handles commands
6. **CV Generator** (`filters/cv_generator.py`) - Creates tailored CVs via Claude API

### Hybrid Scoring System

Jobs are scored on a 0-1 scale:
- **60% CV keyword matching** - Fast, based on weighted skill dictionary
- **40% Ollama semantic scoring** - Slower, deeper understanding (optional)
- Jobs with score ≥ `ERGANE_MIN_SCORE` (default 0.4) trigger notifications

### Data Model

All scrapers produce `Job` dataclass instances (`db/models.py`):

```python
Job(
    url="https://...",           # Required, unique identifier
    title="DevOps Jr",           # Required
    source="occ",                # Required: lowercase, no spaces
    company="Startup MX",        # Optional
    salary_min=30000,            # Optional: MXN brutos/mes (int)
    tags=["Python", "AWS"],      # Optional: list of strings
    remote=True,                 # Optional: boolean
    description="...",           # Optional: for scoring
)
```

### Database Schema

SQLite with WAL mode for concurrency (`db/schema.sql`):

- **jobs** table - Stores scraped jobs with deduplication via `url_hash`
- **runs** table - Logs scraper execution (started_at, jobs_found, status)

Context manager pattern everywhere: `with get_connection(db_path) as conn:`

---

## Key Conventions

### Scraper Pattern

All scrapers inherit from `BaseScraper` (`scrapers/base.py`):

```python
class NewSourceScraper(BaseScraper):
    source_name = "newsource"  # lowercase, no spaces
    
    def scrape(self) -> list[Job]:
        # 1. Use Playwright context (self.page) for dynamic sites
        # 2. Call self._random_sleep() between requests (rate limiting)
        # 3. Return list[Job] objects
        # 4. Don't handle deduplication - storage.py does this
        pass
```

**Important**: Use context manager when running scrapers:

```python
run_id = log_run_start(db_path, "newsource")
try:
    with NewSourceScraper(db_path=db_path) as scraper:
        jobs = scraper.scrape()
        new_count, dupes = bulk_insert_jobs(db_path, jobs)
        log_run_end(db_path, run_id, len(jobs), new_count, "success")
except Exception as e:
    log_run_end(db_path, run_id, 0, 0, "error", str(e))
```

### Playwright Configuration

- **Headless mode** - `True` for production, `False` for debugging
- **User-agent rotation** - Automatically rotated from `USER_AGENTS` list in base.py
- **Rate limiting** - Random sleep 2-5s between requests via `self._random_sleep()`
- **Timeouts** - Use 30s minimum: `page.wait_for_selector(selector, timeout=30000)`

### Environment Variables

All configuration via `.env` file (never hardcode):

```bash
ERGANE_DB_PATH=./ergane.db                    # Database path
TELEGRAM_BOT_TOKEN=...                        # Required for notifications
TELEGRAM_CHAT_ID=...                          # Required for notifications
ANTHROPIC_API_KEY=sk-ant-...                  # Optional, for CV generation
ERGANE_MIN_SCORE=0.4                          # Notification threshold (0-1)
ERGANE_SCHEDULE_HOURS=6                       # Scraper frequency
ERGANE_OLLAMA_ENABLED=true                    # Enable local LLM scoring
ERGANE_OLLAMA_URL=http://localhost:11434     # Ollama endpoint
ERGANE_OLLAMA_MODEL=qwen2.5-coder:7b         # Ollama model
```

### Logging

- **Format**: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- **Level**: Controlled by `ERGANE_LOG_LEVEL` env var (default: INFO)
- **Output**: stdout + `logs/ergane.log`
- **No silent failures** - Always log errors and exceptions

### Git Workflow

- **Feature branches only** - Never push directly to main
- **Branch naming**: lowercase, descriptive (e.g., `fix-techjobsmx-timeout`)
- **Credentials**: Never commit `.env`, check `.gitignore`

### Deduplication Strategy

Use `is_duplicate(db_path, url)` BEFORE scraping job details:

```python
for listing_url in all_listings:
    if is_duplicate(db_path, listing_url):
        continue
    job_details = scrape_job_page(listing_url)  # Expensive operation
    jobs.append(job_details)
```

### CV Matching Skills

CV matcher uses weighted skill dictionary (`filters/cv_matcher.py`):
- **Primary stack** (0.20): Python, AWS, Terraform
- **AI/ML** (0.15-0.10): LangChain, RAG, LLM, MLOps
- **Secondary** (0.08-0.05): FastAPI, Docker, React, SQL
- **Threshold**: 0.15 (configurable in cv_matcher.py)

Match scores are case-insensitive and normalize whitespace.

---

## Telegram Bot Commands

Bot is started via `start_telegram_bot()` in scheduler.py:

- `/start` - Welcome message and command list
- `/review <job_url>` - Analyze job match score with CV
- `/generate_cv <job_url>` - Generate tailored CV + cover letter (Word format)
- `/help` - Show help message

Commands are handled in `notifier/telegram.py`.

---

## Active Scrapers

| Source | File | Status | Notes |
|--------|------|--------|-------|
| OCC | `scrapers/occ.py` | ✅ Active | Static HTML, requests-based |
| CompuTrabajo | `scrapers/computrabajo.py` | ✅ Active | Static HTML, requests-based |
| TechJobsMX | `scrapers/techjobsmx.py` | ✅ Active | Playwright, timeout=30s |
| GetOnBrd | `scrapers/getonbrd.py` | ✅ Active | Playwright (JS-rendered) |
| Himalayas | `scrapers/himalayas.py` | ✅ Active | Remote-first jobs |
| LinkedIn | `scrapers/linkedin_single.py` | ⚠️ Single URLs only | Via `/review` command |
| WeWorkRemotely | `scrapers/weworkremotely.py` | ✅ Active | Remote jobs |

---

## Hardware Context

Running on Pop!_OS with AMD GPU:
- **GPU**: RX 6700 XT (12GB VRAM) with ROCm drivers
- **Ollama**: Localhost at port 11434
- **Default model**: qwen2.5-coder:7b

Verify GPU availability: `ollama ps && rocm-smi`

---

## Common Patterns

### Adding a New Scraper

1. Create `scrapers/newsource.py` extending `BaseScraper`
2. Implement `source_name` (lowercase) and `scrape()` method
3. Add import to `scheduler.py`
4. Add to `SCRAPERS` list in `run_pipeline()`
5. Test with `python main.py --once`

### Adjusting CV Match Weights

Edit `MAYTE_SKILLS` dictionary in `filters/cv_matcher.py`:

```python
MAYTE_SKILLS = {
    "python": 0.20,        # High priority
    "kubernetes": 0.08,    # Medium priority
    "git": 0.05,          # Nice to have
}
```

### Testing Ollama Integration

```bash
# Check if Ollama is running
curl http://localhost:11434/api/generate \
  -d '{"model": "qwen2.5-coder:7b", "prompt": "test"}'

# Verify in Python
python -c "from filters.scorer import score_jobs; print('Ollama OK')"
```

---

## Troubleshooting

### Playwright Timeouts

If scrapers timeout, increase wait time in scraper file:

```python
page.wait_for_selector(selector, timeout=30000)  # 30s minimum
```

### Database Locked Errors

SQLite WAL mode is enabled. If still seeing locks:
- Check for long-running transactions
- Ensure all `with get_connection()` blocks are properly closed
- Verify `timeout=30` in connection string if manually connecting

### Telegram Flood Wait

Built-in handling in `telegram.py`:
- Catches `telegram.error.RetryAfter` exceptions
- Sleeps for required duration + 1s buffer
- Automatically retries after wait

### Ollama Disabled Despite .env=true

Check `load_dotenv()` is FIRST line in `main.py` before any imports.

---

## Project Structure Reference

```
ergane/
├── main.py                  # Entry point, CLI args
├── scheduler.py             # APScheduler pipeline orchestration
├── requirements.txt         # Pinned dependencies
├── .env.example            # Configuration template
│
├── db/
│   ├── schema.sql          # SQLite table definitions
│   ├── models.py           # Job dataclass
│   └── storage.py          # CRUD operations + run logging
│
├── scrapers/
│   ├── base.py             # BaseScraper abstract class
│   ├── occ.py              # OCC.com.mx (static)
│   ├── computrabajo.py     # CompuTrabajo (static)
│   ├── techjobsmx.py       # TechJobsMX (Playwright)
│   ├── getonbrd.py         # GetOnBrd (Playwright)
│   ├── himalayas.py        # Himalayas (remote jobs)
│   ├── weworkremotely.py   # WeWorkRemotely (remote jobs)
│   └── linkedin_single.py  # LinkedIn single URL scraper
│
├── filters/
│   ├── rules.py            # Explicit keyword/salary rules
│   ├── cv_matcher.py       # Fast CV keyword matching (60%)
│   ├── scorer.py           # Ollama semantic scoring (40%)
│   └── cv_generator.py     # Claude API CV generation
│
├── notifier/
│   └── telegram.py         # Bot + notification sender
│
└── tests/
    ├── test_storage.py     # Database tests
    ├── test_filters.py     # Scoring tests
    └── fixtures/           # Test data
```

---

## Security Notes

- **Never commit `.env`** - Contains API keys and tokens
- **Use environment variables** - Never hardcode credentials
- **Private repository recommended** - Contains personal CV data
- **Rate limiting built-in** - Prevents IP bans from job boards
