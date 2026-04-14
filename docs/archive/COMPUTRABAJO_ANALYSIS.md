# CompuTrabajo Analysis — 2026-04-03

## Status: ❌ NOT VIABLE for automated scraping

---

## Investigation Summary

### Problem
CompuTrabajo scraper returns **0 jobs** despite successful connection and proper Scrapling configuration.

### Root Cause
After thorough investigation with Playwright inspection:

1. **Site redirects correctly**: `computrabajo.com.mx` → `mx.computrabajo.com` ✓
2. **Page loads successfully**: HTTP 200, proper title ✓
3. **But NO job listings are rendered**: 0 `<article>` tags, 0 job links

### Tested URLs
- ❌ `https://mx.computrabajo.com/trabajo-de-devops-de-informatica-y-telecom?q=devops`
- ❌ `https://mx.computrabajo.com/trabajo-de-python`
- ❌ `https://mx.computrabajo.com/trabajo-de-programador`
- ❌ `https://mx.computrabajo.com/empleos-de-informatica-y-telecom`

**All return: "¡Ups! Parece que no hay ofertas para el empleo que buscas."**

---

## Possible Explanations

### 1. Geo-blocking (Most Likely)
CompuTrabajo may be detecting:
- Datacenter IP ranges
- Headless browser signatures
- Automated traffic patterns
- Missing cookies/session state

**Evidence**: Site loads fine in manual browser but shows no jobs in automation.

### 2. Empty Job Database (Unlikely)
The site could genuinely have no tech jobs in Mexico right now.

**Counter-evidence**: CompuTrabajo is a major job board — very unlikely to have ZERO IT jobs.

### 3. Advanced Anti-Bot Protection
Site may be using:
- Cloudflare Bot Management
- PerimeterX / DataDome
- Custom JavaScript challenges
- Device fingerprinting

**Evidence**: Even with `StealthyFetcher` and proper user-agent, we get no results.

---

## Attempted Fixes

### ✅ Tried
- [x] Scrapling `StealthyFetcher` (anti-detection)
- [x] Playwright headless=True and headless=False
- [x] Proper user-agent rotation
- [x] Network idle wait
- [x] Extended timeouts (60s+)
- [x] Multiple search queries (devops, python, programador, IT general)
- [x] Different URL patterns

### ❌ Not Attempted (Would Require Major Changes)
- [ ] Residential proxy rotation
- [ ] Captcha solving service integration
- [ ] Cookie/session replay from manual browser
- [ ] Selenium with undetected-chromedriver
- [ ] Puppeteer stealth plugin

---

## Recommendation

### ⚠️ **SKIP CompuTrabajo**

**Reasons:**
1. **Not worth the effort** — System already gets 166 jobs/run without it
2. **Anti-bot arms race** — Any fix will be temporary
3. **Better alternatives exist** — GetOnBrd (92 jobs), TechJobsMX (52 jobs), OCC (22 jobs)
4. **Legal/ethical concerns** — Aggressive bot detection suggests TOS violation

### Alternative: Manual Scraping
If CompuTrabajo jobs are critical, consider:
- User reports job URLs via Telegram bot
- Use LinkedIn single scraper pattern for one-off URLs
- No automated batch scraping

---

## Impact Assessment

### Current Performance (Without CompuTrabajo)
- **Total jobs/run**: ~183
- **New jobs/run**: ~166
- **After filters**: 33 jobs
- **Notifications sent**: 10-15/run

### If CompuTrabajo Worked (Estimated)
- **Additional jobs**: +20-40/run
- **After filters**: +5-8 jobs
- **Additional notifications**: +1-2/run

**Conclusion**: **5-10% improvement** — not worth the maintenance burden.

---

## Alternative Solutions

### Option 1: Focus on Working Scrapers ⭐ RECOMMENDED
- GetOnBrd is now primary source (92 jobs)
- TechJobsMX covers Mexican startups (52 jobs)
- OCC for traditional companies (22 jobs)
- Himalayas for remote global (17 jobs)

**Total coverage: Excellent** for DevOps/Cloud/ML roles in CDMX.

### Option 2: Add New Sources
Instead of fixing CompuTrabajo, add:
- **RemoteOK** (already in codebase)
- **Indeed Mexico** (huge job board)
- **Startup.jobs** (startup-focused)
- **AngelList** (tech startups)

### Option 3: Paid API Access
Consider:
- LinkedIn Job Search API (expensive)
- Indeed API (free tier available)
- Glassdoor API
- Job board aggregators

---

## Code Changes

### Remove from Active Scrapers
Update `scheduler.py`:

```python
SCRAPERS = [
    HimalayasScraper,
    GetOnBrdScraper,
    TechJobsMXScraper,
    OCCScraper,
    WeWorkRemotelyScraper,
    # CompuTrabajoScraper,  # DISABLED: Site blocks automation (2026-04-03)
]
```

### Keep Code for Reference
Don't delete `scrapers/computrabajo.py` — may be useful if:
- Site changes anti-bot protection
- We get residential proxy access
- Manual URL scraping is needed

---

## Final Verdict

**Status**: ❌ **Not Worth Fixing**  
**Action**: Comment out in scheduler, document why  
**Future**: Revisit in 6 months or if site changes  
**Priority**: Focus on adding Indeed Mexico instead

---

**Analysis Date**: 2026-04-03  
**Analyst**: Claude (via GitHub Copilot CLI)  
**Test Methods**: Playwright inspection + Scrapling debugging
