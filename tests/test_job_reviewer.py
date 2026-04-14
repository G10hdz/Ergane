"""
tests/test_job_reviewer.py
Tests for the LangChain + LangGraph Job Reviewer Agent.
Tests cover: keyword fallback, state validation, scoring logic, and Obsidian sync.
"""
import os
import json
import pytest
from unittest.mock import patch, MagicMock

from db.models import Job
from filters.job_reviewer import (
    _cv_keyword_fallback,
    review_job,
    review_cv_against_job,
    review_jobs_batch,
    ReviewState,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_job():
    return Job(
        url="https://example.com/jobs/devops-engineer",
        title="DevOps Engineer",
        company="Startup MX",
        description=(
            "Looking for a DevOps engineer with strong Python and AWS experience. "
            "Must know Terraform, Docker, CI/CD pipelines. LangChain/AI experience is a plus."
        ),
        tags=["Python", "AWS", "Docker", "Terraform"],
        source="test",
    )


@pytest.fixture
def weak_job():
    return Job(
        url="https://example.com/jobs/frontend-react",
        title="Frontend Developer",
        company="Web Agency",
        description="React, CSS, HTML, JavaScript. No cloud or backend experience needed.",
        tags=["React", "JavaScript", "CSS"],
        source="test",
    )


@pytest.fixture
def mayte_profile():
    class FakeProfile:
        name = "Mayte"
        skills = {
            "python": 0.20,
            "aws": 0.20,
            "terraform": 0.15,
            "docker": 0.10,
            "langchain": 0.15,
            "rag": 0.10,
            "kubernetes": 0.08,
        }
        core_skills = ["python", "aws", "terraform"]
        bio = "Cloud & Automation Engineer, 1 year AWS enterprise support"
    return FakeProfile()


@pytest.fixture
def sample_cv_text():
    return """
    Mayte Giovanna Hernández
    Cloud & Automation Engineer
    
    Experience:
    - 1 year AWS enterprise support (S3, DataSync, Lambda)
    - Python/boto3 automation scripts
    - Terraform infrastructure as code
    - Building RAG pipelines with LangChain
    - Local LLM inference with Ollama/ROCm
    
    Skills: Python, AWS, Terraform, Docker, FastAPI, React, TypeScript
    """


# ---------------------------------------------------------------------------
# Tests: CV Keyword Fallback
# ---------------------------------------------------------------------------


class TestCVKeywordFallback:

    def test_high_match(self, sample_job, mayte_profile):
        """Job with many matching skills should score high."""
        state: ReviewState = {
            "job_title": sample_job.title,
            "job_description": sample_job.description,
            "job_company": sample_job.company,
            "job_tags": sample_job.tags,
            "job_salary": sample_job.salary_raw or "N/A",
            "job_url": sample_job.url,
            "profile_name": mayte_profile.name,
            "profile_skills": mayte_profile.skills,
            "profile_core_skills": mayte_profile.core_skills,
            "profile_context": mayte_profile.bio,
            "rules_score": 0.5,
            "seniority_score": 0.5,
            "company_score": 0.5,
            "cv_result": None,
            "semantic_result": None,
            "combined_result": None,
            "error": None,
            "obsidian_path": None,
        }

        result = _cv_keyword_fallback(state)

        assert result["score"] > 0.5
        assert "python" in result["matched_skills"]
        assert "aws" in result["matched_skills"]
        assert "terraform" in result["matched_skills"]

    def test_low_match(self, weak_job, mayte_profile):
        """Frontend job should have low match for DevOps profile."""
        state: ReviewState = {
            "job_title": weak_job.title,
            "job_description": weak_job.description,
            "job_company": weak_job.company,
            "job_tags": weak_job.tags,
            "job_salary": "N/A",
            "job_url": weak_job.url,
            "profile_name": mayte_profile.name,
            "profile_skills": mayte_profile.skills,
            "profile_core_skills": mayte_profile.core_skills,
            "profile_context": mayte_profile.bio,
            "rules_score": 0.3,
            "seniority_score": 0.3,
            "company_score": 0.3,
            "cv_result": None,
            "semantic_result": None,
            "combined_result": None,
            "error": None,
            "obsidian_path": None,
        }

        result = _cv_keyword_fallback(state)

        # Should have very few matches
        assert result["score"] < 0.3
        assert len(result["matched_skills"]) <= 1

    def test_no_skills_profile(self, sample_job):
        """Empty profile should produce zero score."""
        state: ReviewState = {
            "job_title": sample_job.title,
            "job_description": sample_job.description,
            "job_company": sample_job.company,
            "job_tags": sample_job.tags,
            "job_salary": "N/A",
            "job_url": sample_job.url,
            "profile_name": "Empty",
            "profile_skills": {},
            "profile_core_skills": [],
            "profile_context": "",
            "rules_score": 0.0,
            "seniority_score": 0.0,
            "company_score": 0.0,
            "cv_result": None,
            "semantic_result": None,
            "combined_result": None,
            "error": None,
            "obsidian_path": None,
        }

        result = _cv_keyword_fallback(state)
        assert result["score"] == 0.0
        assert result["matched_skills"] == []


# ---------------------------------------------------------------------------
# Tests: review_job (pipeline mode, Ollama disabled)
# ---------------------------------------------------------------------------


class TestReviewJob:

    @patch("filters.job_reviewer.OLLAMA_ENABLED", False)
    def test_review_job_no_ollama(self, sample_job, mayte_profile):
        """Should use keyword fallback when Ollama is disabled."""
        result = review_job(sample_job, mayte_profile)

        assert "final_score" in result
        assert "cv_score" in result
        assert "recommendation" in result
        assert result["cv_score"] > 0
        assert len(result["matched_keywords"]) > 0

    @patch("filters.job_reviewer.OLLAMA_ENABLED", False)
    def test_weak_job_low_score(self, weak_job, mayte_profile):
        """Frontend job should score low for DevOps profile."""
        result = review_job(weak_job, mayte_profile)

        assert result["final_score"] < 0.3
        assert result["recommendation"] == "Skip"

    @patch("filters.job_reviewer.OLLAMA_ENABLED", False)
    def test_dict_profile(self, sample_job):
        """Should work with dict profile, not just objects."""
        profile_dict = {
            "name": "Test",
            "skills": {"python": 0.5, "aws": 0.5},
            "core_skills": ["python"],
            "bio": "Test user",
        }

        result = review_job(sample_job, profile_dict)
        assert "final_score" in result
        assert result["cv_score"] > 0


# ---------------------------------------------------------------------------
# Tests: review_cv_against_job (interactive mode)
# ---------------------------------------------------------------------------


class TestReviewCVAgainstJob:

    @patch("filters.job_reviewer.OLLAMA_ENABLED", False)
    def test_ollama_disabled_error(self):
        """Should return error when Ollama is disabled."""
        result = review_cv_against_job("some cv", "some job")
        assert "error" in result
        assert "Ollama" in result["error"]

    def test_short_cv_error(self):
        """Should reject very short CV text."""
        result = review_cv_against_job("short", "a" * 100)
        assert "error" in result

    def test_short_job_error(self):
        """Should reject very short job description."""
        result = review_cv_against_job("a" * 100, "short")
        assert "error" in result


# ---------------------------------------------------------------------------
# Tests: review_jobs_batch
# ---------------------------------------------------------------------------


class TestReviewJobsBatch:

    @patch("filters.job_reviewer.OLLAMA_ENABLED", False)
    def test_batch_filters_by_min_score(self, sample_job, weak_job, mayte_profile):
        """Should only return jobs above min_score."""
        jobs = [sample_job, weak_job]

        results = review_jobs_batch(jobs, mayte_profile, min_score=0.3)

        # DevOps job should be included
        assert any(r["_job_title"] == sample_job.title for r in results)
        # Frontend job should be excluded (low score)
        assert not any(r["_job_title"] == weak_job.title for r in results)

    @patch("filters.job_reviewer.OLLAMA_ENABLED", False)
    def test_batch_sorted_by_score(self, sample_job, mayte_profile):
        """Results should be sorted by score descending."""
        # Create multiple jobs with varying skill matches
        job1 = Job(
            url="https://example.com/1",
            title="Python AWS Engineer",
            company="A",
            description="Python AWS Terraform Docker",
            tags=["Python", "AWS"],
            source="test",
        )
        job2 = Job(
            url="https://example.com/2",
            title="React Developer",
            company="B",
            description="React CSS HTML",
            tags=["React"],
            source="test",
        )

        results = review_jobs_batch([job1, job2], mayte_profile, min_score=0.0)

        assert len(results) >= 1
        # First result should have highest score
        if len(results) > 1:
            assert results[0]["final_score"] >= results[1]["final_score"]

    @patch("filters.job_reviewer.OLLAMA_ENABLED", False)
    def test_batch_empty_jobs(self, mayte_profile):
        """Should handle empty job list gracefully."""
        results = review_jobs_batch([], mayte_profile)
        assert results == []


# ---------------------------------------------------------------------------
# Tests: LangGraph construction
# ---------------------------------------------------------------------------


class TestLangGraph:

    def test_graph_builds(self):
        """Graph should compile without errors."""
        from filters.job_reviewer import build_review_graph
        graph = build_review_graph()
        assert graph is not None

    def test_graph_cached(self):
        """get_review_graph should cache the graph."""
        from filters.job_reviewer import get_review_graph, _review_graph

        # Reset cache
        import filters.job_reviewer as jr
        jr._review_graph = None

        g1 = get_review_graph()
        g2 = get_review_graph()
        assert g1 is g2  # Same object

    def test_state_defaults(self):
        """node_extract_context should set defaults."""
        from filters.job_reviewer import node_extract_context, ReviewState

        state: ReviewState = {
            "job_title": "Test",
            "job_description": "",
            "job_company": "",
            "job_tags": [],
            "job_salary": "",
            "job_url": "",
            "profile_name": "",
            "profile_skills": {},
            "profile_core_skills": [],
            "profile_context": "",
            "rules_score": 0.0,
            "seniority_score": 0.0,
            "company_score": 0.0,
            "cv_result": None,
            "semantic_result": None,
            "combined_result": None,
            "error": None,
            "obsidian_path": None,
        }

        result = node_extract_context(state)
        assert result["job_company"] == "Unknown"
        assert result["job_salary"] == "Not specified"
        assert result["profile_name"] == "Unknown"

    def test_missing_title_error(self):
        """Empty title should produce error."""
        from filters.job_reviewer import node_extract_context, ReviewState

        state: ReviewState = {
            "job_title": "",
            "job_description": "",
            "job_company": "",
            "job_tags": [],
            "job_salary": "",
            "job_url": "",
            "profile_name": "",
            "profile_skills": {},
            "profile_core_skills": [],
            "profile_context": "",
            "rules_score": 0.0,
            "seniority_score": 0.0,
            "company_score": 0.0,
            "cv_result": None,
            "semantic_result": None,
            "combined_result": None,
            "error": None,
            "obsidian_path": None,
        }

        result = node_extract_context(state)
        assert result["error"] == "Missing job_title"
