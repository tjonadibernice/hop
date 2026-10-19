"""Guardrails: the rules that turn the agent's request into a page status.

The agent only proposes. These plain-code rules decide, so a page that
talks the model into "approve" still can't get past them:

- Safe Browsing said unsafe -> rejected, whatever the agent asked for.
- "approve" needs a completed Safe Browsing check, at least one known topic,
  and quality of at least 0.6 (the same bar as automatic approval).
  Otherwise the page goes to a person instead.
- No decision at all (turn limit, no answer) -> a person decides.
"""

from dataclasses import dataclass, field

from app.curator.tools import SubmitDecision
from app.ingestion.enrich import APPROVE_QUALITY, MAX_TOPICS
from app.ingestion.safety import SafetyResult


@dataclass(frozen=True)
class PolicyOutcome:
    proposed: str  # what the agent asked for (escalate when it gave nothing)
    status: str  # approved, rejected, or needs_review
    reason: str
    blocked_by: str | None = None  # the guardrail that overrode the agent
    topics: list[str] = field(default_factory=list)
    quality: float | None = None


def apply_policy(
    proposal: SubmitDecision | None,
    *,
    safety: SafetyResult,
    known_topics: set[str],
    stop_reason: str | None = None,
) -> PolicyOutcome:
    if proposal is None:
        return PolicyOutcome(
            "escalate",
            "needs_review",
            f"curator gave no decision ({stop_reason or 'unknown reason'})",
        )

    reason = f"curator: {proposal.reason.strip()}"
    if not safety.safe:
        blocked = (
            None
            if proposal.decision == "reject"
            else f"safety check: {safety.reason or 'unsafe'}"
        )
        return PolicyOutcome(
            proposal.decision,
            "rejected",
            reason if blocked is None else f"unsafe ({safety.reason or 'flagged'})",
            blocked_by=blocked,
            quality=proposal.quality,
        )
    if proposal.decision == "reject":
        return PolicyOutcome("reject", "rejected", reason, quality=proposal.quality)
    if proposal.decision == "escalate":
        return PolicyOutcome(
            "escalate", "needs_review", reason, quality=proposal.quality
        )

    # "approve": only if every rule holds
    topics = list(dict.fromkeys(t for t in proposal.topics if t in known_topics))
    topics = topics[:MAX_TOPICS]
    blocked = None
    if not safety.checked:
        blocked = "no Safe Browsing check"
    elif not topics:
        blocked = "no known topic"
    elif proposal.quality < APPROVE_QUALITY:
        blocked = f"quality {proposal.quality:.2f} is below {APPROVE_QUALITY}"
    if blocked is not None:
        return PolicyOutcome(
            "approve",
            "needs_review",
            f"{reason} (approval blocked: {blocked})",
            blocked_by=blocked,
            topics=topics,
            quality=proposal.quality,
        )
    return PolicyOutcome(
        "approve", "approved", reason, topics=topics, quality=proposal.quality
    )
