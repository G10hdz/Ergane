"""
ergane/filters/rules.py
Filtrado por reglas explícitas: regex + keywords.
Retorna score 0.0-1.0 o 0.0 si exclusión dura aplica.

Profile-aware: score_job/seniority_score/company_score accept an optional
UserProfile. When provided, profile fields override the module-level defaults
below (positive stack, blacklists, max years of experience, etc.).
"""
import logging
import re
from typing import TYPE_CHECKING, Dict, List, Optional

from db.models import Job

if TYPE_CHECKING:
    from profiles import UserProfile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

# Stack positivo (suma puntos)
POSITIVE_STACK = {
    "python": 0.15,
    "aws": 0.15,
    "terraform": 0.12,
    "docker": 0.10,
    "kubernetes": 0.10,
    "k8s": 0.10,
    "langchain": 0.12,
    "fastapi": 0.10,
    "flask": 0.08,
    "django": 0.08,
    "machine learning": 0.10,
    "ml": 0.08,
    "mlops": 0.12,
    "devops": 0.10,
    "cloud": 0.08,
    "serverless": 0.08,
    "lambda": 0.08,
    "ci/cd": 0.08,
    "github actions": 0.08,
    "airflow": 0.08,
    "data engineering": 0.10,
    "llm": 0.12,
    "ai": 0.10,
    "rag": 0.10,
    "agents": 0.10,
}

# Exclusiones duras - EMPTY (no automatic exclusions)
# Let user evaluate all opportunities manually
HARD_EXCLUSIONS = []

# Roles junior falsos (prometen junior pero piden senior)
# Only trigger when title explicitly says junior AND description asks for senior-level experience
FAKE_JUNIOR_TITLE_PATTERNS = [
    r"\bjunior\b",
    r"\bjr\.?\b",
]

FAKE_JUNIOR_DESC_PATTERNS = [
    r"\b5\+?\s*(años|years?)\b",
    r"\b(sr\.?|senior)\s+(engineer|developer|consultant|analyst)\b",
    r"\b(staff|principal|lead|head)\s+(engineer|developer|consultant)\b",
]

# Salary mínimo aceptable (MXN brutos/mes)
MIN_SALARY_ACCEPTABLE = 30000

# Máximo años de experiencia aceptables por default (0 = sin límite).
# Los perfiles pueden overridear con profile.max_years_experience.
MAX_YEARS_EXPERIENCE_JR = 0

# Títulos relevantes por default (cuando el perfil no define relevant_titles).
DEFAULT_RELEVANT_TITLES = [
    "devops",
    "cloud",
    "mlops",
    "machine learning",
    "ml",
    "ai",
    "data engineer",
    "backend",
    "python",
    "platform",
    "infrastructure",
    "sre",
    "site reliability",
]

# ---------------------------------------------------------------------------
# Seniority scoring — penalización por fake junior
# ---------------------------------------------------------------------------

SENIORITY_EXPERIENCE_PATTERNS = [
    r"\b5\+?\s*(años|years?)\b",
    r"\b6\s*años\b",
    r"\b7\s*años\b",
    r"\b7\+?\s*years?\b",
    r"\b5\+?\s*years?\b",
    r"\b6\+?\s*years?\b",
]

SENIORITY_LEVEL_PATTERNS = [
    r"\bsenior\b",
    r"\blead\b",
    r"\bstaff\b",
    r"\bprincipal\b",
    r"\barchitect\b",
    r"\bhead\s+of\b",
]

SENIORITY_RESPONSIBILITY_PATTERNS = [
    r"\bmanage\s+(a\s+)?team\b",
    r"\bliderar\s+equipo\b",
    r"\bliderar\s+equipos\b",
    r"\bdirect\s+reports\b",
    r"\breports\b.*\bmanage\b",
]

# ---------------------------------------------------------------------------
# Company scoring — blacklist + whitelist
# ---------------------------------------------------------------------------

STAFFING_BLACKLIST = {
    "manpower", "adecco", "randstad", "kelly", "hays", "robert half",
    "experis", "pagegroup", "michael page", "softtek", "neoris",
    "infosys", "wipro", "tcs", "cognizant", "stefanini",
}

STARTUP_WHITELIST = {
    "clip", "konfío", "konfio", "kueski", "bitso", "conekta", "rappi",
    "truora", "flat.mx", "flat", "jüsto", "justo", "clara", "palenca",
}


# ---------------------------------------------------------------------------
# Helpers de resolución profile vs. defaults
# ---------------------------------------------------------------------------

