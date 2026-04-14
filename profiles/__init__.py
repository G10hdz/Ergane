"""
ergane/profiles/loader.py
Multi-user profile system for job matching.
Loads YAML profiles from profiles/ directory.
"""
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Default profiles directory
PROFILES_DIR = Path(__file__).parent


@dataclass
class UserProfile:
    """User profile for job matching and notifications."""

    name: str
    enabled: bool = True

    # Telegram settings
    telegram_chat_id: Optional[str] = None

    # Job preferences
    min_salary_mxn: int = 0
    remote_preferred: bool = True
    locations: List[str] = field(default_factory=list)
    exclude_companies: List[str] = field(default_factory=list)

    # Skills with weights (used by cv_matcher / match_job_to_profile)
    skills: Dict[str, float] = field(default_factory=dict)
    core_skills: List[str] = field(default_factory=list)
    min_score: float = 0.15

    # Rules-engine configuration (filters/rules.py). Any field left empty
    # falls back to the module-level defaults in rules.py.
    positive_stack: Dict[str, float] = field(default_factory=dict)
    relevant_titles: List[str] = field(default_factory=list)
    max_years_experience: int = 0       # 0 = no limit
    rules_min_salary_mxn: int = 0       # 0 = fall back to min_salary_mxn
    hard_exclusions: List[str] = field(default_factory=list)

    # Company classification (filters/rules.py::company_score)
    company_blacklist: List[str] = field(default_factory=list)
    company_whitelist: List[str] = field(default_factory=list)

    # Source file path
    _file_path: Optional[str] = None


