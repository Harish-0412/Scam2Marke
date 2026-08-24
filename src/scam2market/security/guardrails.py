import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(prior|previous)\s+instructions", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(prior|previous)\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(in\s+)?(developer|admin|root)\s+mode", re.IGNORECASE),
    re.compile(r"reveal\s+(the\s+)?(system|developer)\s+prompt", re.IGNORECASE),
    re.compile(r"<\s*(system|assistant|tool)\s*>", re.IGNORECASE),
    re.compile(r"</\s*(system|assistant|tool)\s*>", re.IGNORECASE),
    re.compile(r"jailbreak|prompt\s+injection", re.IGNORECASE),
    re.compile(r"print\s+(the\s+)?hidden\s+(prompt|policy)", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class GuardrailDecision:
    accepted: bool
    reasons: tuple[str, ...]
    risk_score: float


def inspect_untrusted_text(text: str, *, max_length: int = 20_000) -> GuardrailDecision:
    reasons: list[str] = []
    if len(text) > max_length:
        reasons.append("TEXT_TOO_LARGE")
    if any(pattern.search(text) for pattern in _INJECTION_PATTERNS):
        reasons.append("PROMPT_INJECTION_PATTERN")
    control_count = sum(ord(char) < 32 and char not in "\n\r\t" for char in text)
    if control_count:
        reasons.append("CONTROL_CHARACTERS")
    normalized_words = text.lower().split()
    if len(normalized_words) >= 50 and len(set(normalized_words)) / len(normalized_words) < 0.08:
        reasons.append("REPETITIVE_CONTENT")
    return GuardrailDecision(not reasons, tuple(reasons), min(1.0, len(reasons) * 0.35))


def inspect_ingestion_payload(
    payload: dict[str, Any],
    *,
    event_time: datetime,
    source_trust: float,
    now: datetime | None = None,
) -> GuardrailDecision:
    reasons: list[str] = []
    current = now or datetime.now(tz=UTC)
    observed = event_time if event_time.tzinfo is not None else event_time.replace(tzinfo=UTC)
    if observed > current + timedelta(minutes=5):
        reasons.append("FUTURE_EVENT_TIME")
    if not 0 <= source_trust <= 1:
        reasons.append("INVALID_SOURCE_TRUST")
    elif source_trust < 0.25:
        reasons.append("LOW_TRUST_SOURCE")
    if len(str(payload)) > 1_000_000:
        reasons.append("PAYLOAD_TOO_LARGE")
    return GuardrailDecision(not reasons, tuple(reasons), min(1.0, len(reasons) * 0.4))
