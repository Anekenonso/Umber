"""Stage 2 Intent Classification Test Suite & Benchmark (Phase 11 & Phase 12).

Tests:
1. Benchmark against the 28-message eval set (`tests/eval_set.json`).
   - Asserts overall routing accuracy >= 95%.
   - Asserts escalation recall == 100% (zero missed complaints or human asks).
   - Dumps execution report to `evidence/eval-results/stage2_eval.json`.
2. Deterministic escalation guardrail verification (explicit human requests).
3. Complaint and billing dispute guardrail verification.
4. Mixed intent escalation priority (Phase 9 & 12: complaints take precedence over styling).
5. Nigerian Pidgin and code-switched phrasing across all three classes.
6. Phase 9 low-confidence fallback to escalation.
7. Phase 6 explicit conversation state mapping.
8. Phase 13 structured event logging.
"""
import json
from pathlib import Path
import pytest
from unittest.mock import patch

from app.classifier import classify_intent
from app.states import (
    ClassificationResult,
    ConversationState,
    EscalationReason,
    Intent,
)

EVAL_SET_PATH = Path(__file__).resolve().parent / "eval_set.json"
EVAL_RESULTS_DIR = Path(__file__).resolve().parent.parent / "evidence" / "eval-results"


def test_eval_set_accuracy_and_escalation_recall():
    """Evaluate classifier against Phase 12 labeled evaluation set.
    
    Hard claims:
    - Overall routing accuracy >= 90% (target: 95%+)
    - Escalation recall == 100% (a missed complaint is unacceptable)
    """
    assert EVAL_SET_PATH.exists(), f"Evaluation set not found at {EVAL_SET_PATH}"
    
    with open(EVAL_SET_PATH, "r", encoding="utf-8") as f:
        eval_cases = json.load(f)

    total = len(eval_cases)
    correct = 0
    
    escalation_total = 0
    escalation_detected = 0
    
    detailed_results = []

    for item in eval_cases:
        text = item["text"]
        expected = item["expected_intent"]
        
        result = classify_intent(text)
        predicted = result.intent.value
        is_match = (predicted == expected)
        
        if is_match:
            correct += 1
            
        if expected == "escalation":
            escalation_total += 1
            if predicted == "escalation":
                escalation_detected += 1

        detailed_results.append({
            "id": item["id"],
            "text": text,
            "category": item.get("category", ""),
            "expected": expected,
            "predicted": predicted,
            "match": is_match,
            "confidence": result.confidence,
            "reason": result.reason,
            "next_state": result.next_state.value,
        })

    accuracy = correct / total
    escalation_recall = escalation_detected / escalation_total if escalation_total > 0 else 1.0

    # Save benchmark artifact to evidence/eval-results/
    EVAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_report = {
        "total_samples": total,
        "correct_predictions": correct,
        "overall_accuracy": round(accuracy * 100, 2),
        "escalation_total": escalation_total,
        "escalation_detected": escalation_detected,
        "escalation_recall": round(escalation_recall * 100, 2),
        "results": detailed_results,
    }
    
    with open(EVAL_RESULTS_DIR / "stage2_eval.json", "w", encoding="utf-8") as f:
        json.dump(summary_report, f, indent=2)

    # Enforce Phase 12 acceptance criteria
    assert accuracy >= 0.95, f"Overall accuracy {accuracy:.2%} is below required 95%"
    assert escalation_recall == 1.0, f"Escalation recall {escalation_recall:.2%} must be 100%"


def test_explicit_human_agent_escalations():
    """Verify explicit human agent requests trigger immediate escalation with high confidence."""
    human_queries = [
        "I need to speak with a human agent right away",
        "Please connect me to customer service",
        "Transfer me to your store manager",
        "Can I talk to a real person please?",
        "Stop sending automated messages, give me a real staff",
    ]
    for q in human_queries:
        res = classify_intent(q)
        assert res.intent == Intent.ESCALATION
        assert res.next_state == ConversationState.ESCALATED
        assert res.confidence == 1.0
        assert res.escalation_reason == EscalationReason.EXPLICIT_HUMAN_REQUEST


def test_complaint_and_billing_escalations():
    """Verify complaints and financial disputes trigger immediate escalation."""
    complaint_queries = [
        "My order was double debited and I demand a refund now",
        "The dress arrived completely damaged and torn!",
        "This company is a scam, where is my package?!",
        "Your service is terrible and unacceptable",
    ]
    for q in complaint_queries:
        res = classify_intent(q)
        assert res.intent == Intent.ESCALATION
        assert res.next_state == ConversationState.ESCALATED
        assert res.confidence == 1.0
        assert res.escalation_reason == EscalationReason.COMPLAINT_OR_DISPUTE


def test_mixed_intent_prioritizes_escalation():
    """Verify mixed intent queries prioritize escalation over personalization (Phase 9 & 12)."""
    mixed_query = (
        "I wanted to see what yellow gown suits my warm undertone, but your courier "
        "was so rude and I was double charged, so I want my money refunded immediately!"
    )
    res = classify_intent(mixed_query)
    assert res.intent == Intent.ESCALATION
    assert res.next_state == ConversationState.ESCALATED
    assert res.escalation_reason == EscalationReason.COMPLAINT_OR_DISPUTE


def test_pidgin_code_switching_support():
    """Verify Nigerian Pidgin expressions are accurately routed across all three intents."""
    # Personalization
    res_pers = classify_intent("Wetin go match my dark complexion abeg?")
    assert res_pers.intent == Intent.PERSONALIZATION
    assert res_pers.next_state == ConversationState.AWAITING_PHOTO

    # General
    res_gen = classify_intent("Una dey open today?")
    assert res_gen.intent == Intent.GENERAL
    assert res_gen.next_state == ConversationState.GENERAL_REPLY

    # Escalation
    res_esc = classify_intent("Abeg transfer me give human being, I no get strength for robot")
    assert res_esc.intent == Intent.ESCALATION
    assert res_esc.next_state == ConversationState.ESCALATED


def test_ambiguous_fallback_to_escalation():
    """Verify ambiguous, unclassifiable or empty input defaults to escalation (Phase 9)."""
    ambiguous_inputs = [
        "",
        "   ",
        "xyz 123 qwerty whatever",
        "hmm maybe later perhaps",
    ]
    for text in ambiguous_inputs:
        res = classify_intent(text)
        assert res.intent == Intent.ESCALATION
        assert res.next_state == ConversationState.ESCALATED
        assert res.escalation_reason == EscalationReason.UNCERTAIN_INTENT


def test_phase6_state_mapping():
    """Verify that every intent maps to the appropriate Phase 6 ConversationState."""
    res_pers = classify_intent("Which shade matches my skin tone best?")
    assert res_pers.next_state == ConversationState.AWAITING_PHOTO

    res_gen = classify_intent("What are your store hours?")
    assert res_gen.next_state == ConversationState.GENERAL_REPLY

    res_esc = classify_intent("I want to speak with an agent")
    assert res_esc.next_state == ConversationState.ESCALATED


def test_phase13_event_logging():
    """Verify structured event logging on classification."""
    with patch("app.classifier.log_event") as mock_log:
        res = classify_intent("Does this suit my tone?")
        assert res.intent == Intent.PERSONALIZATION
        
        # Verify INTENT_CLASSIFIED event was called
        mock_log.assert_called_with(
            "INTENT_CLASSIFIED",
            {
                "intent": "personalization",
                "confidence": res.confidence,
                "next_state": "AWAITING_PHOTO",
                "reason": res.reason,
                "text_preview": "Does this suit my tone?",
            },
        )
