from pathlib import Path

import pytest

from recollectium.core import RecollectiumCore


@pytest.fixture(scope="session", autouse=True)
def production_embedding_runtime_is_ready(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    db_path = Path(tmp_path_factory.mktemp("embedding-readiness")) / "readiness.db"
    RecollectiumCore(db_path=db_path).ensure_embedding_ready(timeout_seconds=60)
