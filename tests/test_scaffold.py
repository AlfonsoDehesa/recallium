import subprocess
import sys


def test_import_recollectium() -> None:
    import recollectium

    assert recollectium.__version__ == "0.1.0"


def test_module_entrypoint_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "recollectium"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