def load_profile(filepath: str) -> Optional[UserProfile]:
    """Load a single profile from a YAML file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        if not data:
            logger.warning("Empty profile: %s", filepath)
            return None
        
        # Extract telegram settings
        telegram = data.get("telegram", {})
        telegram_chat_id = telegram.get("chat_id") if telegram else None
        
        # Extract preferences
        prefs = data.get("preferences", {})

        # Rules-engine configuration (optional; falls back to module defaults)
        rules_cfg = data.get("rules") or {}
        companies_cfg = data.get("companies") or {}

        profile = UserProfile(
            name=data.get("name", Path(filepath).stem),
            enabled=data.get("enabled", True),
            telegram_chat_id=telegram_chat_id,
            min_salary_mxn=prefs.get("min_salary_mxn", 0),
            remote_preferred=prefs.get("remote_preferred", True),
            locations=prefs.get("locations", []),
            exclude_companies=prefs.get("exclude_companies", []),
            skills=data.get("skills") or {},
            core_skills=data.get("core_skills") or [],
            min_score=data.get("min_score", 0.15),
            positive_stack=rules_cfg.get("positive_stack") or {},
            relevant_titles=rules_cfg.get("relevant_titles") or [],
            max_years_experience=int(rules_cfg.get("max_years_experience", 0) or 0),
            rules_min_salary_mxn=int(rules_cfg.get("min_salary_mxn", 0) or 0),
            hard_exclusions=rules_cfg.get("hard_exclusions") or [],
            company_blacklist=companies_cfg.get("blacklist") or [],
            company_whitelist=companies_cfg.get("whitelist") or [],
            _file_path=filepath,
        )
        
        logger.debug("Loaded profile: %s (%d skills)", profile.name, len(profile.skills))
        return profile
        
    except Exception as e:
        logger.error("Failed to load profile %s: %s", filepath, e)
        return None


def load_all_profiles(profiles_dir: str = None) -> List[UserProfile]:
    """
    Load all enabled profiles from the profiles directory.
    
    Args:
        profiles_dir: Path to profiles directory (default: ./profiles/)
    
    Returns:
        List of enabled UserProfile objects
    """
    if profiles_dir is None:
        profiles_dir = PROFILES_DIR
    
    profiles_path = Path(profiles_dir)
    
    if not profiles_path.exists():
        logger.warning("Profiles directory not found: %s", profiles_path)
        return []
    
    profiles = []
    
    for yaml_file in profiles_path.glob("*.yaml"):
        # Skip template file
        if yaml_file.stem == "template":
            continue
            
        profile = load_profile(str(yaml_file))
        
        if profile and profile.enabled:
            profiles.append(profile)
            logger.info("Loaded profile: %s", profile.name)
        elif profile:
            logger.debug("Skipping disabled profile: %s", profile.name)
    
    logger.info("Loaded %d active profiles", len(profiles))
    return profiles


def get_profile_by_name(name: str, profiles_dir: str = None) -> Optional[UserProfile]:
    """
    Get a specific profile by name.
    
    Args:
        name: Profile name (case-insensitive)
        profiles_dir: Path to profiles directory
    
    Returns:
        UserProfile if found and enabled, None otherwise
    """
    profiles = load_all_profiles(profiles_dir)
    
    for profile in profiles:
        if profile.name.lower() == name.lower():
            return profile
    
    return None


def get_default_profile(profiles_dir: str = None) -> Optional[UserProfile]:
    """
    Get the first enabled profile (for backward compatibility).
    
    Returns:
        First UserProfile found, or None if no profiles exist
    """
    profiles = load_all_profiles(profiles_dir)
    return profiles[0] if profiles else None


# ---------------------------------------------------------------------------
# Profile-based scoring
# ---------------------------------------------------------------------------

import re
from db.models import Job


def match_job_to_profile(job: Job, profile: UserProfile) -> tuple[float, List[str]]:
    """
    Match a job against a user's profile skills.
    
    Args:
        job: Job to evaluate
        profile: User profile with skills and weights
    
    Returns:
        (score, matched_skills) tuple
    """
    # Build text to search
    text_to_search = " ".join([
        job.title.lower(),
        (job.description or "").lower(),
        " ".join(tag.lower() for tag in job.tags),
    ])
    
    matched_skills = []
    score = 0.0
    
    for skill, weight in profile.skills.items():
        # Use word boundary matching for accuracy
        pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, text_to_search, re.IGNORECASE):
            matched_skills.append(skill)
            score += weight
    
    # Clamp to 1.0
    score = min(score, 1.0)
    
    return (score, matched_skills)


def job_passes_profile_filter(job: Job, profile: UserProfile) -> bool:
    """
    Check if a job passes all profile filters.
    
    Checks:
    - Salary minimum
    - Excluded companies
    - Skill score threshold
    
    Returns:
        True if job passes all filters
    """
    # Check excluded companies
    if profile.exclude_companies and job.company:
        company_lower = job.company.lower()
        for excluded in profile.exclude_companies:
            if excluded.lower() in company_lower:
                logger.debug("Excluded company %s for profile %s", job.company, profile.name)
                return False
    
    # Check salary minimum
    if profile.min_salary_mxn > 0 and job.salary_min:
        if job.salary_min < profile.min_salary_mxn:
            logger.debug("Salary too low for profile %s: %d < %d", 
                        profile.name, job.salary_min, profile.min_salary_mxn)
            return False
    
    # Check skill score
    score, _ = match_job_to_profile(job, profile)
    if score < profile.min_score:
        logger.debug("Score too low for profile %s: %.2f < %.2f",
                    profile.name, score, profile.min_score)
        return False
    
    return True


def score_job_for_profile(job: Job, profile: UserProfile) -> float:
    """
    Get the match score for a job against a profile.
    
    Args:
        job: Job to score
        profile: User profile
    
    Returns:
        Match score (0.0-1.0)
    """
    score, _ = match_job_to_profile(job, profile)
    return score


def filter_jobs_for_profile(jobs: List[Job], profile: UserProfile) -> List[Job]:
    """
    Filter and score jobs for a specific profile.
    
    Args:
        jobs: List of jobs to filter
        profile: User profile
    
    Returns:
        Filtered list of jobs that match the profile
    """
    logger.info("[%s] Filtering %d jobs against profile", profile.name, len(jobs))
    
    filtered = []
    
    for job in jobs:
        if job_passes_profile_filter(job, profile):
            # Update job score for this profile
            score, _ = match_job_to_profile(job, profile)
            job.score = score
            filtered.append(job)
    
    logger.info("[%s] Kept %d/%d jobs", profile.name, len(filtered), len(jobs))
    return filtered
