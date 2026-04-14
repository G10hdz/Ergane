"""
tests/test_rules_extended.py
Tests for seniority_score and company_score in filters/rules.py.
"""
import pytest
from db.models import Job
from filters.rules import seniority_score, company_score


# ---------------------------------------------------------------------------
# Tests: seniority_score
# ---------------------------------------------------------------------------

class TestSeniorityScore:
    def test_no_penalties_returns_1_0(self):
        """Job with no seniority signals should get 1.0."""
        job = Job(
            url="https://x.com/1",
            title="DevOps Jr",
            description="Entry level position for recent graduates.",
            source="test",
        )
        assert seniority_score(job) == 1.0

    def test_penalizes_5_plus_years(self):
        """Job asking for 5+ years should be penalized."""
        job = Job(
            url="https://x.com/2",
            title="Cloud Engineer",
            description="We need someone with 5+ years of experience in AWS.",
            source="test",
        )
        score = seniority_score(job)
        assert score < 1.0
        assert score >= 0.0

    def test_penalizes_5_anos_spanish(self):
        """Job asking for 5 años should be penalized."""
        job = Job(
            url="https://x.com/3",
            title="Ingeniero Cloud",
            description="Requerimos 5 años de experiencia en Python.",
            source="test",
        )
        score = seniority_score(job)
        assert score < 1.0

    def test_penalizes_senior_level(self):
        """Job asking for senior engineer should be penalized."""
        job = Job(
            url="https://x.com/4",
            title="Engineer",
            description="Looking for a senior engineer to lead our team.",
            source="test",
        )
        score = seniority_score(job)
        assert score < 1.0

    def test_penalizes_staff_level(self):
        """Staff level should be penalized."""
        job = Job(
            url="https://x.com/5",
            title="Engineer",
            description="Staff engineer position with direct reports.",
            source="test",
        )
        score = seniority_score(job)
        assert score < 1.0

    def test_penalizes_lead_level(self):
        """Lead level should be penalized."""
        job = Job(
            url="https://x.com/6",
            title="Engineer",
            description="Lead engineer responsible for architecture decisions.",
            source="test",
        )
        score = seniority_score(job)
        assert score < 1.0

    def test_penalizes_manage_team(self):
        """Managing team responsibility should be penalized."""
        job = Job(
            url="https://x.com/7",
            title="Engineer",
            description="You will manage a team of 5 engineers.",
            source="test",
        )
        score = seniority_score(job)
        assert score < 1.0

    def test_penalizes_liderar_equipo(self):
        """Liderar equipo should be penalized."""
        job = Job(
            url="https://x.com/8",
            title="Ingeniero",
            description="Debes liderar equipo de desarrollo.",
            source="test",
        )
        score = seniority_score(job)
        assert score < 1.0

    def test_penalizes_direct_reports(self):
        """Direct reports should be penalized."""
        job = Job(
            url="https://x.com/9",
            title="Engineer",
            description="This role has direct reports and performance reviews.",
            source="test",
        )
        score = seniority_score(job)
        assert score < 1.0

    def test_high_salary_junior_title_penalty(self):
        """High salary + Jr title should have additional penalty."""
        job = Job(
            url="https://x.com/10",
            title="DevOps Jr",
            description="5+ years experience required.",
            salary_min=65000,
            source="test",
        )
        score = seniority_score(job)
        # 0.3 for 5+ years + 0.2 for high salary + Jr title = 0.5 deduction
        assert score <= 0.5

    def test_score_never_below_0(self):
        """Score should never go below 0.0."""
        job = Job(
            url="https://x.com/11",
            title="Jr Developer",
            description=(
                "7+ years experience. Senior engineer role. "
                "Manage a team with direct reports. Lead architecture decisions."
            ),
            salary_min=80000,
            source="test",
        )
        score = seniority_score(job)
        assert score >= 0.0


# ---------------------------------------------------------------------------
# Tests: company_score
# ---------------------------------------------------------------------------

class TestCompanyScore:
    def test_staffing_blacklist_returns_0_1(self):
        """Staffing companies should return 0.1."""
        staffing_companies = [
            "Manpower", "Adecco", "Randstad", "Kelly Services",
            "Hays", "Robert Half", "Experis", "PageGroup",
            "Michael Page", "Softtek", "Neoris",
            "Infosys", "Wipro", "TCS", "Cognizant", "Stefanini",
        ]
        for company in staffing_companies:
            job = Job(
                url=f"https://x.com/{company}",
                title="Engineer",
                company=company,
                source="test",
            )
            assert company_score(job) == 0.1, f"Failed for {company}"

    def test_startup_whitelist_returns_0_9(self):
        """Whitelisted startups should return 0.9."""
        startup_companies = [
            "Clip", "Konfío", "Konfio", "Kueski", "Bitso",
            "Conekta", "Rappi", "Truora", "Flat.mx",
            "Jüsto", "Clara", "Palenca",
        ]
        for company in startup_companies:
            job = Job(
                url=f"https://x.com/{company}",
                title="Engineer",
                company=company,
                source="test",
            )
            assert company_score(job) == 0.9, f"Failed for {company}"

    def test_unknown_company_returns_0_5(self):
        """Unknown company should return 0.5."""
        job = Job(
            url="https://x.com/unknown",
            title="Engineer",
            company="Random Startup SA de CV",
            source="test",
        )
        assert company_score(job) == 0.5

    def test_no_company_returns_0_5(self):
        """No company should return 0.5."""
        job = Job(
            url="https://x.com/nocompany",
            title="Engineer",
            company=None,
            source="test",
        )
        assert company_score(job) == 0.5

    def test_case_insensitive_matching(self):
        """Company matching should be case insensitive."""
        job = Job(
            url="https://x.com/clip",
            title="Engineer",
            company="CLIP",
            source="test",
        )
        assert company_score(job) == 0.9

        job2 = Job(
            url="https://x.com/manpower",
            title="Engineer",
            company="MANPOWER",
            source="test",
        )
        assert company_score(job2) == 0.1
