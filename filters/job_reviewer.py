"""
ergane/filters/job_reviewer.py
Job Reviewer Agent: LangChain + LangGraph powered CV scoring + job matching.
Replaces filters/scorer.py with structured, stateful agent workflow.

Two modes:
  1. Pipeline mode: batch score scraped jobs against profile skills
  2. Interactive mode: user asks "/review this job" via Telegram

LangGraph state machine flow:
  extract_context → score_cv → score_semantic → combine → sync_obsidian
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from pydantic import BaseModel, Field

# Lazy imports - only load LangChain/LangGraph when needed
# These are expensive (~500ms) so avoid in pipeline mode

# Backwards-compatible stub for tests
class ReviewState(TypedDict):
    job_title: str
    job_description: str
    job_company: str
    job_tags: List[str]
    job_salary: str
    job_url: str
    profile_name: str
    profile_skills: Dict[str, float]
    profile_core_skills: List[str]
    profile_context: str
    rules_score: float
    seniority_score: float
    company_score: float
    cv_result: Optional[Dict[str, Any]]
    semantic_result: Optional[Dict[str, Any]]
    combined_result: Optional[Dict[str, Any]]
    error: Optional[str]
    obsidian_path: Optional[str]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OLLAMA_URL = os.getenv("ERGANE_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("ERGANE_OLLAMA_MODEL", "qwen2.5-coder:7b")
OLLAMA_ENABLED = os.getenv("ERGANE_OLLAMA_ENABLED", "false").lower() == "true"
OBSIDIAN_VAULT = os.path.expanduser(os.getenv(
    "ERGANE_OBSIDIAN_VAULT",
    "~/Documents/Ai's help/"
))

# Scoring weights
CV_WEIGHT = 0.40
RULES_WEIGHT = 0.25
SENIORITY_WEIGHT = 0.20
COMPANY_WEIGHT = 0.15

logger = logging.getLogger(__name__)


def node_extract_context(state: ReviewState) -> ReviewState:
    """Validate and enrich input state (backwards-compatible stub)."""
    if not state.get("job_title"):
        state["error"] = "Missing job_title"
        return state
    state["job_description"] = state.get("job_description") or ""
    state["job_company"] = state.get("job_company") or "Unknown"
    state["job_tags"] = state.get("job_tags") or []
    state["job_salary"] = state.get("job_salary") or "Not specified"
    state["job_url"] = state.get("job_url") or ""
    state["profile_name"] = state.get("profile_name") or "Unknown"
    state["profile_skills"] = state.get("profile_skills") or {}
    state["profile_core_skills"] = state.get("profile_core_skills") or []
    state["profile_context"] = state.get("profile_context") or ""
    state.setdefault("rules_score", 0.0)
    state.setdefault("seniority_score", 0.0)
    state.setdefault("company_score", 0.0)
    return state


def build_review_graph():
    """Build LangGraph (backwards-compatible stub)."""
    return get_review_graph()


# ---------------------------------------------------------------------------
# Lazy-loaded LangChain/LangGraph components
# ---------------------------------------------------------------------------

def _get_llm(temperature: float = 0.1):
    """Get ChatOllama instance (lazy load)."""
    from langchain_ollama import ChatOllama
    return ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_URL,
        temperature=temperature,
        format="json",
    )


def _build_prompts():
    """Build LangChain prompts (lazy load)."""
    from langchain_core.prompts import ChatPromptTemplate
    cv_prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert CV reviewer and job matching specialist.
Analyze how well the candidate's skills match the job description.
Return ONLY valid JSON matching this schema:
{"score": 0.75, "matched_skills": ["python"], "missing_skills": [], "feedback": []}"""),
        ("human", """CANDIDATE: {profile_name} | {profile_context} | Skills: {profile_skills}
JOB: {job_title} @ {job_company} | {job_salary} | {job_description} | Tags: {job_tags}
Score this job."""),
    ])
    semantic_prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a senior tech recruiter. Evaluate job fit.
Return JSON: {"score": 0.8, "reasoning": "...", "concerns": [], "strengths": []}"""),
        ("human", """CANDIDATE: {profile_name} | {profile_context}
