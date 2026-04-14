"""
ergane/filters/cv_matcher.py
Fast keyword-based matching against Mayte's CV skills.
First pass in hybrid scoring pipeline.
"""
import logging
import re
from typing import List, Tuple

from db.models import Job

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mayte's Skills with weights
# ---------------------------------------------------------------------------

MAYTE_SKILLS = {
    # Primary stack (high weight) - AWS/Cloud/Python core
    "python": 0.20,
    "aws": 0.20,
    "terraform": 0.15,
    "boto3": 0.10,
    "docker": 0.10,
    
    # AI/ML (high weight - differentiator)
    "langchain": 0.15,
    "rag": 0.10,
    "llm": 0.10,
    "mlops": 0.10,
    "ollama": 0.08,
    "llmops": 0.08,
    "agents": 0.08,
    
    # Secondary (medium weight)
    "fastapi": 0.08,
    "flask": 0.05,
    "django": 0.05,
    "react": 0.05,
    "typescript": 0.05,
    "javascript": 0.05,
    "sql": 0.05,
    "pandas": 0.05,
    
    # DevOps & Tools (nice to have)
    "devops": 0.05,
    "ci/cd": 0.05,
    "github actions": 0.05,
    "git": 0.05,
    "linux": 0.05,
    "bash": 0.05,
    "shell": 0.05,
    
    # Cloud infrastructure
    "lambda": 0.08,
    "serverless": 0.08,
    "s3": 0.08,
    "ec2": 0.05,
    "iam": 0.05,
    "cloudformation": 0.05,
    "cdk": 0.05,
    "kubernetes": 0.08,
    "k8s": 0.08,
    "eks": 0.05,
    
    # Data & ML infrastructure
    "machine learning": 0.10,
    "ml": 0.08,
    "data pipeline": 0.08,
    "etl": 0.08,
    "airflow": 0.08,
    "sagemaker": 0.08,
    "bedrock": 0.08,
    
    # Frontend (full-stack capability)
    "tailwind": 0.05,
    "next.js": 0.05,
    "nextjs": 0.05,
    "vite": 0.05,
    "shadcn": 0.05,
    
    # Databases
    "sqlite": 0.05,
    "postgresql": 0.05,
    "mysql": 0.05,
    "tidb": 0.05,
    "vector database": 0.08,
    "redis": 0.05,
    
    # Soft skills / languages (for international roles)
    "english": 0.05,
    "bilingual": 0.05,
    "spanish": 0.05,
}

# Skills that are hard requirements for good matches
CORE_SKILLS = {"python", "aws", "terraform", "langchain", "rag", "llm", "mlops"}

# Minimum threshold to pass keyword filter
DEFAULT_MIN_SCORE = 0.15  # Lowered to catch more opportunities


# ---------------------------------------------------------------------------
# Main functions
# ---------------------------------------------------------------------------

def match_cv(job: Job) -> Tuple[float, List[str]]:
    """
    Match job against Mayte's CV skills.
    
    Args:
        job: Job object to evaluate
        
    Returns:
        (score, matched_skills) where:
        - score: float 0.0-1.0 (sum of matched skill weights)
        - matched_skills: list of skill names found in job
    """
    # Build text to search
    text_to_search = " ".join([
        job.title.lower(),
        (job.description or "").lower(),
        " ".join(tag.lower() for tag in job.tags),
    ])
    
    matched_skills = []
    score = 0.0
    
    for skill, weight in MAYTE_SKILLS.items():
        # Use word boundary matching for accuracy
        pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, text_to_search, re.IGNORECASE):
            matched_skills.append(skill)
            score += weight
    
    # Clamp to 1.0
    score = min(score, 1.0)
    
    logger.debug(
        "[cv_matcher] Job: %s @ %s | Score: %.2f | Matched: %s",
        job.title,
        job.company or "Unknown",
        score,
        ", ".join(matched_skills[:5])  # Show first 5
    )
    
    return (score, matched_skills)


def passes_keyword_filter(job: Job, min_score: float = None) -> bool:
    """
    Quick True/False check if job passes keyword filter.
    
    Args:
        job: Job object to evaluate
        min_score: Minimum score threshold (default: 0.25)
        
    Returns:
        True if job has enough skill matches
    """
    if min_score is None:
        min_score = DEFAULT_MIN_SCORE
    
    score, _ = match_cv(job)
    passes = score >= min_score
    
    if not passes:
        logger.debug("[cv_matcher] Filtered out: %s (score %.2f < %.2f)", 
                    job.title, score, min_score)
    
    return passes


def get_skill_gaps(job: Job) -> List[str]:
    """
    Find skills Mayte has that are NOT mentioned in the job.
    Useful for identifying potential learning opportunities.
    
    Args:
        job: Job object to evaluate
        
    Returns:
        List of skill names not found in job description
    """
    text_to_search = " ".join([
        job.title.lower(),
        (job.description or "").lower(),
        " ".join(tag.lower() for tag in job.tags),
    ])
    
    missing_skills = []
    
    for skill in MAYTE_SKILLS.keys():
        pattern = r'\b' + re.escape(skill) + r'\b'
        if not re.search(pattern, text_to_search, re.IGNORECASE):
            missing_skills.append(skill)
    
    return missing_skills


def get_core_skill_matches(job: Job) -> List[str]:
    """
    Find which of Mayte's CORE skills are present in the job.
    
    Args:
        job: Job object to evaluate
        
    Returns:
        List of core skill names found in job
    """
    text_to_search = " ".join([
        job.title.lower(),
        (job.description or "").lower(),
        " ".join(tag.lower() for tag in job.tags),
    ])
    
    matched_core = []
    
    for skill in CORE_SKILLS:
        pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, text_to_search, re.IGNORECASE):
            matched_core.append(skill)
    
    return matched_core


def has_core_skills(job: Job, min_core: int = 2) -> bool:
    """
    Check if job has at least N of Mayte's core skills.
    
    Args:
        job: Job object to evaluate
        min_core: Minimum number of core skills required
        
    Returns:
        True if job has enough core skill matches
    """
    matched_core = get_core_skill_matches(job)
    has_them = len(matched_core) >= min_core
    
    if not has_them:
        logger.debug(
            "[cv_matcher] Missing core skills: %s (has %d/%d required)",
            job.title,
            len(matched_core),
            min_core
        )
    
    return has_them


# ---------------------------------------------------------------------------
# Integration with scoring pipeline
# ---------------------------------------------------------------------------

def cv_score_pipeline(jobs: List[Job], min_score: float = None) -> List[Job]:
    """
    Apply CV matching to a list of jobs.
    Updates job.score with CV match score.
    
    Args:
        jobs: List of jobs to score
        min_score: Minimum score to keep job (default: 0.25)
        
    Returns:
        Filtered list of jobs that pass the threshold
    """
    if min_score is None:
        min_score = DEFAULT_MIN_SCORE
    
    logger.info("[cv_matcher] Scoring %d jobs against CV", len(jobs))
    
    filtered_jobs = []
    
    for job in jobs:
        score, matched = match_cv(job)
        job.score = score  # Store CV match score
        
        if score >= min_score:
            filtered_jobs.append(job)
        else:
            logger.debug(
                "[cv_matcher] Filtered: %s (score %.2f)",
                job.title, score
            )
    
    logger.info(
        "[cv_matcher] Kept %d/%d jobs after CV matching",
        len(filtered_jobs), len(jobs)
    )
    
    return filtered_jobs
