# 🚀 Ergane - Automated Job Search Assistant

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-blue)](https://core.telegram.org/bots)

**English** | [Español](#-ergane---asistente-automatizado-para-búsqueda-de-empleo)

---

## 📖 Overview

Ergane is an intelligent, multi-user job search automation tool designed for the Mexican/LATAM market. It continuously scrapes job boards, matches opportunities against user profiles using AI-powered scoring, and sends personalized notifications via Telegram. Generate tailored CVs and cover letters in Word format with a single command.

### ✨ Key Features

- **🤖 AI-Powered Matching** — Multi-dimensional scoring: profile skills (40%) + rules (25%) + seniority (20%) + company fit (15%)
- **👥 Multi-User Profiles** — Support multiple users with individual skills, preferences, and Telegram notifications
- **📱 Advanced Telegram Bot** — `/review`, `/generate_cv`, `/applied`, `/pending`, `/stats`, `/interview` commands
- **📄 CV Generation** — Auto-generate tailored CVs + cover letters as Word documents using Claude API
- **🏢 Target Companies** — Direct scraping from 33+ curated companies (automatic ATS detection)
- **📊 ATS Scanner** — Resume-to-JD matching analysis with keyword extraction and recommendations
- **🔄 Automated Scheduling** — Runs periodically (default: every 6 hours)
- **🌐 Multi-Source Scraping** — 9+ sources: OCC, CompuTrabajo, TechJobsMX, GetOnBrd, Himalayas, WeWorkRemotely, Target Companies, LinkedIn Posts, Generic Scraper
- **🎯 Smart Filtering** — Detects fake junior jobs, scores company fit, filters staffing agencies
- **🖥️ Web Dashboard** — Visual job tracking, profile management, and application analytics

---

## 🏗️ Architecture

```
┌──────────────────────┐     ┌────────────────────────┐
│   Scrapers (9+)      │────▶│  Multi-Dimensional     │
│  • Job Boards (6)    │     │  Scoring Engine        │
│  • Target Companies  │     │  • Profile Match (40%) │
│  • Generic Scraper   │     │  • Rules (25%)         │
│  • LinkedIn Posts    │     │  • Seniority (20%)     │
└──────────────────────┘     │  • Company Fit (15%)   │
                             └────────────────────────┘
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         ▼                            ▼                            ▼
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│  User Profiles  │     │  Application Tracker │     │  Telegram Bot   │
│  (YAML configs) │     │  (applied, pending,  │     │  • Notifications│
│  • Skills       │     │   interviews)        │     │  • Commands     │
│  • Preferences  │     └──────────────────────┘     │  • CV Gen       │
└─────────────────┘              │                   └─────────────────┘
         │                       │                            │
         └───────────────────────┼────────────────────────────┘
                                 ▼
                        ┌─────────────────┐
                        │  SQLite DB      │
                        │  • Jobs         │
                        │  • Tracking     │
                        │  • Run History  │
                        └─────────────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │  Web Dashboard  │
                        │  • Jobs View    │
                        │  • Profile Mgmt │
                        │  • Analytics    │
                        └─────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+**
- **Telegram Bot Token** (from [@BotFather](https://t.me/BotFather))
- **Anthropic API Key** (optional, for CV generation)
- **Ollama** (optional, for local semantic scoring)

### Installation

```bash
# Clone the repository
git clone https://github.com/G10hdz/Ergane.git
cd Ergane

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your credentials
```

### Configuration

Edit `.env` file:

```bash
# Required
TELEGRAM_BOT_TOKEN=your_bot_token_here      # From @BotFather
TELEGRAM_CHAT_ID=your_chat_id_here          # From @userinfobot (default user)

# Optional (recommended)
ANTHROPIC_API_KEY=sk-ant-your-key-here      # For CV generation
ERGANE_MIN_SCORE=0.4                        # Minimum match score (0-1)
ERGANE_SCHEDULE_HOURS=6                     # How often to run scraper

# Optional (ATS Scanner)
ERGANE_ATS_ENABLED=false                    # Enable ATS resume-JD matching

# Optional (local AI)
ERGANE_OLLAMA_ENABLED=true
ERGANE_OLLAMA_URL=http://localhost:11434
ERGANE_OLLAMA_MODEL=qwen2.5-coder:7b
```

### Multi-User Setup

Create individual profiles in `profiles/` directory:

```yaml
# profiles/yourname.yaml
name: yourname
enabled: true

skills:
  python: 0.20      # High priority skills
  aws: 0.18
  docker: 0.10      # Medium priority
  git: 0.05         # Nice to have

preferences:
  min_salary_mxn: 30000
  remote_preferred: true
  locations:
    - Mexico
    - CDMX
    - Remote

telegram:
  chat_id: "your_chat_id"  # From @userinfobot

min_score: 0.15  # Notification threshold
```

Copy `profiles/template.yaml` as a starting point.

### First Run

```bash
# Test run (single execution)
python main.py --once

# Start scheduler (runs continuously)
python main.py

# View statistics
python main.py --stats
```

### Web Dashboard

```bash
# Install web app dependencies
cd web
npm install
npm run dev

# Open http://localhost:5173
```

The web dashboard provides:
- **Jobs View** — Browse all scraped jobs with scores and filters
- **Applications** — Track applied, pending, and interviewed jobs
- **Profiles** — Manage user profiles and skill weights
- **Analytics** — Pipeline metrics, source performance, score distribution

---

## 📱 Telegram Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and available commands |
| `/review <job_url>` | Analyze job match with your profile |
| `/generate_cv <job_url>` | Generate tailored CV + cover letter |
| `/applied <job_url> [notes]` | Mark job as applied |
| `/pending` | Show high-priority jobs you haven't applied to |
| `/stats` | View application statistics |
| `/interview <job_url> [notes]` | Mark job as interview scheduled |
| `/help` | Show help message |

---

## 🛠️ Supported Job Sources

| Source | Type | Region | Avg Jobs/Run |
|--------|------|--------|--------------|
| **GetOnBrd** | Job Board | LATAM | ~130 jobs |
| **TechJobsMX** | Job Board | Mexico | ~50 jobs |
| **LinkedIn Posts** | Social | Global | Varies |
| **Generic Scraper** | Custom | Any | Configurable |
| **Target Companies** | Direct Scraping | Global | Varies |
| **Himalayas** | Job Board | Remote | ~20 jobs |
| **WeWorkRemotely** | Job Board | Remote | ~80 jobs |
| **OCC** | Job Board | Mexico | ~20 jobs |
| **CompuTrabajo** | Job Board | Mexico | ~40 jobs |

### Target Companies (33 curated)

Direct scraping from company career pages with automatic ATS detection:

**Mexican Fintech/Tech:** Clip, Konfío, Kueski, Bitso, Conekta, Rappi, Truora, Flat.mx, Clara, Palenca

**AI/ML Leaders:** Hugging Face, LangChain, Databricks, Cohere, Anthropic, Scale AI, Weights & Biases

**Cloud/Infrastructure:** Red Hat, Canonical, GitLab, NVIDIA, Cloudflare, DigitalOcean, Fastly

---

## 📊 Scoring System

Ergane uses a **multi-dimensional scoring system** (0-1 scale):

| Component | Weight | Description |
|-----------|--------|-------------|
| **Profile Skills** | 40% | Matches job description against weighted skills |
| **Rules** | 25% | Explicit keyword filtering and exclusions |
| **Seniority** | 20% | Detects fake junior jobs, experience level |
| **Company Fit** | 15% | Boosts startups, penalizes staffing agencies |

### Thresholds

- **0.70+** - High priority (🔥 in notifications, re-notify after 3 days)
- **0.40+** - Notification threshold (worth reviewing)
- **0.15+** - Stored in database

---

## 📄 CV Generation

Ergane uses **Claude Sonnet** API for high-quality CV generation:

- **Input**: Job description + base CV template
- **Output**: Tailored CV + cover letter in Markdown + Word (.docx)
- **Cost**: ~$0.03-0.04 per generation
- **Time**: ~20-30 seconds per CV

---

## 🧪 Testing

```bash
# Run full test suite
pytest

# Run specific test modules
pytest tests/test_ats_scanner.py
pytest tests/test_rules_extended.py
pytest tests/test_target_companies.py
```

---

## 📁 Project Structure

```
ergane/
├── main.py                    # Entry point
├── scheduler.py               # Job scheduler with multi-user support
├── requirements.txt           # Python dependencies
├── .env.example              # Environment template
├── target_companies.yaml     # 33 curated companies
│
├── web/                      # React + Vite dashboard
│   ├── src/
│   │   ├── components/       # UI components
│   │   ├── pages/            # Dashboard pages
│   │   └── services/         # API client
│   └── package.json
│
├── db/                       # Database layer
├── profiles/                 # User profile configurations
├── scrapers/                 # Job source scrapers
├── filters/                  # Scoring, CV generation, ATS
├── notifier/                 # Telegram bot
└── tests/                    # Test suite
```

---

## 🔒 Security

- **Never commit `.env` file** — Contains sensitive API keys
- **Use environment variables** for all credentials
- **Rate limiting** — Built-in delays to avoid IP bans
- **Singleton lock** — Prevents duplicate bot instances

---

## 📝 License

MIT License — see [LICENSE](LICENSE) file.

---

## 🙋 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

---

# 🚀 Ergane - Asistente Automatizado para Búsqueda de Empleo

[Español](#-ergane---asistente-automatizado-para-búsqueda-de-empleo) | **English**

## 📖 Descripción General

Ergane es una herramienta inteligente de automatización para búsqueda de empleo diseñada para el mercado mexicano/latinoamericano. Escanea continuamente bolsas de trabajo, compara oportunidades con tu perfil usando IA, y envía notificaciones personalizadas vía Telegram. Genera CVs y cartas de presentación personalizadas en formato Word con un solo comando.

### ✨ Características Principales

- **🤖 Matching con IA** — Puntuación multidimensional: perfil skills (40%) + reglas (25%) + seniority (20%) + empresa (15%)
- **👥 Perfiles Multi-Usuario** — Soporta múltiples usuarios con habilidades y preferencias individuales
- **📱 Bot de Telegram Avanzado** — Comandos `/applied`, `/pending`, `/stats`, `/interview`, `/review`, `/generate_cv`
- **📄 Generación de CV** — Auto-genera CVs + cartas de presentación como documentos Word usando Claude API
- **🏢 Empresas Target** — Scraping directo de 33+ empresas curadas
- **📊 Scanner ATS** — Análisis de matching CV-a-JD con recomendaciones
- **🔄 Programación Automática** — Ejecuta periódicamente (default: cada 6 horas)
- **🌐 Scraping Multi-Fuente** — 9+ fuentes
- **🖥️ Dashboard Web** — Seguimiento visual de empleos, gestión de perfiles y analíticas

### Instalación

```bash
git clone https://github.com/G10hdz/Ergane.git
cd Ergane
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your credentials
python main.py --once
```

### Dashboard Web

```bash
cd web && npm install && npm run dev
# Open http://localhost:5173
```

### Licencia

MIT License — ver [LICENSE](LICENSE)
