"""Recallium Core package."""

from recallium.core import RecalliumCore
from recallium.errors import NotFoundError, RecalliumError, ValidationError
from recallium.models import (
    SPACE_USER,
    SPACE_WORKSPACE,
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    Memory,
    SearchResult,
)

__all__ = [
    "__version__",
    "Memory",
    "SearchResult",
    "RecalliumCore",
    "RecalliumError",
    "ValidationError",
    "NotFoundError",
    "SPACE_USER",
    "SPACE_WORKSPACE",
    "STATUS_ACTIVE",
    "STATUS_ARCHIVED",
]

__version__ = "0.1.0"
