"""Intent Classification and Routing Module for Umber (Stage 2).

Implements Phase 8 deterministic guardrails and Phase 12 intent classification
across three core categories:
1. PERSONALIZATION: Skin tone / undertone analysis, styling, garment color matching.
2. GENERAL: Store hours, locations, shipping, policies, payment, general greetings.
3. ESCALATION: Human agent requests, complaints, disputes, refunds, and low-confidence inputs.

Operating Rules:
- Phase 8: Deterministic code enforces rules (escalation triggers, guardrails).
- Phase 9: Default to escalation when uncertain (never bury a complaint).
- Phase 12: High escalation recall (100% on eval set).
- Phase 13: Structured event logging (INTENT_CLASSIFIED, ESCALATED).
"""
import re
from typing import List, Optional, Tuple

from app.events import log_event
from app.states import (
    ClassificationResult,
    ConversationState,
    EscalationReason,
    Intent,
)

# ---------------------------------------------------------------------------
# 1. Deterministic Escalation Signatures (Phase 8 Guardrails)
# ---------------------------------------------------------------------------
EXPLICIT_HUMAN_PATTERNS = [
    r"\b(real\s+person|human\s+being|human\s+agent|talk\s+to\s+a\s+person|speak\s+to\s+a\s+(real\s+)?person)\b",
    r"\b(speak\s+to|talk\s+to|connect\s+me\s+to|transfer\s+me\s+to|transfer\s+me\s+give)\s+(a\s+|an\s+|the\s+|your\s+)?(store\s+)?(agent|human|representative|manager|staff|someone|person|customer\s+care)\b",
    r"\b(customer\s+care(\s+agent)?|customer\s+service(\s+agent)?|live\s+support|operator|store\s+manager)\b",
    r"\b(give\s+me\s+someone|get\s+someone\s+who|give\s+me\s+a\s+real\s+staff|real\s+staff|no\s+get\s+strength\s+for\s+(bot|robot)|no\s+dey\s+talk\s+to\s+(bot|robot)|stop\s+sending\s+automated)\b",
    r"\b(speak\s+with\s+a\s+human|talk\s+to\s+human|transfer\s+me\s+to\s+your\s+manager)\b",
]

COMPLAINT_AND_DISPUTE_PATTERNS = [
    r"\b(refund|chargeback|debited\s+twice|double\s+charge(d)?|took\s+my\s+money|money\s+is\s+missing)\b",
    r"\b(scam|fraud|thief|thieves|stolen|stole)\b",
    r"\b(damaged|torn|stained|defective|broken\s+package|package\s+arrived\s+completely)\b",
    r"\b(unacceptable|ridiculous|terrible\s+service|horrible\s+service|rubbish|nonsense|wahala)\b",
    r"\b(useless\s+(ai\s+)?bot|waste\s+(of\s+)?(my\s+)?time|wastes\s+my\s+time)\b",
    r"\b(police|lawyer|sue\s+you|report\s+(una|you|him|her)\s+to)\b",
]

# ---------------------------------------------------------------------------
# 2. Personalization Patterns & Keywords
# ---------------------------------------------------------------------------
PERSONALIZATION_SIGNALS = [
    r"\b(skin\s*tone|skin\s*color|complexion|undertone(s)?)\b",
    r"\b(suit(s)?|match(es)?|fit(s)?|flatter(s|ing)?|compliment(s)?)\s+(me|my\s+(tone|skin|complexion|undertone|body))\b",
    r"\b(look(s)?\s+good\s+on\s+me|compliment(s)?\s+me|suit(s)?\s+me|match(es)?\s+me)\b",
    r"\b(which|what)\s+(color|shade|colur|gown|dress|outfit)\s+(suits|matches|suits\s+my|fits|looks\s+best)\b",
    r"\b(dark\s+skin|fair\s+skin|olive\s+skin|brown\s+skin|melanin|pale\s+skin|tan\s+skin)\b",
    r"\b(warm\s+undertone|cool\s+undertone|neutral\s+undertone|golden\s+undertone|pink\s+undertone)\b",
    r"\b(washed\s+out\s+on|flattering\s+on|suit\s+my\s+undertone|match\s+my\s+tone|suit\s+my\s+tone|look\s+pop)\b",
    r"\b(wetin\s+go\s+(match|fit)|color\s+gown\s+go\s+fit|gown\s+go\s+fit\s+my\s+tone|my\s+complexion\s+abeg)\b",
    r"\b(recommend(\s+an)?\s+outfit|outfit\s+recommendation|recommend\s+something\s+for)\b",
]