def _cfg_positive_stack(profile: Optional["UserProfile"]) -> Dict[str, float]:
    if profile and profile.positive_stack:
        return profile.positive_stack
    return POSITIVE_STACK


def _cfg_hard_exclusions(profile: Optional["UserProfile"]) -> List[str]:
    if profile and profile.hard_exclusions:
        return profile.hard_exclusions
    return HARD_EXCLUSIONS


def _cfg_relevant_titles(profile: Optional["UserProfile"]) -> List[str]:
    if profile and profile.relevant_titles:
        return profile.relevant_titles
    return DEFAULT_RELEVANT_TITLES


def _cfg_min_salary(profile: Optional["UserProfile"]) -> int:
    if profile:
        if profile.rules_min_salary_mxn:
            return profile.rules_min_salary_mxn
        if profile.min_salary_mxn:
            return profile.min_salary_mxn
    return MIN_SALARY_ACCEPTABLE


def _cfg_max_years(profile: Optional["UserProfile"]) -> int:
    if profile is not None:
        return profile.max_years_experience
    return MAX_YEARS_EXPERIENCE_JR


def _cfg_company_blacklist(profile: Optional["UserProfile"]) -> set:
    if profile and profile.company_blacklist:
        return {c.lower() for c in profile.company_blacklist}
    return STAFFING_BLACKLIST


def _cfg_company_whitelist(profile: Optional["UserProfile"]) -> set:
    if profile and profile.company_whitelist:
        return {c.lower() for c in profile.company_whitelist}
    return STARTUP_WHITELIST


# ---------------------------------------------------------------------------
# Funciones principales
# ---------------------------------------------------------------------------

def score_job(job: Job, profile: Optional["UserProfile"] = None) -> float:
    """
    Scorea un job según reglas explícitas.

    Args:
        job: Job a evaluar.
        profile: Perfil de usuario opcional. Si se provee, sus campos
            (positive_stack, hard_exclusions, max_years_experience, etc.)
            sobrescriben los defaults del módulo.

    Retorna:
        0.0 si cualquier exclusión dura aplica
        0.0-1.0 basado en stack match y otros factores
    """
    # 1. Check exclusiones duras
    if _is_hard_excluded(job, profile):
        logger.debug("[%s] Excluido duro: %s @ %s", job.source, job.title, job.company)
        return 0.0

    # 2. Check salario (si visible)
    min_salary = _cfg_min_salary(profile)
    if job.salary_min and min_salary and job.salary_min < min_salary:
        logger.debug("[%s] Salario muy bajo: %d < %d", job.source, job.salary_min, min_salary)
        return 0.0

    # 3. Check fake junior
    if _is_fake_junior(job):
        logger.debug("[%s] Fake junior: %s", job.source, job.title)
        return 0.0

    # 4. Calcular score positivo
    score = _calculate_positive_score(job, profile)

    # 5. Bonus por remoto
    if job.remote:
        score += 0.05

    # 6. Bonus por título relevante
    if _is_relevant_title(job.title, profile):
        score += 0.10

    # Clamp a 1.0
    score = min(score, 1.0)

    logger.debug(
        "[%s] Score %.2f para: %s @ %s",
        job.source, score, job.title, job.company,
    )

    return score


def _is_hard_excluded(job: Job, profile: Optional["UserProfile"] = None) -> bool:
    """
    Verifica si el job está en exclusiones duras o excede el límite
    de años de experiencia configurado para el perfil.
    """
    text_to_check = " ".join([
        job.title.lower(),
        (job.company or "").lower(),
        (job.description or "").lower(),
    ])

    for exclusion in _cfg_hard_exclusions(profile):
        if exclusion.lower() in text_to_check:
            return True

    if _exceeds_experience_limit(job, profile):
        logger.debug("[%s] Excluido por exceso de experiencia: %s @ %s",
                    job.source, job.title, job.company)
        return True

    return False


# ---------------------------------------------------------------------------
# Años de experiencia
# ---------------------------------------------------------------------------

_YEARS_PATTERNS = [
    r"(\d+)\+?\s*años?\s*de\s*experiencia",
    r"(\d+)\+?\s*años?\s*experience",
    r"(\d+)\+?\s*years?\s*of\s*experience",
    r"(\d+)\+?\s*years?\s*experience",
    r"mínimo\s*(\d+)\s*años?",
    r"minimum\s*(\d+)\s*years?",
    r"requiere\s*(\d+)\s*años?",
    r"requires\s*(\d+)\s*years?",
]


