"""
Tests for Stage 2 post-LLM rule engine (stage2_rules.py).
Test data from stage2_refactor_spec.md Appendix A.
"""

import pytest
from stage2_rules import judge_from_scores, compute_content_confidence, compose_reason, build_stage2_result


# ── Appendix A: standard cases (non-spike) ──────────────────────

@pytest.mark.parametrize("I, A, D, expected_washed, expected_type", [
    (5, 2, 3, True,  "incentive"),   # case 1
    (1, 2, 1, True,  "template"),    # case 2
    (1, 5, 5, False, "none"),        # case 3
    (1, 2, 2, True,  "template"),    # case 4
    (1, 4, 3, False, "none"),        # case 5
    (1, 2, 2, True,  "template"),    # case 6
    (1, 4, 3, False, "none"),        # case 7
    (1, 3, 4, False, "none"),        # case 8
    (2, 4, 4, False, "none"),        # case 9
    (1, 2, 2, True,  "template"),    # case 10
    (1, 3, 4, False, "none"),        # case 11
])
def test_standard_cases(I, A, D, expected_washed, expected_type):
    is_washed, issue_type = judge_from_scores(I, A, D, is_spike=False)
    assert is_washed == expected_washed
    assert issue_type == expected_type


# ── Appendix A: boundary cases ──────────────────────────────────

def test_boundary_5_4_4_clean():
    """(5, 4, 4) → clean (exception: genuine consumption detail)."""
    is_washed, issue_type = judge_from_scores(5, 4, 4, is_spike=False)
    assert is_washed is False
    assert issue_type == "none"


def test_boundary_5_3_3_washed():
    """(5, 3, 3) → washed/incentive."""
    is_washed, issue_type = judge_from_scores(5, 3, 3, is_spike=False)
    assert is_washed is True
    assert issue_type == "incentive"


def test_boundary_3_3_2_washed():
    """(3, 3, 2) → washed/incentive."""
    is_washed, issue_type = judge_from_scores(3, 3, 2, is_spike=False)
    assert is_washed is True
    assert issue_type == "incentive"


def test_boundary_1_4_2_non_spike_clean():
    """(1, 4, 2) non-spike → clean."""
    is_washed, issue_type = judge_from_scores(1, 4, 2, is_spike=False)
    assert is_washed is False
    assert issue_type == "none"


def test_boundary_1_4_2_spike_washed():
    """(1, 4, 2) spike → washed/template."""
    is_washed, issue_type = judge_from_scores(1, 4, 2, is_spike=True)
    assert is_washed is True
    assert issue_type == "template"


def test_boundary_1_4_3_spike_clean():
    """(1, 4, 3) spike → clean (D=3 does not trigger)."""
    is_washed, issue_type = judge_from_scores(1, 4, 3, is_spike=True)
    assert is_washed is False
    assert issue_type == "none"


# ── Confidence formula ──────────────────────────────────────────

def test_confidence_washed_high():
    """High wash scores (I=5, A=1, D=1) → high confidence."""
    conf = compute_content_confidence(True, 5, 1, 1)
    assert conf == 100  # s_val=12, agreement=1.0, 1^1.5=1 → 100


def test_confidence_clean_high():
    """Clean with (I=1, A=5, D=5) → high confidence."""
    conf = compute_content_confidence(False, 1, 5, 5)
    assert conf == 100  # s_val=0, agreement=1.0


def test_confidence_ambiguous():
    """Middle scores (3,3,3) → low confidence."""
    conf = compute_content_confidence(True, 3, 3, 3)
    # s_val=(2)+(2)+(2)=6, washRatio=0.5, agreement=0.5, 0.5^1.5≈0.354 → 35
    assert conf == 35


# ── Reason composition ──────────────────────────────────────────

def test_reason_incentive_i5():
    reason = compose_reason(True, "incentive", 5, 2, 3, False)
    assert "I=5" in reason and "明文利益交換" in reason


def test_reason_incentive_i3():
    reason = compose_reason(True, "incentive", 3, 3, 2, False)
    assert "I=3" in reason and "D=2" in reason


def test_reason_template_spike():
    reason = compose_reason(True, "template", 1, 4, 2, True)
    assert "集中發表期" in reason


def test_reason_template_non_spike():
    reason = compose_reason(True, "template", 1, 2, 2, False)
    assert "空洞模板" in reason


def test_reason_clean():
    reason = compose_reason(False, "none", 1, 5, 5, False)
    assert "無洗評特徵" in reason


# ── build_stage2_result integration ─────────────────────────────

def test_build_result_washed():
    result = build_stage2_result("Alice", 5, 2, 3, "明文打卡送禮", is_spike=False)
    assert result["username"] == "Alice"
    assert result["isWashed"] is True
    assert result["issueType"] == "incentive"
    assert result["verdictBasis"] == "content"
    assert result["incentiveIntensity"] == 5
    assert result["reasoningPath"] == "明文打卡送禮"
    assert 0 <= result["confidenceScore"] <= 100


def test_build_result_clean():
    result = build_stage2_result("Bob", 1, 5, 5, "具體描述", is_spike=False)
    assert result["isWashed"] is False
    assert result["issueType"] == "none"
    assert result["confidenceScore"] == 100