JOB: {job_title} @ {job_company} | {job_description} | Tags: {job_tags} | {job_salary}
Evaluate fit."""),
    ])
    return cv_prompt, semantic_prompt


def _build_review_graph():
    """Build and compile LangGraph (lazy load)."""
    from langgraph.graph import END, StateGraph
    from typing import TypedDict
    
    class ReviewState(TypedDict):
        job_title: str
        job_description: str
        job_company: str
        job_tags: list
        job_salary: str
        job_url: str
        profile_name: str
        profile_skills: dict
        profile_core_skills: list
        profile_context: str
        rules_score: float
        seniority_score: float
        company_score: float
        cv_result: dict
        semantic_result: dict
        combined_result: dict
        error: str
        obsidian_path: str
    
    def node_extract_context(state: ReviewState) -> ReviewState:
        if not state.get("job_title"):
            state["error"] = "Missing job_title"
            return state
        state["job_description"] = state.get("job_description") or ""
        state["job_company"] = state.get("job_company") or "Unknown"
        state["job_tags"] = state.get("job_tags") or []
        state["job_salary"] = state.get("job_salary") or "Not specified"
        state["job_url"] = state.get("job_url") or ""
        state["profile_name"] = state.get("profile_name") or "Unknown"
        state["profile_skills"] = state.get("profile_skills") or {}
        state["profile_core_skills"] = state.get("profile_core_skills") or []
        state["profile_context"] = state.get("profile_context") or ""
        return state

    def node_score_cv(state: ReviewState) -> ReviewState:
        if not OLLAMA_ENABLED:
            state["cv_result"] = _cv_keyword_fallback(state)
            return state
        try:
            from pydantic import BaseModel, Field
            class CVScoreResult(BaseModel):
                score: float = Field(ge=0.0, le=1.0)
                matched_skills: list = Field(default_factory=list)
                missing_skills: list = Field(default_factory=list)
                feedback: list = Field(default_factory=list)
            cv_prompt, _ = _build_prompts()
            llm = _get_llm().with_structured_output(CVScoreResult)
            response = (cv_prompt | llm).invoke({
                "profile_name": state["profile_name"],
                "profile_context": state["profile_context"],
                "profile_skills": json.dumps(state["profile_skills"], ensure_ascii=False),
                "job_title": state["job_title"],
                "job_company": state["job_company"],
                "job_salary": state["job_salary"],
                "job_description": state["job_description"][:2000],
                "job_tags": ", ".join(state["job_tags"]),
            })
            state["cv_result"] = {"score": response.score, "matched_skills": response.matched_skills,
                                  "missing_skills": response.missing_skills, "feedback": response.feedback}
        except Exception as e:
            state["cv_result"] = _cv_keyword_fallback(state)
        return state

    def node_score_semantic(state: ReviewState) -> ReviewState:
        if not OLLAMA_ENABLED:
            state["semantic_result"] = None
            return state
        try:
            from pydantic import BaseModel, Field
            class SemanticScoreResult(BaseModel):
                score: float = Field(ge=0.0, le=1.0)
                reasoning: str
                concerns: list = Field(default_factory=list)
                strengths: list = Field(default_factory=list)
            _, semantic_prompt = _build_prompts()
            llm = _get_llm().with_structured_output(SemanticScoreResult)
            response = (semantic_prompt | llm).invoke({
                "profile_name": state["profile_name"],
                "profile_context": state["profile_context"],
                "job_title": state["job_title"],
                "job_company": state["job_company"],
                "job_description": state["job_description"][:2000],
                "job_tags": ", ".join(state["job_tags"]),
                "job_salary": state["job_salary"],
                "job_url": state["job_url"],
            })
            state["semantic_result"] = {"score": response.score, "reasoning": response.reasoning,
                                         "concerns": response.concerns, "strengths": response.strengths}
        except Exception:
            state["semantic_result"] = None
        return state

    def node_combine_scores(state: ReviewState) -> ReviewState:
        cv_result = state.get("cv_result", {})
        semantic_result = state.get("semantic_result")
        rules_score = state.get("rules_score", 0.0)
        seniority_score = state.get("seniority_score", 0.0)
        company_score = state.get("company_score", 0.0)
        cv_score = cv_result.get("score", 0.0) if cv_result else 0.0
        semantic_score = semantic_result.get("score", 0.0) if semantic_result else 0.0
        
        if semantic_score > 0 and OLLAMA_ENABLED:
            final_score = 0.70 * (CV_WEIGHT * cv_score + (1.0 - CV_WEIGHT) * semantic_score) + \
                          0.15 * rules_score + 0.10 * seniority_score + 0.05 * company_score
        else:
            final_score = CV_WEIGHT * cv_score + RULES_WEIGHT * rules_score + \
                          SENIORITY_WEIGHT * seniority_score + COMPANY_WEIGHT * company_score
        
        final_score = min(1.0, max(0.0, final_score))
        recommendation = "Apply" if final_score >= 0.70 else "Consider" if final_score >= 0.40 else "Skip"
        matched = cv_result.get("matched_skills", []) if cv_result else []
        concerns = semantic_result.get("concerns", []) if semantic_result else []
        strengths = semantic_result.get("strengths", []) if semantic_result else []
        
        state["combined_result"] = {
            "final_score": round(final_score, 3),
            "cv_score": round(cv_score, 3),
            "semantic_score": round(semantic_score, 3),
            "recommendation": recommendation,
            "summary": f"Strengths: {', '.join(strengths[:2])} | Concerns: {', '.join(concerns[:2])}" if strengths or concerns else f"Score: {final_score:.2f}",
            "matched_keywords": matched,
            "action_items": [],
        }
        return state

    def node_sync_obsidian(state: ReviewState) -> ReviewState:
        combined = state.get("combined_result")
        if not combined:
            return state
        try:
            import os
            os.makedirs(OBSIDIAN_VAULT, exist_ok=True)
            title_safe = f"{state['job_title'].replace(' ', '_')[:30]}_{state.get('job_company', 'unknown').replace(' ', '_')[:20]}"
            filename = f"{datetime.now().strftime('%Y%m%d_%H%M')}_review_{title_safe}.md"
            filepath = os.path.join(OBSIDIAN_VAULT, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"Job Review: {state['job_title']} @ {state['job_company']}\nScore: {combined['final_score']}")
            state["obsidian_path"] = filepath
        except Exception:
            state["obsidian_path"] = None
        return state

    workflow = StateGraph(ReviewState)
    workflow.add_node("extract_context", node_extract_context)
    workflow.add_node("score_cv", node_score_cv)
    workflow.add_node("score_semantic", node_score_semantic)
    workflow.add_node("combine", node_combine_scores)
    workflow.add_node("sync_obsidian", node_sync_obsidian)
    workflow.set_entry_point("extract_context")
    workflow.add_edge("extract_context", "score_cv")
    workflow.add_edge("score_cv", "score_semantic")
    workflow.add_edge("score_semantic", "combine")
    workflow.add_edge("combine", "sync_obsidian")
    workflow.add_edge("sync_obsidian", END)
    return workflow.compile()


# Fallback: pure keyword matching (no Ollama)
def _cv_keyword_fallback(state: dict) -> dict:
    """Simple keyword matching when LLM is unavailable."""
    text_to_search = " ".join([
        state.get("job_title", "").lower(),
        state.get("job_description", "").lower(),
        " ".join(t.lower() for t in state.get("job_tags", [])),
    ])
    matched = []
    for skill in state.get("profile_skills", {}):
        if skill.lower() in text_to_search:
            matched.append(skill)
    score = min(1.0, sum(state.get("profile_skills", {}).get(s, 0.0) for s in matched))
    feedback = [f"Match: {', '.join(matched[:5])}"] if matched else ["No match"]
    return {"score": round(score, 3), "matched_skills": matched, "missing_skills": [],
            "feedback": feedback}


# Cache the compiled graph
_review_graph = None


def _fast_review_job(job, profile, rules_score, seniority_score, company_score):
    """Fast path: Skip LangGraph, use direct keyword matching only."""
    profile_skills = getattr(profile, 'skills', profile.get('skills', {}) if isinstance(profile, dict) else {})
    text_to_search = " ".join([
        (job.title or "").lower(),
        (job.description or "").lower(),
        " ".join(t.lower() for t in (job.tags or [])),
    ])
    matched = [s for s in profile_skills if s.lower() in text_to_search]
    cv_score = min(1.0, sum(profile_skills.get(s, 0.0) for s in matched))
    final_score = CV_WEIGHT * cv_score + RULES_WEIGHT * rules_score + \
                  SENIORITY_WEIGHT * seniority_score + COMPANY_WEIGHT * company_score
    final_score = min(1.0, max(0.0, final_score))
    return {"final_score": round(final_score, 3), "cv_score": round(cv_score, 3), "semantic_score": 0.0,
            "recommendation": "Apply" if final_score >= 0.70 else "Consider" if final_score >= 0.40 else "Skip",
            "summary": f"Matched: {', '.join(matched[:3]) if matched else 'None'}",
            "matched_keywords": matched, "action_items": []}


def get_review_graph():
    global _review_graph
    if _review_graph is None:
        _review_graph = _build_review_graph()
    return _review_graph


# ---------------------------------------------------------------------------
# Public API: Pipeline Mode
# ---------------------------------------------------------------------------


def review_job(job, profile, rules_score=0.0, seniority_score=0.0,
               company_score=0.0, sync_obsidian=False, fast_mode=True):
    """
    Review a single job against a profile.

    Args:
        job: Ergane Job model
        profile: UserProfile from profiles/ (or dict with skills, name, etc.)
        rules_score: Pre-computed rules score
        seniority_score: Pre-computed seniority score
        company_score: Pre-computed company score
        sync_obsidian: Whether to save to Obsidian
        fast_mode: If True, skip LangGraph when Ollama disabled (for pipeline)

    Returns:
        Dict with scoring results (compatible with combined_result format)
    """
    # FAST PATH: Skip LangGraph entirely when Ollama disabled
    if fast_mode and not OLLAMA_ENABLED:
        return _fast_review_job(job, profile, rules_score, seniority_score, company_score)
    # Extract profile data
    if hasattr(profile, 'skills'):
        profile_name = profile.name
        profile_skills = profile.skills
        profile_core = getattr(profile, 'core_skills', [])
        profile_ctx = getattr(profile, 'bio', f"{profile_name}'s profile")
    elif isinstance(profile, dict):
        profile_name = profile.get("name", "Unknown")
        profile_skills = profile.get("skills", {})
        profile_core = profile.get("core_skills", [])
        profile_ctx = profile.get("bio", "")
    else:
        profile_name = "Default"
        profile_skills = {}
        profile_core = []
        profile_ctx = ""

    # Build initial state
    initial_state: ReviewState = {
        "job_title": job.title or "",
        "job_description": job.description or "",
        "job_company": job.company or "Unknown",
        "job_tags": job.tags or [],
        "job_salary": job.salary_raw or "Not specified",
        "job_url": job.url or "",
        "profile_name": profile_name,
        "profile_skills": profile_skills,
        "profile_core_skills": profile_core,
        "profile_context": profile_ctx,
        "rules_score": rules_score,
        "seniority_score": seniority_score,
        "company_score": company_score,
        "cv_result": None,
        "semantic_result": None,
        "combined_result": None,
        "error": None,
        "obsidian_path": None,
    }

    # Run the graph
    graph = get_review_graph()
    result = graph.invoke(initial_state)

    if result.get("error"):
        logger.error("[job_reviewer] Error: %s", result["error"])
        return {"error": result["error"]}

    combined = result.get("combined_result", {})
    if not sync_obsidian:
        combined.pop("obsidian_path", None)

    return combined


def review_jobs_batch(jobs: List[Job], profile: Any = None,
                      min_score: float = 0.4) -> List[Dict[str, Any]]:
    """
    Review multiple jobs in batch.

    Args:
        jobs: List of Ergane Job models
        profile: UserProfile or dict
        min_score: Minimum score to include in results

    Returns:
        List of scoring results, sorted by score descending
    """
    results = []

    for job in jobs:
        # Get pre-computed scores if available
        r_score = getattr(job, 'rules_score', 0.0)
        s_score = getattr(job, 'seniority_score', 0.0)
        c_score = getattr(job, 'company_score', 0.0)

        result = review_job(
            job=job,
            profile=profile,
            rules_score=r_score,
            seniority_score=s_score,
            company_score=c_score,
            sync_obsidian=False,  # Don't spam Obsidian for batch
        )

        if result.get("final_score", 0) >= min_score:
            result["_job_url"] = job.url
            result["_job_title"] = job.title
            result["_job_company"] = job.company
            results.append(result)

    # Sort by score descending
    results.sort(key=lambda x: x.get("final_score", 0), reverse=True)

    logger.info(
        "[job_reviewer] Batch review: %d/%d jobs above threshold %.2f",
        len(results), len(jobs), min_score
    )

    return results


# ---------------------------------------------------------------------------
# Public API: Interactive Mode (Mentis-style)
# ---------------------------------------------------------------------------


def review_cv_against_job(cv_text: str, job_description: str,
                          job_title: str = "", job_company: str = "") -> Dict[str, Any]:
    """
    Interactive mode: user pastes their CV + a job description.

    Args:
        cv_text: User's CV text
        job_description: Job description text
        job_title: Job title (optional)
        job_company: Company name (optional)

    Returns:
        Dict with score, feedback, recommendations
    """
    if not OLLAMA_ENABLED:
        return {
            "error": "Ollama not enabled. Set ERGANE_OLLAMA_ENABLED=true",
            "suggestion": "Run: ollama serve && ollama pull qwen2.5-coder:7b",
        }

    if len(cv_text) < 50:
        return {
            "error": "CV text too short (min 50 chars)",
            "suggestion": "Paste your full CV or resume text",
        }

    if len(job_description) < 50:
        return {
            "error": "Job description too short (min 50 chars)",
            "suggestion": "Paste the full job description",
        }

    # Build state for interactive review
    initial_state: ReviewState = {
        "job_title": job_title or "Unknown Position",
        "job_description": job_description[:3000],
        "job_company": job_company or "Unknown",
        "job_tags": [],
        "job_salary": "Not specified",
        "job_url": "",
        "profile_name": "User",
        "profile_skills": {},  # Extract from CV text
        "profile_core_skills": [],
        "profile_context": cv_text[:1000],  # Use CV as context
        "rules_score": 0.0,
        "seniority_score": 0.0,
        "company_score": 0.0,
        "cv_result": None,
        "semantic_result": None,
        "combined_result": None,
        "error": None,
        "obsidian_path": None,
    }

    # Run the graph
    graph = get_review_graph()
    result = graph.invoke(initial_state)

    if result.get("error"):
        return {"error": result["error"]}

    combined = result.get("combined_result", {})
    combined["cv_text_preview"] = cv_text[:100] + "..."
    combined["job_preview"] = f"{job_title} @ {job_company}"

    return combined


# ---------------------------------------------------------------------------
# CLI: Test the agent
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Job Reviewer Agent")
    parser.add_argument("--test", action="store_true", help="Run a test review")
    parser.add_argument("--cv", type=str, help="Path to CV text file")
    parser.add_argument("--job", type=str, help="Path to job description file")
    args = parser.parse_args()

    if args.test:
        print("=" * 60)
        print("Job Reviewer Agent — Test Mode")
        print("=" * 60)
        print(f"Ollama: {'enabled' if OLLAMA_ENABLED else 'disabled'}")
        print(f"Model: {OLLAMA_MODEL}")
        print(f"URL: {OLLAMA_URL}")
        print("-" * 60)

        # Test with dummy data
        from db.models import Job

        class FakeProfile:
            name = "Mayte"
            skills = {
                "python": 0.20, "aws": 0.20, "terraform": 0.15,
                "docker": 0.10, "langchain": 0.15, "rag": 0.10,
            }
            core_skills = ["python", "aws", "terraform"]
            bio = "Cloud & Automation Engineer, 1 year AWS enterprise support"

        test_job = Job(
            url="https://example.com/job/devops-engineer",
            title="DevOps Engineer",
            source="test",
            company="Startup MX",
            salary_min=35000,
            salary_raw="35,000 MXN",
            tags=["Python", "AWS", "Docker", "Terraform", "CI/CD"],
            remote=True,
            description="""
We're looking for a DevOps Engineer with strong Python and AWS experience.
You'll build infrastructure as code with Terraform, deploy with Docker,
and manage CI/CD pipelines. Experience with LangChain or AI/ML is a plus.
            """.strip(),
        )

        result = review_job(test_job, FakeProfile())
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("=" * 60)

    elif args.cv and args.job:
        with open(args.cv, "r") as f:
            cv_text = f.read()
        with open(args.job, "r") as f:
            job_text = f.read()

        result = review_cv_against_job(cv_text, job_text)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    else:
        parser.print_help()