def _extract_years_experience(text: str) -> Optional[int]:
    """Extrae el máximo de años de experiencia requeridos del texto."""
    max_years = 0
    for pattern in _YEARS_PATTERNS:
        for match in re.findall(pattern, text, re.IGNORECASE):
            try:
                max_years = max(max_years, int(match))
            except ValueError:
                continue
    return max_years if max_years > 0 else None


def _exceeds_experience_limit(job: Job, profile: Optional["UserProfile"] = None) -> bool:
    """True si el job pide más años de los que el perfil acepta. 0 = sin límite."""
    max_years = _cfg_max_years(profile)
    if max_years <= 0:
        return False

    if not job.description:
        return False

    years = _extract_years_experience(job.description.lower())
    if years is not None and years > max_years:
        logger.debug("[%s] Excede límite: %d años > %d años máximo",
                    job.source, years, max_years)
        return True

    return False


def _is_fake_junior(job: Job) -> bool:
    """
    Detecta jobs que dicen ser junior pero piden experiencia senior.
    Only triggers when title says junior AND description has senior-level requirements.
    """
    title_lower = job.title.lower()
    desc_lower = (job.description or "").lower()

    # Title must mention junior
    title_is_junior = any(re.search(p, title_lower) for p in FAKE_JUNIOR_TITLE_PATTERNS)
    if not title_is_junior:
        return False

    # Description must have senior-level signals
    return any(re.search(p, desc_lower) for p in FAKE_JUNIOR_DESC_PATTERNS)


def _calculate_positive_score(job: Job, profile: Optional["UserProfile"] = None) -> float:
    """
    Calcula score positivo basado en stack match.
    """
    stack = _cfg_positive_stack(profile)
    score = 0.0

    text_to_check = " ".join([
        job.title.lower(),
        (job.description or "").lower(),
        " ".join(job.tags).lower(),
    ])

    matches_count = 0
    for skill, points in stack.items():
        if skill.lower() in text_to_check:
            score += points
            matches_count += 1

    # Bonus por múltiples matches (sinergias)
    if matches_count >= 5:
        score += 0.10

    return score


def _is_relevant_title(title: str, profile: Optional["UserProfile"] = None) -> bool:
    """Verifica si el título matchea alguna palabra clave relevante del perfil."""
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in _cfg_relevant_titles(profile))


def filter_jobs(
    jobs: list[Job],
    min_score: float = 0.4,
    profile: Optional["UserProfile"] = None,
) -> list[Job]:
    """
    Filtra y scorea una lista de jobs usando las reglas del perfil (o defaults).

    Returns:
        Lista de jobs con score >= min_score, ordenados por score DESC
    """
    scored_jobs = []

    for job in jobs:
        score = score_job(job, profile)
        if score >= min_score:
            job.score = score
            scored_jobs.append(job)

    scored_jobs.sort(key=lambda j: j.score, reverse=True)

    logger.info(
        "Filtrado: %d jobs -> %d aprobados (score >= %.2f)",
        len(jobs), len(scored_jobs), min_score,
    )

    return scored_jobs


# ---------------------------------------------------------------------------
# Seniority score — detecta fake junior
# ---------------------------------------------------------------------------

def seniority_score(job: Job, profile: Optional["UserProfile"] = None) -> float:
    """
    Detecta jobs que parecen junior pero piden nivel senior.
    Retorna 1.0 si ningún patrón aplica, reducido por penalizaciones.

    Penalizaciones:
    - -0.3 si description pide 5+ años, nivel senior, o responsabilidades de lead
    - -0.2 adicional si salary > 60k y título dice Jr/Junior
    """
    score = 1.0
    desc_lower = (job.description or "").lower()
    title_lower = job.title.lower()

    # Check experiencia: 5+ años
    if any(re.search(p, desc_lower) for p in SENIORITY_EXPERIENCE_PATTERNS):
        score -= 0.3

    # Check nivel senior
    if any(re.search(p, desc_lower) for p in SENIORITY_LEVEL_PATTERNS):
        score -= 0.3

    # Check responsabilidades senior
    if any(re.search(p, desc_lower) for p in SENIORITY_RESPONSIBILITY_PATTERNS):
        score -= 0.3

    # Penalización adicional: salary alto + título junior
    if job.salary_min and job.salary_min > 60000:
        if re.search(r"\b(jr\.?|junior)\b", title_lower):
            score -= 0.2

    return max(score, 0.0)


