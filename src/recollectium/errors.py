"""Typed errors for Recollectium Core."""


class RecollectiumError(Exception):
    """Base class for Recollectium domain errors."""


class ValidationError(RecollectiumError):
    """Raised when inputs fail Recollectium validation."""


class NotFoundError(RecollectiumError):
    """Raised when a requested memory cannot be found."""


class EmbeddingProviderUnavailableError(RecollectiumError):
    """Raised when the embedding provider runtime cannot be initialized."""


class EmbeddingModelUnavailableError(RecollectiumError):
    """Raised when the configured embedding model cannot be loaded or cached."""


class EmbeddingGenerationError(RecollectiumError):
    """Raised when embedding generation fails."""


class EmbeddingDimensionMismatchError(EmbeddingGenerationError):
    """Raised when the provider returns a vector with the wrong dimension."""


class EmbeddingReadinessTimeoutError(EmbeddingProviderUnavailableError):
    """Raised when embedding provider startup does not finish in time."""


class ReembeddingInProgressError(RecollectiumError):
    """Raised when re-embedding must finish before search can continue."""

    def __init__(self, message: str, *, job_id: str, status_path: str) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.status_path = status_path


class ReembeddingFailedError(RecollectiumError):
    """Raised when immediate re-embedding fails during runtime search."""

    def __init__(self, message: str, *, job_id: str, status_path: str) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.status_path = status_path


class MigrationError(RecollectiumError):
    """Raised when database schema migration fails or is incompatible."""


class ServiceError(RecollectiumError):
    """Base class for service lifecycle errors."""


class ServiceConflictError(ServiceError):
    """Raised when starting a conflicting service while another is running."""
