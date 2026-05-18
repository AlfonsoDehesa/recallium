"""Typed errors for Recallium Core."""


class RecalliumError(Exception):
    """Base class for Recallium domain errors."""


class ValidationError(RecalliumError):
    """Raised when inputs fail Recallium validation."""


class NotFoundError(RecalliumError):
    """Raised when a requested memory cannot be found."""
