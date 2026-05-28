"""Recollectium Core package."""

from importlib.metadata import PackageNotFoundError, version

from recollectium.config import RecollectiumConfig
from recollectium.core import RecollectiumCore
from recollectium.errors import (
    MigrationError,
    NotFoundError,
    RecollectiumError,
    ServiceConflictError,
    ServiceError,
    ValidationError,
)
from recollectium.logging import get_logger, setup_logging
from recollectium.models import (
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
    "RecollectiumConfig",
    "RecollectiumCore",
    "RecollectiumError",
    "SearchResult",
    "ValidationError",
    "NotFoundError",
    "MigrationError",
    "ServiceError",
    "ServiceConflictError",
    "SPACE_USER",
    "SPACE_WORKSPACE",
    "STATUS_ACTIVE",
    "STATUS_ARCHIVED",
    "get_logger",
    "setup_logging",
]

try:
    __version__ = version("recollectium")
except PackageNotFoundError:  # pragma: no cover - source tree fallback
    __version__ = "0.1.0"
