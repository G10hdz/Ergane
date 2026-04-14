"""
ergane/filters/ats_scanner.py
ATS Resume Scanner — compares job description vs CV text.
Two modes: Claude API (if ERGANE_ATS_ENABLED=true) or regex fallback (default, free).

Inspired by AIApply.co, Beach-Independent AO, and ApplyPilot patterns.
Main insight: "the system's main job is saying no, not spamming yes."
"""
import json
import logging
import os
import re
from difflib import SequenceMatcher
from typing import Optional

from dotenv import load_dotenv

from db.models import Job

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ATS_ENABLED = os.getenv("ERGANE_ATS_ENABLED", "false").lower() == "true"
CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = "claude-sonnet-4-5-20250514"
CLAUDE_TIMEOUT = 30  # seconds

# Spanish + English stopwords for keyword extraction
STOPWORDS = {
    # English
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "don", "now", "about", "also", "like", "make", "way", "work", "team",
    "you", "your", "we", "our", "they", "their", "what", "which", "who",
    "this", "that", "these", "those", "am", "it", "its", "he", "she",
    "but", "and", "or", "if", "while", "because", "although", "though",
    "since", "until", "unless", "whether", "even", "much", "well", "back",
    "still", "already", "really", "quite", "rather", "simply", "actually",
    "looking", "seeking", "join", "role", "position", "opportunity",
    "experience", "skills", "skill", "required", "requirements", "require",
    "preferred", "plus", "nice", "good", "great", "strong", "solid",
    "knowledge", "understanding", "familiar", "ability", "ability",
    "responsible", "responsibilities", "responsibility",
    # Spanish
    "el", "la", "los", "las", "un", "una", "unos", "unas", "es", "son",
    "esta", "este", "estos", "estas", "ese", "esa", "esos", "esas",
    "ese", "esa", "eso", "su", "sus", "mi", "tu", "nos", "les",
    "de", "del", "al", "en", "con", "sin", "por", "para", "sobre",
    "entre", "tras", "hasta", "desde", "hacia", "segun", "como",
    "que", "quien", "cual", "cuales", "donde", "cuando",
    "y", "o", "ni", "pero", "sino", "aunque", "si", "no", "mas",
    "muy", "se", "le", "lo", "les", "la", "las", "me", "te", "nos",
    "buscamos", "busca", "buscar", "ofrecemos", "ofrece", "ofrecer",
    "requerido", "requerida", "requeridos", "requeridas",
    "deseable", "deseables", "deseado", "deseada",
    "experiencia", "conocimiento", "habilidades", "habilidad",
    "puesto", "puesto", "empleo", "trabajo", "empresa", "equipo",
    "area", "departamento", "nivel", "tiempo", "manera", "forma",
    "persona", "personas", "profesional", "profesionales",
}

# Fuzzy matching threshold (0.0-1.0)
FUZZY_THRESHOLD = 0.75


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def score_ats(job: Job, cv_text: str) -> dict:
    """
    Score a job against CV text using ATS-like matching.

    Args:
        job: Job to evaluate
        cv_text: Full CV text content

    Returns:
        {
            "match_score": float (0.0-1.0),
            "missing_keywords": list[str],
            "present_keywords": list[str],
            "recommendation": "apply" | "skip" | "tailor_first"
        }
    """
    if ATS_ENABLED and CLAUDE_API_KEY:
        try:
            return _score_ats_claude(job, cv_text)
        except Exception as e:
            logger.warning("Claude ATS scoring failed, falling back to regex: %s", e)

    return _score_ats_regex(job, cv_text)


# ---------------------------------------------------------------------------
# Claude API mode
# ---------------------------------------------------------------------------

