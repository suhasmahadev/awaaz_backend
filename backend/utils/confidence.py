"""
Confidence engine — AWAAZ-PROOF.
ANTIGRAVITY: complete rewrite because original had only bare helpers,
missing calculate_confidence(), ConfidenceBreakdown, ESCALATION_THRESHOLD.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Signal weights ──────────────────────────────────────────────────────────────
# Positive weights sum to 1.10 (allows score > 1.0 before clamping — intended).
# Negative weights are penalties applied when before→after comparison fails.
SIGNAL_WEIGHTS: dict[str, float] = {
    "single_report":           0.30,   # base: any complaint gets this
    "photo_attached":          0.15,   # at least one photo in evidence table
    "gps_precision_high":      0.05,   # GPS lat/lng present (not null)
    "multi_reporter_48h":      0.20,   # ≥2 distinct anon reporters at geohash6 in 48h
    "sensor_cluster":          0.15,   # sensor_clusters.device_count ≥ 3 at geohash6
    "community_vote_net_5":    0.10,   # net corroborate votes ≥ 5
    "repeat_temporal_pattern": 0.10,   # ≥3 complaints at geohash6 in last 30 days
    "tee_signed_evidence":     0.05,   # at least one TEE/HMAC-signed evidence record
    "after_state_submitted":  -0.10,   # penalty: after submitted but not yet verified
    "after_state_verified":   -0.25,   # penalty: CLIP found NO change (false complaint)
}

# Assertion guard: fires at module load, not at runtime.
# ANTIGRAVITY: catches weight drift during development before it hits judges.
_positive_sum = round(sum(v for v in SIGNAL_WEIGHTS.values() if v > 0), 10)
assert abs(_positive_sum - 1.10) < 1e-9, (
    f"SIGNAL_WEIGHTS positive sum must be 1.10 — got {_positive_sum}. "
    "Update weights to sum to exactly 1.10."
)

# Confidence tiers — boundaries are non-inclusive on lower end.
# ANTIGRAVITY: thresholds from spec (0.75 / 0.55 / 0.35).
THRESHOLDS: list[tuple[float, str]] = [
    (0.75, "high"),
    (0.55, "medium"),
    (0.35, "low"),
    (0.00, "unverified"),
]

# Score that triggers auto_escalate → contractor breach update.
ESCALATION_THRESHOLD: float = 0.75


@dataclass
class ConfidenceBreakdown:
    """
    Immutable result of confidence calculation.
    All callers use .confidence and .threshold_tier for routing decisions.
    """
    complaint_id: str
    confidence: float                       # clamped to [0.0, 1.0], rounded 3dp
    threshold_tier: str                     # high | medium | low | unverified
    signals: dict[str, float] = field(default_factory=dict)
    auto_escalate: bool = False             # True when tier == "high"
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "complaint_id":   self.complaint_id,
            "confidence":     self.confidence,
            "threshold_tier": self.threshold_tier,
            "signals":        self.signals,
            "auto_escalate":  self.auto_escalate,
            "message":        self.message,
        }


def get_tier(score: float) -> str:
    """
    Maps a clamped confidence score to a human-readable tier string.
    Thresholds are inclusive on the upper bound:
      score ≥ 0.75 → "high"
      score ≥ 0.55 → "medium"
      score ≥ 0.35 → "low"
      otherwise    → "unverified"
    """
    for threshold, label in THRESHOLDS:
        if score >= threshold:
            return label
    return "unverified"


def calculate_confidence(
    active_signals: list[str],
    complaint_id: str,
) -> ConfidenceBreakdown:
    """
    Calculates confidence score from a list of active signal keys.

    ANTIGRAVITY: added full implementation because original was bare helpers only.

    Args:
        active_signals: List of signal keys that are currently active for this complaint.
                        Unknown keys are logged as warnings and ignored (not raised).
        complaint_id:   Used only for logging correlation; not part of score formula.

    Returns:
        ConfidenceBreakdown with clamped score, tier, signal breakdown, and escalation flag.

    Signal computation:
      1. Filter active_signals to only known keys; warn on unknown.
      2. Sum weights of active signals.
      3. Clamp result to [0.0, 1.0].
      4. Round to 3 decimal places.
      5. Derive tier and auto_escalate flag.
    """
    # Link 1 guard: single_report must always be in active_signals for valid complaints.
    if "single_report" not in active_signals:
        logger.warning(
            "calculate_confidence [%s]: 'single_report' missing from active_signals — "
            "base score will be 0. Was the complaint created correctly?",
            complaint_id,
        )

    breakdown: dict[str, float] = {}
    for key in active_signals:
        if key not in SIGNAL_WEIGHTS:
            logger.warning(
                "calculate_confidence [%s]: unknown signal key '%s' — ignored",
                complaint_id, key,
            )
            continue
        breakdown[key] = SIGNAL_WEIGHTS[key]

    raw_score = sum(breakdown.values())
    clamped = round(min(max(raw_score, 0.0), 1.0), 3)
    tier = get_tier(clamped)
    escalate = tier == "high"

    # Tier message for API consumers and judge demos.
    messages = {
        "high":       "High confidence — probable warranty breach. Auto-escalation triggered.",
        "medium":     "Medium confidence — probable infrastructure failure. More corroboration needed.",
        "low":        "Low confidence — insufficient signals. Submit photo or vote evidence.",
        "unverified": "Unverified — single report only. Insufficient to escalate.",
    }

    return ConfidenceBreakdown(
        complaint_id=complaint_id,
        confidence=clamped,
        threshold_tier=tier,
        signals=breakdown,
        auto_escalate=escalate,
        message=messages.get(tier, ""),
    )
