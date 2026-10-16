"""Explicit, evidence-aware terminal statuses for TAL execution."""

from enum import Enum


class OutcomeStatus(str, Enum):
    VERIFIED = "verified"
    COMPLETED_UNVERIFIED = "completed_unverified"
    FAILED = "failed"
    ESCALATED = "escalated"
    WAITING_FOR_USER = "waiting_for_user"
