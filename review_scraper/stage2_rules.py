"""
Stage 2 post-LLM rule engine: the LLM outputs I/A/D scores only;
verdict (isWashed, issueType) and reason are determined here in code.

Thresholds are carried over from audit_prompt v2 and are ALL provisional —
to be calibrated with labeled stores after this PR lands.
"""


def judge_from_scores(I: int, A: int, D: int, is_spike: bool) -> tuple:
    """Return (is_washed, issue_type). Thresholds per stage2_refactor_spec.md."""
    # Rule 1: incentive exchange
    if I >= 3 and D <= 2:
        return True, "incentive"
    if I == 5 and not (D >= 4 and A >= 4):  # explicit exchange; exception: genuine detail
        return True, "incentive"
    # Rule 2: hollow template (original rule 3 "A<=1 and D<=2" is a subset, merged)
    if D <= 2 and (A <= 2 or is_spike):
        return True, "template"
    return False, "none"


def compute_content_confidence(is_washed: bool, I: int, A: int, D: int) -> int:
    """Content-path confidence (TRUE_RATING_LOGIC.md section 4.3), unchanged."""
    s_val = (I - 1) + (5 - A) + (5 - D)
    wash_ratio = s_val / 12
    agreement = wash_ratio if is_washed else (1 - wash_ratio)
    confidence = round(agreement ** 1.5 * 100)
    return max(0, min(100, confidence))


def compose_reason(is_washed: bool, issue_type: str,
                   I: int, A: int, D: int, is_spike: bool) -> str:
    """Build a human-readable reason string, labeling which rule fired."""
    if not is_washed:
        return "無洗評特徵"
    if issue_type == "incentive":
        if I == 5:
            return f"I={I}，明文利益交換"
        return f"I={I}、D={D}，利益交換且描述空洞"
    if issue_type == "template":
        if is_spike:
            return f"集中發表期且無具體內容（D={D}）"
        return f"A={A}、D={D}，空洞模板"
    return "無洗評特徵"


def build_stage2_result(username: str, I: int, A: int, D: int,
                        reasoning: str, is_spike: bool) -> dict:
    """Compose the full result object (field names unchanged from old schema)."""
    is_washed, issue_type = judge_from_scores(I, A, D, is_spike)
    confidence = compute_content_confidence(is_washed, I, A, D)
    reason = compose_reason(is_washed, issue_type, I, A, D, is_spike)
    return {
        "username": username,
        "isWashed": is_washed,
        "reason": reason,
        "confidenceScore": confidence,
        "issueType": issue_type,
        "verdictBasis": "content",
        "incentiveIntensity": I,
        "sentimentAuthenticity": A,
        "descriptionGranularity": D,
        "reasoningPath": reasoning,
    }
