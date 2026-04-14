# Ergane — Job Search Automation Tool
**Positronica Labs** | Cloud & Automation Engineer tooling para job search en CDMX/LatAm
**Repo:** github.com/G10hdz/Ergane (privado)
**Última actualización:** 2026-04-09

---

## Contexto del proyecto

Sistema agéntico end-to-end que scrapea vacantes tech en México, las filtra según el perfil
de la usuaria, genera CVs personalizados en Word y notifica por Telegram con resumen accionable.

**Perfil target (Mayte):**
- Roles: DevOps Jr, Cloud Engineer, MLOps, AI Builder
- Salario mínimo: 30,000 MXN brutos/mes
- Preferencia: startups, consultoras tech — no bancos ni fintech tradicional
- Stack relevante: Python, AWS, Terraform, LangChain, FastAPI, Docker

**Perfil secundario (Jeaneth):**
- Roles: Frontend, React Developer, .NET Developer
- Stack relevante: React, TypeScript, .NET, Next.js

---

## Stack

- Python 3.11+
- Playwright (scraping dinámico)
- Scrapling v0.4.3 (StealthyFetcher)
- requests + BeautifulSoup (fuentes estáticas/API)
- SQLite (almacenamiento local, WAL mode)
- APScheduler (ejecución cada 6h)
- Telegram Bot API via python-telegram-bot
- Claude Sonnet 4.5 API (CV generation + ATS scanner opcional)
- Ollama local opcional (qwen2.5-coder:7b)
- python-docx (generación Word)
- LangChain + LangGraph (job reviewer agent)

**Hardware:** Pop!_OS 24.04, Ryzen 5 5600G, 16GB RAM, RX 6700 XT (12GB VRAM, ROCm)
**Ollama con ROCm:**
```bash
export HSA_OVERRIDE_GFX_VERSION=10.3.0
export HIP_VISIBLE_DEVICES=0
export OLLAMA_LLM_LIBRARY=rocm
ollama serve
```

---

## Reglas del proyecto

- Feature branches siempre, nunca push directo a main
- Credenciales en `.env`, nunca hardcodeadas
- Dependencias en `requirements.txt` con versiones pinneadas
- Tests en `tests/` con pytest
- Logging: stdout + `logs/ergane.log`, sin silent failures
- SQLite: context managers con `timeout=30`
- `load_dotenv()` debe ser la PRIMERA línea de `main.py`
- varlock antes de cualquier push cerca de credenciales

---

## Estructura de archivos

```
ergane/
├── CLAUDE.md
├── README.md                       # bilingüe EN/ES
├── .gitignore
├── .env.example
├── requirements.txt
├── target_companies.yaml           # DONE — 33 empresas curadas
├── main.py                         # DONE — CLI: --once, --stats, scheduler
├── scheduler.py                    # DONE — pipeline multi-perfil completo
├── db/
│   ├── schema.sql                  # DONE — incluye applied, reminded columns
│   ├── models.py                   # DONE — dataclass Job
│   ├── storage.py                  # DONE — CRUD + dedup + run logging
│   └── migrate_tracking.py         # DONE — migration: applied, applied_at, reminded
├── profiles/
│   ├── __init__.py                 # DONE — profile loader + scoring
│   ├── mayte.yaml                  # DONE — 80+ skills, DevOps/MLOps
│   ├── jeaneth.yaml                # DONE — 56 skills, React/TS/.NET
│   └── template.yaml               # DONE — template para nuevos perfiles
├── scrapers/
│   ├── base.py                     # DONE
│   ├── himalayas.py                # DONE — API JSON, 17 jobs/run
│   ├── getonbrd.py                 # DONE — 133 jobs/run
│   ├── techjobsmx.py               # DONE — 53 jobs/run
│   ├── occ.py                      # DONE — 22 jobs/run
│   ├── computrabajo.py             # DONE — 40 jobs/run (bloquea a veces)
│   ├── weworkremotely.py           # DONE — RSS, remote global
│   ├── linkedin_single.py          # DONE — /review command
│   └── target_companies.py         # DONE — TargetCompaniesScraper (33 empresas)
├── filters/
│   ├── rules.py                    # DONE — seniority_score + company_score
│   ├── cv_matcher.py               # DONE — 40+ skills, threshold 0.15
│   ├── scorer.py                   # DONE — hybrid 60% CV + 40% Ollama
│   ├── ats_scanner.py              # DONE — ATS resume scanner
│   └── cv_generator.py             # DONE — Claude Sonnet 4.5, Word output
├── agents/
│   ├── __init__.py
│   └── README.md
├── notifier/
│   └── telegram.py                 # DONE — MarkdownV2, /applied, /pending, /stats, /interview, fcntl.flock singleton
├── cv_output/                      # gitignored
└── tests/
    ├── test_job_reviewer.py        # DONE — 16 tests
    ├── test_ats_scanner.py         # DONE
    ├── test_rules_extended.py      # DONE
    ├── test_target_companies.py    # DONE
    ├── test_storage.py             # TODO
    ├── test_filters.py             # TODO
    └── fixtures/
```

---

## Estado actual — 2026-04-05

### Todo DONE y en repo

**Pipeline completo:**
- 1 scraping pass → scoring por perfil → Telegram independiente por usuario
- Mayte: 185 jobs matched/run | Jeaneth: 120+ jobs matched/run
- 60/60 tests pasando

**Scoring combinado (scheduler.py):**
```python
final_score = (
    0.40 * cv_score +
    0.25 * rules_score +
    0.20 * seniority_score(job) +
    0.15 * company_score(job)
)
```

