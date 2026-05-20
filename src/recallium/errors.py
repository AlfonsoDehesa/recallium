"""Typed errors for Recallium Core."""


class RecalliumError(Exception):
    """Base class for Recallium domain errors."""


class ValidationError(RecalliumError):
    """Raised when inputs fail Recallium validation."""


class NotFoundError(RecalliumError):
    """Raised when a requested memory cannot be found."""


class EmbeddingProviderUnavailableError(RecalliumError):
    """Raised when the embedding provider runtime cannot be initialized."""


class EmbeddingModelUnavailableError(RecalliumError):
    """Raised when the configured embedding model cannot be loaded or cached."""


class EmbeddingGenerationError(RecalliumError):
    """Raised when embedding generation fails."""


class EmbeddingDimensionMismatchError(EmbeddingGenerationError):
    """Raised when the provider returns a vector with the wrong dimension."""


class EmbeddingReadinessTimeoutError(EmbeddingProviderUnavailableError):
    """Raised when embedding provider startup does not finish in time."""


class ReembeddingInProgressError(RecalliumError):
    """Raised when re-embedding must finish before search can continue."""

    def __init__(self, message: str, *, job_id: str, status_path: str) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.status_path = status_path


class ReembeddingFailedError(RecalliumError):
    """Raised when immediate re-embedding fails during runtime search."""

    def __init__(self, message: str, *, job_id: str, status_path: str) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.status_path = status_path


class MigrationError(RecalliumError):
    """Raised when database schema migration fails or is incompatible."""