# ---------------------------------------------------------------------------
# Company score — blacklist staffing + whitelist startups
# ---------------------------------------------------------------------------

def company_score(job: Job, profile: Optional["UserProfile"] = None) -> float:
    """
    Score basado en empresa.

    - 0.1 si es staffing/outsourcing (blacklist del perfil o default)
    - 0.9 si es startup/consultora tech conocida (whitelist del perfil o default)
    - 0.5 default (desconocida)
    """
    company_lower = (job.company or "").lower().strip()

    if not company_lower:
        return 0.5

    for banned in _cfg_company_blacklist(profile):
        if banned in company_lower:
            return 0.1

    for preferred in _cfg_company_whitelist(profile):
        if preferred in company_lower:
            return 0.9

    return 0.5


# ---------------------------------------------------------------------------
# Ambiguity detection — flag culture/values-heavy postings
# ---------------------------------------------------------------------------

def detect_ambiguity(job: Job) -> dict:
    """
    Detect if a job posting is culture/values-heavy instead of skills-specific.

    These postings often get low keyword scores but might still be worth
    investigating. Returns metadata to flag them for manual review.

    Returns:
        dict with keys:
        - is_ambiguous: bool
        - reason: str explanation
        - confidence: float 0.0-1.0
    """
    desc = (job.description or "").lower()
    title = (job.title or "").lower()
    text = title + " " + desc

    if not desc or len(desc) < 50:
        return {"is_ambiguous": False, "reason": "", "confidence": 0.0}

    # Signals of culture/values-heavy postings (English + Spanish)
    soft_skill_keywords = [
        "ownership", "proactive", "self-motivated", "self-starter",
        "team player", "passion", "passionate", "enthusiastic",
        "fast-paced", "dynamic", "exciting", "amazing",
        "work-life balance", "flexible", "autonomy", "autonom",
        "problem solver", "problem-solving", "critical thinking",
        "communication skills", "leadership", "mentor", "collaborat",
        "culture", "values", "mindset", "attitude", "grit",
        "hustle", "drive", "motivat", "initiative",
        "hace la diferencia", "criterio", "hacerse cargo",
        "proactiv", "resolutiv", "excelencia",
        "problemas del negocio", "resolver problemas", "buen criterio",
        "sin burocracia", "impacto real", "crecer rápido",
        "autonomía", "criterio técnico", "ambigüedad",
    ]

    # Concrete technical signals — use word-boundary matching for accuracy
    tech_skill_list = list(POSITIVE_STACK.keys()) + [
        "sql", "nosql", "postgres", "mysql", "mongodb", "redis",
        "react", "angular", "vue", "typescript", "javascript", "java",
        "go", "golang", "rust", "c\\+\\+", "c#", "\\.net", "ruby",
        "elixir", "erlang", "scala", "kotlin", "swift", "dart",
        "flutter", "spring", "graphql", "rest", "microservice",
        "git", "agile", "scrum", "kanban",
        "api", "backend", "frontend", "fullstack", "full-stack",
        "years of experience", "años de experiencia", "bachelor",
        "degree", "computer science", "ingeniería", "licenciatura",
    ]

    # Count soft signals (substring match — intentional for phrases)
    soft_matches = sum(1 for kw in soft_skill_keywords if kw in text)

    # Count tech signals (word-boundary regex to avoid false positives)
    tech_matches = 0
    for pattern in tech_skill_list:
        if re.search(r'\b' + pattern + r'\b', text, re.IGNORECASE):
            tech_matches += 1

    # Heuristics for ambiguity
    total_signals = soft_matches + tech_matches
    if total_signals == 0:
        return {
            "is_ambiguous": True,
            "reason": "Posting has almost no technical or cultural signals",
            "confidence": 0.9,
        }

    soft_ratio = soft_matches / total_signals if total_signals > 0 else 0

    # Flag when soft signals dominate AND tech mentions are sparse (< 5)
    # Culture-heavy postings often mention 1-3 technologies but focus on values
    is_ambiguous = soft_ratio > 0.5 and tech_matches < 5
    confidence = min(soft_ratio, 0.95)

    if is_ambiguous:
        reason = (
            f"Culture/values-focused posting ({soft_matches} soft signals, "
            f"only {tech_matches} technical). Score may underestimate fit."
        )
    else:
        reason = ""

    return {
        "is_ambiguous": is_ambiguous,
        "reason": reason,
        "confidence": confidence,
    }
