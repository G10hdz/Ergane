import pytest
from unittest.mock import patch
from db.models import Job
from filters.cv_matcher import (
    match_cv,
    passes_keyword_filter,
    get_skill_gaps,
    get_core_skill_matches,
    has_core_skills,
    cv_score_pipeline,
)
from filters.scorer import (
    score_with_ollama,
    score_jobs,
    _parse_response,
)

@pytest.fixture
def perfect_job():
    return Job(
        url="https://example.com/perfect",
        title="Senior Cloud AI Engineer",
        source="test",
        description="We need someone with extensive Python and AWS experience. You will manage our LLM infrastructure using Terraform, Langchain, and RAG architectures.",
        tags=["Python", "AWS", "Machine Learning", "Docker"]
    )

@pytest.fixture
def poor_job():
    return Job(
        url="https://example.com/poor",
        title="Junior Frontend",
        source="test",
        description="Looking for an HTML developer with some CSS and basic JavaScript.",
        tags=["HTML", "CSS"]
    )

def test_cv_matcher_match_cv(perfect_job, poor_job):
    score_perfect, skills_perfect = match_cv(perfect_job)
    assert score_perfect > 0.5
    assert "python" in skills_perfect
    assert "aws" in skills_perfect
    assert "langchain" in skills_perfect
    
    score_poor, skills_poor = match_cv(poor_job)
    assert score_poor < 0.15 # only javascript matches, which is 0.05
    assert "javascript" in skills_poor or "html" not in skills_poor

def test_cv_matcher_passes_keyword_filter(perfect_job, poor_job):
    assert passes_keyword_filter(perfect_job, min_score=0.15) is True
    assert passes_keyword_filter(poor_job, min_score=0.15) is False

def test_cv_matcher_core_skills(perfect_job, poor_job):
    core_skills = get_core_skill_matches(perfect_job)
    # AWS, Python, LangChain, RAG, LLM (from LLM infrastructure)
    assert len(core_skills) >= 3
    
    assert has_core_skills(perfect_job, min_core=2) is True
    assert has_core_skills(poor_job, min_core=1) is False

def test_cv_score_pipeline(perfect_job, poor_job):
    jobs = [perfect_job, poor_job]
    filtered = cv_score_pipeline(jobs, min_score=0.15)
    
    assert len(filtered) == 1
    assert filtered[0].title == "Senior Cloud AI Engineer"
    assert filtered[0].score > 0.0

def test_scorer_parse_response():
    score, reason = _parse_response('{"score": 0.85, "reason": "Good match base"}')
    assert score == 0.85
    assert reason == "Good match base"
    
    # Text before or after
    score, reason = _parse_response('Here is my response:\n{"score": 0.6, "reason": "Okay"}')
    assert score == 0.6
    
    # Invalid JSON
    score, reason = _parse_response('{"score": 0.5, reason: "missing quotes"}')
    assert score is None

@patch("filters.scorer.OLLAMA_ENABLED", True)
@patch("filters.scorer._call_ollama")
def test_score_with_ollama(mock_call_ollama, perfect_job):
    mock_call_ollama.return_value = '{"score": 0.9, "reason": "Excellent match"}'
    
    score, reason = score_with_ollama(perfect_job)
    assert score == 0.9
    assert reason == "Excellent match"
    mock_call_ollama.assert_called_once()

@patch("filters.scorer.OLLAMA_ENABLED", True)
@patch("filters.scorer._call_ollama")
def test_score_jobs_hybrid(mock_call_ollama, perfect_job):
    # Setup CV score natively
    perfect_job.score = 0.5 # Assume 50% from CV
    
    # Setup Ollama score
    mock_call_ollama.return_value = '{"score": 0.8, "reason": "Excellent match"}'
    
    # Hybrid calculation: 0.6 * CV_SCORE + 0.4 * OLLAMA_SCORE
    # 0.6 * 0.5 = 0.30
    # 0.4 * 0.8 = 0.32
    # Total = 0.62
    
    scored_jobs = score_jobs([perfect_job])
    assert scored_jobs[0].score == pytest.approx(0.62)