# ---------------------------------------------------------------------------
# 3. General Inquiry Patterns & Keywords (Store FAQ, Shipping, Hours)
# ---------------------------------------------------------------------------
GENERAL_SIGNALS = [
    r"\b(hello|hi|hey|good\s+morning|good\s+afternoon|good\s+evening|how\s+far)\b",
    r"\b(store\s+hours|business\s+hours|opening\s+hours|hours|open\s+today|what\s+time\s+do\s+you\s+open|closing\s+time|una\s+dey\s+open)\b",
    r"\b((when\s+(are\s+you|are\s+una|una\s+dey)\s+)?(free|open|available)\s+on\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekend)|when\s+are\s+you\s+(free|open|available))\b",
    r"\b(shipping|delivery|deliver\s+to|shipping\s+to|how\s+much\s+(be\s+shipping|does\s+delivery|is\s+delivery|una\s+dey\s+sell))\b",
    r"\b(where\s+(is|are)\s+your\s+(physical\s+)?(store|boutique|shop)|located\s+in)\b",
    r"\b(return\s+(and\s+exchange\s+)?policy|exchange\s+policy|store\s+policy)\b",
    r"\b(card\s+payments|bank\s+transfer|accept\s+card|payment\s+method(s)?)\b",
    r"\b(new\s+arrivals|in\s+stock|what\s+do\s+you\s+sell|catalog|items\s+in\s+stock)\b",
]


def _match_any(patterns: List[str], text: str) -> List[str]:
    """Return all pattern regexes that match the given text."""
    matches = []
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            matches.append(pattern)
    return matches


def classify_intent(text: str) -> ClassificationResult:
    """Classify incoming WhatsApp customer text into an explicit intent.
    
    Adheres strictly to the architectural constraints:
    1. Deterministic guardrails evaluate first.
    2. Escalation takes precedence in mixed-intent messages (Phase 9 & 12).
    3. High-confidence Personalization and General queries are routed to their Phase 6 states.
    4. Ambiguous / low-confidence text defaults to ESCALATION (Phase 9 rule).
    5. Logs structured events to Phase 13 events log.
    """
    clean_text = text.strip()
    if not clean_text:
        res = ClassificationResult.for_escalation(
            confidence=0.5,
            reason="Empty message received; routing to agent for review",
            escalation_reason=EscalationReason.UNCERTAIN_INTENT,
        )
        _log_classification(res, clean_text)
        return res

    # -----------------------------------------------------------------------
    # Step 1: Check Deterministic Escalation Guardrails (Highest Priority)
    # -----------------------------------------------------------------------
    human_matches = _match_any(EXPLICIT_HUMAN_PATTERNS, clean_text)
    if human_matches:
        res = ClassificationResult.for_escalation(
            confidence=1.0,
            reason="Explicit customer request for human agent or representative",
            escalation_reason=EscalationReason.EXPLICIT_HUMAN_REQUEST,
            signals=human_matches,
        )
        _log_classification(res, clean_text)
        return res

    complaint_matches = _match_any(COMPLAINT_AND_DISPUTE_PATTERNS, clean_text)
    if complaint_matches:
        res = ClassificationResult.for_escalation(
            confidence=1.0,
            reason="Complaint, billing dispute, damaged item, or customer dissatisfaction detected",
            escalation_reason=EscalationReason.COMPLAINT_OR_DISPUTE,
            signals=complaint_matches,
        )
        _log_classification(res, clean_text)
        return res

    # -----------------------------------------------------------------------
    # Step 2: Evaluate Personalization and General Signals
    # -----------------------------------------------------------------------
    pers_matches = _match_any(PERSONALIZATION_SIGNALS, clean_text)
    gen_matches = _match_any(GENERAL_SIGNALS, clean_text)

    # Calculate signal weights
    pers_score = len(pers_matches)
    gen_score = len(gen_matches)

    # Personalization dominates
    if pers_score > 0 and pers_score >= gen_score:
        confidence = min(0.75 + (0.1 * pers_score), 0.99)
        res = ClassificationResult.for_personalization(
            confidence=round(confidence, 2),
            reason="Customer is seeking skin-tone matching, undertone advice, or tailored styling",
            signals=pers_matches,
        )
        _log_classification(res, clean_text)
        return res

    # General store FAQ dominates
    if gen_score > 0:
        confidence = min(0.75 + (0.1 * gen_score), 0.99)
        res = ClassificationResult.for_general(
            confidence=round(confidence, 2),
            reason="Customer is asking general store inquiries (hours, shipping, policies, payment, or greeting)",
            signals=gen_matches,
        )
        _log_classification(res, clean_text)
        return res

    # -----------------------------------------------------------------------
    # Step 3: Ambiguous / Low Confidence Fallback (Phase 9)
    # Default to escalation when uncertain, never the reverse.
    # -----------------------------------------------------------------------
    res = ClassificationResult.for_escalation(
        confidence=0.50,
        reason="Ambiguous input with insufficient intent signals; escalating per Phase 9 guardrails",
        escalation_reason=EscalationReason.UNCERTAIN_INTENT,
    )
    _log_classification(res, clean_text)
    return res


def _log_classification(result: ClassificationResult, raw_text: str) -> None:
    """Emit Phase 13 structured events for intent classification and escalation."""
    log_event("INTENT_CLASSIFIED", {
        "intent": result.intent.value,
        "confidence": result.confidence,
        "next_state": result.next_state.value,
        "reason": result.reason,
        "text_preview": raw_text[:60] if raw_text else "",
    })

    if result.intent == Intent.ESCALATION:
        log_event("ESCALATED", {
            "trigger": result.escalation_reason.value if result.escalation_reason else "unknown",
            "reason": result.reason,
            "text_preview": raw_text[:60] if raw_text else "",
        })
