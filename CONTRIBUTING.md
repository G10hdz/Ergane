# Contributing to Ergane

Thank you for your interest in contributing to Ergane! This document provides guidelines for contributing to the project.

## 🎯 Ways to Contribute

- **Bug Reports** — Open an issue with steps to reproduce
- **Feature Requests** — Describe the problem you want solved
- **Pull Requests** — Fix bugs or add new features
- **Documentation** — Improve README, add examples, fix typos
- **Scrapers** — Add support for new job boards

## 🛠️ Development Setup

```bash
# Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/Ergane.git
cd Ergane

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install --with-deps chromium

# Run tests
pytest
```

## 📝 Coding Standards

- Follow PEP 8 for Python code
- Use descriptive variable names
- Add docstrings to public functions
- Write tests for new features
- Keep functions under 50 lines when possible

## 🧪 Testing

```bash
# Run full test suite
pytest

# Run specific test file
pytest tests/test_storage.py

# Run with coverage
pytest --cov=.
```

## 📤 Pull Request Process

1. Create a feature branch (`git checkout -b feature/amazing-feature`)
2. Make your changes
3. Run tests and ensure they pass
4. Commit with conventional commit format:
   - `feat: add LinkedIn scraper`
   - `fix: resolve deduplication issue`
   - `docs: update README`
5. Push to your fork and open a PR

## 🏗️ Architecture Overview

Ergane is organized into modules:

- `db/` — Database layer (SQLite operations, schema, migrations)
- `profiles/` — User profile configuration and matching logic
- `scrapers/` — Job source scrapers (Playwright-based)
- `filters/` — Scoring engine, CV generation, ATS scanner
- `notifier/` — Telegram bot for notifications and commands
- `web/` — React + Vite dashboard (optional web interface)

## 💡 Adding a New Scraper

1. Create `scrapers/my_scraper.py`
2. Extend `BaseScraper` from `scrapers/base.py`
3. Implement `scrape()` method
4. Register in `scheduler.py`
5. Add tests in `tests/test_my_scraper.py`

## 🤝 Community

- Be respectful and inclusive
- Help others with questions
- Share your experience using Ergane

## 📜 License

By contributing, you agree that your contributions will be licensed under the MIT License.
