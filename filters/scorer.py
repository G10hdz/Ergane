"""
ergane/filters/scorer.py
Semantic scoring with Ollama (qwen2.5-coder:7b).
Second pass in hybrid pipeline (after CV keyword matching).
Optional: only runs if ERGANE_OLLAMA_ENABLED=true in .env
"""
import json
import logging
import os
import re
import time
from typing import Optional, Tuple

import requests

from db.models import Job

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration from .env
# ---------------------------------------------------------------------------

OLLAMA_ENABLED = os.getenv("ERGANE_OLLAMA_ENABLED", "false").lower() == "true"
OLLAMA_URL = os.getenv("ERGANE_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("ERGANE_OLLAMA_MODEL", "qwen2.5-coder:7b")

# Timeouts and retries
OLLAMA_TIMEOUT = 30  # seconds
OLLAMA_RETRIES = 1

# Weight for hybrid scoring (CV match + Ollama semantic)
CV_WEIGHT = 0.6  # 60% CV keyword match
OLLAMA_WEIGHT = 0.4  # 40% semantic scoring


# ---------------------------------------------------------------------------
# Main functions
# ---------------------------------------------------------------------------

def score_with_ollama(job: Job) -> Tuple[float, str]:
    """
    Score a job semantically using Ollama.
    
    Args:
        job: Job object to score
        
    Returns:
        (score, reason) where:
        - score: float 0.0-1.0
        - reason: brief string explaining the score
        
    If Ollama is not enabled or fails, returns (0.0, "error: ...")
    """
    if not OLLAMA_ENABLED:
        logger.debug("Ollama disabled, skipping semantic scoring")
        return (0.0, "ollama disabled")

    # Build prompt with Mayte's context
    prompt = _build_prompt(job)
    
    # Call Ollama with retries
    for attempt in range(OLLAMA_RETRIES + 1):
        try:
            response_text = _call_ollama(prompt)
            if response_text is None:
                continue
            
            # Parse response
            score, reason = _parse_response(response_text)
            if score is not None:
                logger.info(
                    "[ollama] Score %.2f for: %s @ %s | %s",
                    score, job.title, job.company or "Unknown", reason
                )
                return (score, reason)
                
        except Exception as e:
            logger.warning(
                "[ollama] Attempt %d failed: %s",
                attempt + 1, e
            )
            if attempt < OLLAMA_RETRIES:
                time.sleep(2 ** attempt)  # Exponential backoff
    
    # All attempts failed
    logger.error("[ollama] All attempts failed for: %s", job.title)
    return (0.0, "error: ollama unavailable")


def _build_prompt(job: Job) -> str:
    """
    Build the prompt for Ollama with Mayte's profile context.
    """
    title = job.title or ""
    description = job.description or ""
    tags = ", ".join(job.tags) if job.tags else ""
    company = job.company or ""
    salary = job.salary_raw or "Not specified"
    
    # Truncate description if too long (max 1500 chars)
    if len(description) > 1500:
        description = description[:1500] + "..."
    
    prompt = f"""You are a job match evaluator for Mayte Giovanna Hernández Ríos.

CANDIDATE PROFILE:
- Cloud & Automation Engineer, 1 year AWS enterprise support (S3, DataSync, Transfer Family, Lambda)
- Python/boto3 automation, Terraform IaC
- AI/ML: RAG, LangChain, Anthropic API, local inference (Ollama/ROCm)
- Math @ UNAM, building MLOps/LLMOps career
- Co-founder Positronica Labs (FairHire, QMANUS - production AI systems)
- Stack: Python, AWS, Terraform, FastAPI, React, TypeScript, SQLite

SCORE THIS JOB 0.0-1.0:
Title: {title}
Company: {company}
Salary: {salary}
Tags: {tags}
Description: {description}

SCORING CRITERIA:
- 0.8-1.0: Strong AWS/Python/AI match, role fits her career goals
- 0.5-0.7: Some relevant skills, decent match
- 0.2-0.4: Weak match or wrong stack
- 0.0-0.1: EXCLUDE (banks, fintech like BBVA/Santander, fake junior, <30k MXN)

Respond with ONLY this JSON format:
{{"score": 0.75, "reason": "AWS + Python match, AI/ML role aligns with career goals"}}

Do not include any other text. Just the JSON."""

    return prompt


def _call_ollama(prompt: str) -> Optional[str]:
    """
    Call Ollama API and return the response.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,  # Low for consistent responses
            "num_predict": 150,  # Enough for JSON + reason
        }
    }
    
    url = f"{OLLAMA_URL}/api/generate"
    
    logger.debug("[ollama] Calling %s with model %s", url, OLLAMA_MODEL)
    
    response = requests.post(
        url,
        json=payload,
        timeout=OLLAMA_TIMEOUT
    )
    response.raise_for_status()
    
    result = response.json()
    return result.get("response", "")


def _parse_response(response_text: str) -> Tuple[Optional[float], str]:
    """
    Parse Ollama response to extract score and reason.
    
    Returns (None, "error: ...") if parsing fails.
    """
    if not response_text:
        return (None, "error: empty response")
    
    # Clean response
    response_text = response_text.strip()
    
    # Try to extract JSON
    json_match = re.search(r'\{[^}]+\}', response_text, re.DOTALL)
    
    if not json_match:
        logger.warning("[ollama] No JSON found in response: %s", response_text[:100])
        return (None, "error: invalid json format")
    
    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError as e:
        logger.warning("[ollama] Invalid JSON: %s | error: %s", json_match.group(), e)
        return (None, "error: json decode failed")
    
    # Extract score
    score = data.get("score")
    if score is None:
        return (None, "error: no score in response")
    
    # Validate score
    try:
        score = float(score)
    except (TypeError, ValueError):
        return (None, "error: score not a number")
    
    if score < 0.0 or score > 1.0:
        logger.warning("[ollama] Score out of range: %.2f, clamping to 0.0-1.0", score)
        score = max(0.0, min(1.0, score))
    
    # Extract reason
    reason = data.get("reason", "no reason provided")
    reason = str(reason)[:100]  # Max 100 chars
    
    return (score, reason)


# ---------------------------------------------------------------------------
# Hybrid pipeline (CV matching + Ollama)
# ---------------------------------------------------------------------------

def score_jobs(jobs: list[Job], cv_scores: dict = None) -> list[Job]:
    """
    Score jobs using hybrid approach:
    - 60% CV keyword matching (already done in cv_matcher.py)
    - 40% Ollama semantic scoring (if enabled)
    
    Args:
        jobs: List of jobs to score (already has job.score from CV matching)
        cv_scores: Dict mapping job.url_hash -> cv_score (optional)
        
    Returns:
        Jobs with updated hybrid scores
    """
    if not OLLAMA_ENABLED:
        logger.info("[ollama] Disabled, using CV scores only")
        return jobs
    
    logger.info("[ollama] Applying semantic scoring to %d jobs", len(jobs))
    
    for job in jobs:
        # Get CV score (already in job.score from cv_matcher)
        cv_score = job.score
        
        # Get Ollama semantic score
        ollama_score, reason = score_with_ollama(job)
        
        if ollama_score > 0:
            # Hybrid: 60% CV + 40% Ollama
            hybrid_score = (CV_WEIGHT * cv_score) + (OLLAMA_WEIGHT * ollama_score)
            job.score = min(hybrid_score, 1.0)
            
            logger.debug(
                "[ollama] Hybrid score for %s: CV=%.2f + Ollama=%.2f = %.2f | %s",
                job.title, cv_score, ollama_score, job.score, reason
            )
        else:
            # Ollama failed, keep CV score
            logger.debug(
                "[ollama] Using CV score only for %s: %.2f",
                job.title, cv_score
            )
    
    return jobs


def score_jobs_ollama_only(jobs: list[Job]) -> list[Job]:
    """
    Score jobs using ONLY Ollama (no CV matching).
    Use this when you want pure semantic scoring.
    """
    logger.info("[ollama] Scoring %d jobs semantically", len(jobs))
    
    for job in jobs:
        score, reason = score_with_ollama(job)
        job.score = score
        
        if score >= 0.5:
            logger.debug("[ollama] %s: %.2f | %s", job.title, score, reason)
    
    return jobs