def _score_ats_claude(job: Job, cv_text: str) -> dict:
    """Use Claude API to compare JD vs CV."""
    import anthropic

    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY, timeout=CLAUDE_TIMEOUT)

    jd_text = f"Title: {job.title}\nCompany: {job.company}\n\n{job.description or ''}"

    prompt = (
        "You are an ATS (Applicant Tracking System) scanner. Compare this job description "
        "against this CV and return ONLY a JSON object with these exact fields:\n"
        "- match_score: float from 0.0 to 1.0 (how well the CV matches the job)\n"
        "- missing_keywords: list of important keywords from the job NOT found in the CV\n"
        "- present_keywords: list of important keywords from the job that ARE in the CV\n"
        "- recommendation: one of 'apply', 'skip', or 'tailor_first'\n\n"
        "Focus on technical skills, tools, frameworks, and requirements. "
        "Ignore generic words like 'team player', 'communication', etc.\n\n"
        f"Job Description:\n{jd_text}\n\n"
        f"CV:\n{cv_text}\n\n"
        "Return ONLY valid JSON, no markdown fences, no explanation."
    )

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )

    content = response.content[0].text.strip()
    # Strip markdown fences if present
    content = content.removeprefix("```json").removesuffix("```").strip()

    result = json.loads(content)

    # Validate structure
    assert "match_score" in result
    assert "missing_keywords" in result
    assert "present_keywords" in result
    assert "recommendation" in result

    logger.info(
        "[ATS Claude] %s @ %s — score: %.2f, recommendation: %s",
        job.title, job.company or "Unknown",
        result["match_score"], result["recommendation"],
    )

    return result


# ---------------------------------------------------------------------------
# Regex mode (free, default)
# ---------------------------------------------------------------------------

def _score_ats_regex(job: Job, cv_text: str) -> dict:
    """
    Regex-based ATS scoring using keyword extraction + fuzzy matching.
    """
    cv_lower = cv_text.lower()

    # Extract keywords from job
    keywords = _extract_job_keywords(job)

    if not keywords:
        return {
            "match_score": 0.0,
            "missing_keywords": [],
            "present_keywords": [],
            "recommendation": "skip",
        }

    present = []
    missing = []

    for kw in keywords:
        # Exact match
        if kw.lower() in cv_lower:
            present.append(kw)
            continue

        # Fuzzy match using difflib
        best_ratio = _fuzzy_match(kw.lower(), cv_lower)
        if best_ratio >= FUZZY_THRESHOLD:
            present.append(kw)
        else:
            missing.append(kw)

    match_score = len(present) / len(keywords) if keywords else 0.0

    recommendation = _recommendation(match_score, missing, job)

    logger.info(
        "[ATS Regex] %s @ %s — score: %.2f (%d/%d keywords), recommendation: %s",
        job.title, job.company or "Unknown",
        match_score, len(present), len(keywords), recommendation,
    )

    return {
        "match_score": round(match_score, 3),
        "missing_keywords": missing,
        "present_keywords": present,
        "recommendation": recommendation,
    }


def _extract_job_keywords(job: Job) -> list[str]:
    """Extract meaningful keywords from job title, description, and tags."""
    text_parts = []

    if job.title:
        text_parts.append(job.title)
    if job.description:
        text_parts.append(job.description)
    if job.tags:
        text_parts.append(" ".join(job.tags))

    full_text = " ".join(text_parts).lower()

    # Tokenize: split on non-alphanumeric, keep multi-char tokens
    tokens = re.findall(r'[a-z0-9][a-z0-9.+#]*[a-z0-9]|[a-z0-9]', full_text)

    # Filter: remove stopwords, single chars, numbers-only
    keywords = set()
    for token in tokens:
        if len(token) < 2:
            continue
        if token.isdigit():
            continue
        if token in STOPWORDS:
            continue
        keywords.add(token)

    return sorted(keywords)


def _fuzzy_match(pattern: str, text: str) -> float:
    """Find the best fuzzy match ratio of pattern anywhere in text."""
    if not pattern or not text:
        return 0.0

    best = 0.0
    # Slide pattern-sized windows across text
    window_size = len(pattern)
    for i in range(len(text) - window_size + 1):
        chunk = text[i:i + window_size]
        ratio = SequenceMatcher(None, pattern, chunk).ratio()
        if ratio > best:
            best = ratio
        if best >= 0.95:
            break

    return best


def _recommendation(score: float, missing: list, job: Job) -> str:
    """Determine recommendation based on score and missing keywords."""
    if score >= 0.7:
        return "apply"
    elif score >= 0.4:
        return "tailor_first"
    else:
        return "skip"
