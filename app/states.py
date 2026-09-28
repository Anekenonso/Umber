"""Explicit Conversation States and Intent Enums for Umber (Phase 6 & Stage 2).

Defines the state machine states, intent categories, escalation triggers,
and structured classification results.
"""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ConversationState(str, Enum):
    """Explicit conversation states from Phase 6 of the architecture worksheet.
    
    Flow:
        RECEIVED -> CLASSIFIED -> (GENERAL_REPLY | ESCALATED | AWAITING_PHOTO)
        AWAITING_PHOTO -> ANALYZING -> MATCHING -> RENDERING -> SENT
            -> (CONVERTED | ALTERNATIVE_REQUESTED -> back to MATCHING | ESCALATED)
    """
    # Inbound & routing
    RECEIVED = "RECEIVED"
    CLASSIFIED = "CLASSIFIED"
    
    # Early terminal / routing branches
    GENERAL_REPLY = "GENERAL_REPLY"
    ESCALATED = "ESCALATED"
    
    # Personalization pipeline
    AWAITING_PHOTO = "AWAITING_PHOTO"
    ANALYZING = "ANALYZING"
    ANALYZING_FAILED = "ANALYZING_FAILED"
    MATCHING = "MATCHING"
    RENDERING = "RENDERING"
    RENDERING_FAILED = "RENDERING_FAILED"
    SENT = "SENT"
    
    # Post-recommendation states
    CONVERTED = "CONVERTED"
    ALTERNATIVE_REQUESTED = "ALTERNATIVE_REQUESTED"
    ABANDONED = "ABANDONED"

    @classmethod
    def terminal_states(cls) -> set:
        """States after which no further automated pipeline processing occurs without new intent."""
        return {cls.GENERAL_REPLY, cls.ESCALATED, cls.CONVERTED, cls.ABANDONED}

    @classmethod
    def failure_states(cls) -> set:
        """States indicating an external or processing failure requiring fallback."""
        return {cls.ANALYZING_FAILED, cls.RENDERING_FAILED}


class Intent(str, Enum):
    """Customer intent categories for message classification."""
    PERSONALIZATION = "personalization"
    GENERAL = "general"
    ESCALATION = "escalation"


class EscalationReason(str, Enum):
    """Specific root triggers causing escalation to a human agent."""
    EXPLICIT_HUMAN_REQUEST = "explicit_human_request"
    COMPLAINT_OR_DISPUTE = "complaint_or_dispute"
    FRUSTRATION_OR_ANGER = "frustration_or_anger"
    UNCERTAIN_INTENT = "uncertain_intent"
    REPEATED_FAILURE = "repeated_failure"
    NOT_SATISFIED = "not_satisfied"


class ClassificationResult(BaseModel):
    """Structured output returned by the intent classifier."""
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    next_state: ConversationState
    reason: str
    escalation_reason: Optional[EscalationReason] = None
    detected_signals: List[str] = Field(default_factory=list)

    @classmethod
    def for_personalization(cls, confidence: float, reason: str, signals: Optional[List[str]] = None):
        return cls(
            intent=Intent.PERSONALIZATION,
            confidence=confidence,
            next_state=ConversationState.AWAITING_PHOTO,
            reason=reason,
            detected_signals=signals or [],
        )

    @classmethod
    def for_general(cls, confidence: float, reason: str, signals: Optional[List[str]] = None):
        return cls(
            intent=Intent.GENERAL,
            confidence=confidence,
            next_state=ConversationState.GENERAL_REPLY,
            reason=reason,
            detected_signals=signals or [],
        )

    @classmethod
    def for_escalation(
        cls,
        confidence: float,
        reason: str,
        escalation_reason: EscalationReason,
        signals: Optional[List[str]] = None,
    ):
        return cls(
            intent=Intent.ESCALATION,
            confidence=confidence,
            next_state=ConversationState.ESCALATED,
            reason=reason,
            escalation_reason=escalation_reason,
            detected_signals=signals or [],
        )