**Telegram commands:**
- `/applied <job_id>` — marca job como aplicado
- `/pending` — lista jobs score >= 0.8 sin aplicar, ordenados por score
- `/stats` — estadísticas + seguimiento de aplicaciones
- `/interview <job_url>` — genera preguntas de entrevista con Claude API
- `/review` — scraper de LinkedIn single URL

**Notificaciones:**
- 🔥 jobs con score >= 0.8 van primero con aviso de alta prioridad
- ⏰ re-notifica una vez jobs >= 0.7 sin aplicar después de 3 días
- MarkdownV2 escaping correcto (170/170 exitosas)

**Scraper stats:**
| Fuente | Jobs/run | Estado |
|---|---|---|
| GetOnBrd | 133 | Estable |
| TechJobsMX | 53 | Estable |
| CompuTrabajo | 40 | Bloquea ocasionalmente |
| OCC | 22 | Estable |
| Himalayas | 17 | Muy estable (API) |
| WeWorkRemotely | ~30 | Estable (RSS) |
| Target Companies | variable | 33 empresas curadas |

---

## Job Reviewer Agent (filters/job_reviewer.py)

**Integrado en scheduler.py como opcional:**
- Flag `ERGANE_AGENT_ENABLED=true` activa el agente
- Default: `false` (usa scoring existente)
- Requiere Ollama para modo completo

**Modos de operación:**
| Modo | Ollama | sync_obsidian | Tiempo/job |
|------|--------|---------------|------------|
| fast_mode=True | OFF | False | ~70ms |
| fast_mode=False | ON | True | Lento |

**Lazy loading:** LangChain/LangGraph se cargan solo cuando necesario (~500ms ahorro)

---

## Próximos pasos

1. Test pipeline completo post-migration: `python3 main.py --once`
2. Verificar `/pending` y `/applied` en Telegram
3. Agregar más empresas a `target_companies.yaml`
4. `tests/test_storage.py` y `tests/test_filters.py` (únicos TODO)
5. Probar agente con `ERGANE_AGENT_ENABLED=true ERGANE_OLLAMA_ENABLED=true`

---

## Patrones críticos

### Playwright element handles
```python
# ROMPE: Navigate destruye element handles
for card in cards:
    page.goto(card.get_attribute("href"))
    card.inner_text()  # FALLA

# CORRECTO: Extract first, navigate second
card_data = [{"url": c.get_attribute("href"), "title": c.inner_text()} for c in cards]
for data in card_data:
    page.goto(data["url"])
    description = page.inner_text(".job-description")
```

### MarkdownV2 escaping
```python
# SÍ escapar: texto y decimales
f"{score:.2f}".replace(".", "\\.")

# NO escapar: URLs dentro de ()
f"[{escaped_title}](https://url-sin-escapar.com)"
```

### Scrapling v0.4.3
```python
# DEPRECATED:
StealthyFetcher(fetch_timeout=30)
fetcher.configure(...)

# CORRECTO:
fetcher = StealthyFetcher()
page = fetcher.fetch(url, headless=True, timeout=90000)  # ms, no segundos
```

### Claude API model IDs
```python
"claude-sonnet-4-5"   # CVs y ATS scanner
"claude-haiku-4-5"    # NO "claude-3-5-haiku-20241022" (deprecated)
```

### Telegram bot — singleton lock (fcntl.flock)
```python
# El lock usa fcntl.flock a nivel de kernel — auto-released en SIGKILL/OOM
# Lock file: ~/.ergane/telegram_bot.lock
# Si el PID en el lock está muerto → stale lock → unlink + retry
# NO cerrar el handle antes de checkear el PID (handle.close() libera el lock!)

# Leer PID ANTES de abrir con "w" (trunca el archivo!)
old_pid_str = lock_path.read_text().strip() if lock_path.exists() else ""
handle = lock_path.open("w")
# ... fcntl.flock(handle, LOCK_EX | LOCK_NB) ...
# Si falla → check old_pid → os.kill(old_pid, 0) → alive? exit : stale → retry
```

### systemd (producción)
```bash
systemctl --user start ergane-bot.service   # iniciar
systemctl --user restart ergane-bot.service # después de cambios
journalctl --user -u ergane-bot.service -f  # logs en vivo
```

---

## Variables de entorno (.env.example)

```env
ERGANE_DB_PATH=./ergane.db
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ERGANE_MIN_SCORE=0.4
ERGANE_OLLAMA_ENABLED=false
ERGANE_OLLAMA_URL=http://localhost:11434
ERGANE_OLLAMA_MODEL=qwen2.5-coder:7b
ERGANE_AGENT_ENABLED=false
ERGANE_SCHEDULE_HOURS=6
ERGANE_LOG_LEVEL=INFO
ERGANE_ATS_ENABLED=false
ANTHROPIC_API_KEY=
```

---

## Comandos útiles

```bash
# systemd (producción)
systemctl --user status ergane-bot.service
systemctl --user restart ergane-bot.service
journalctl --user -u ergane-bot.service -f

# Pipeline debug (una vez, sin scheduler)
python3 main.py --once

# Stats
python3 main.py --stats

# GPU
ollama ps && rocm-smi

# Tests
pytest tests/ -v

# Debug jobs en DB
python3 -c "
from db.storage import get_connection
with get_connection('./ergane.db') as conn:
    rows = conn.execute(
        'SELECT title, source, score, applied FROM jobs ORDER BY score DESC LIMIT 10'
    ).fetchall()
    for r in rows: print(dict(r))
"
```