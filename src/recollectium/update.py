"""Package upgrade planning and execution for Recollectium."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Literal, Protocol, TypeGuard
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version
from platformdirs import user_state_dir

import logging

_log = logging.getLogger(__name__)

InstallMethod = Literal["bootstrap", "pip", "pipx", "uv_tool", "source", "unknown"]
CommandSpec = list[str] | list[list[str]]
UpdateStatus = Literal[
    "up_to_date",
    "update_available",
    "updated",
    "dry_run",
    "unsupported_install_method",
    "network_error",
    "update_failed",
]

_INSTALL_METHODS = {"bootstrap", "pip", "pipx", "uv_tool", "source"}
_GITHUB_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SAFE_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


class UpdateError(Exception):
    """Base class for upgrade flow errors."""


class ReleaseLookupError(UpdateError):
    """Raised when latest release lookup fails."""

    def __init__(self, message: str, *, reason: str = "release_lookup_failed") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class InstallMetadata:
    install_method: InstallMethod
    source_ref: str | None
    installed_at: str | None
    metadata_path: Path | None


@dataclass(frozen=True)
class ReleaseInfo:
    version: str | None
    tag: str
    url: str | None


@dataclass(frozen=True)
class UpdatePlan:
    status: UpdateStatus
    current_version: str
    latest_version: str | None
    latest_tag: str | None
    install_method: InstallMethod
    command: CommandSpec | None
    reason: str | None
    metadata_path: str | None
    cwd: str | None = None


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(
        self, command: list[str], *, timeout_seconds: int, cwd: str | None = None
    ) -> CommandResult: ...


class ReleaseClient(Protocol):
    def latest_release(self, repo: str) -> ReleaseInfo: ...


class GitHubReleaseClient:
    """Fetch latest release metadata from GitHub's REST API."""

    def latest_release(self, repo: str) -> ReleaseInfo:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "recollectium",
        }
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers=headers,
        )
        try:
            with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed GitHub API URL
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 404:
                raise ReleaseLookupError(
                    "No latest GitHub release found.", reason="no_latest_release"
                ) from exc
            raise ReleaseLookupError(str(exc), reason="github_http_error") from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ReleaseLookupError(str(exc)) from exc

        tag = payload.get("tag_name")
        if not isinstance(tag, str) or not tag:
            raise ReleaseLookupError(
                "Latest GitHub release did not include tag_name.",
                reason="invalid_release_payload",
            )
        return ReleaseInfo(
            version=_version_from_tag(tag), tag=tag, url=payload.get("html_url")
        )


class SubprocessCommandRunner:
    """Run package-manager commands with captured output."""

    def run(
        self, command: list[str], *, timeout_seconds: int, cwd: str | None = None
    ) -> CommandResult:
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (
                exc.stdout.decode("utf-8", errors="replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or "")
            )
            stderr = (
                exc.stderr.decode("utf-8", errors="replace")
                if isinstance(exc.stderr, bytes)
                else (
                    exc.stderr or f"command timed out after {timeout_seconds} seconds"
                )
            )
            return CommandResult(returncode=124, stdout=stdout, stderr=stderr)
        except OSError as exc:
            return CommandResult(returncode=1, stdout="", stderr=str(exc))
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def load_install_metadata(
    *, state_dir: Path | None = None, platform_name: str | None = None
) -> InstallMetadata:
    """Read bootstrap install metadata when present."""
    if state_dir is None:
        if (platform_name or platform.system()).lower().startswith("win"):
            local_app_data = os.environ.get("LOCALAPPDATA")
            state_dir = (
                Path(local_app_data) / "recollectium"
                if local_app_data
                else Path(user_state_dir("recollectium"))
            )
        else:
            state_dir = Path(user_state_dir("recollectium"))
    metadata_path = state_dir / "install.json"
    if not metadata_path.exists():
        return InstallMetadata("unknown", None, None, None)

    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return InstallMetadata("unknown", None, None, metadata_path)
    method = payload.get("install_method")
    if method not in _INSTALL_METHODS:
        method = "unknown"
    source_ref = payload.get("source_ref")
    installed_at = payload.get("installed_at")
    return InstallMetadata(
        install_method=method,  # type: ignore[arg-type]
        source_ref=source_ref if isinstance(source_ref, str) else None,
        installed_at=installed_at if isinstance(installed_at, str) else None,
        metadata_path=metadata_path,
    )


def detect_install_method(
    metadata: InstallMetadata,
    *,
    executable_path: str | None = None,
    env: dict[str, str] | None = None,
) -> InstallMethod:
    """Return bootstrap from metadata, else inspect environment and executable path."""
    if metadata.install_method != "unknown":
        return metadata.install_method

    env_map = os.environ if env is None else env
    override = env_map.get("RECOLLECTIUM_INSTALL_METHOD")
    if override in _INSTALL_METHODS:
        return override  # type: ignore[return-value]

    module_source_root = find_source_checkout_root(Path(__file__).resolve())
    if module_source_root is not None:
        return "source"

    path = (executable_path or sys.executable).replace("\\", "/").lower()
    if "/pipx/venvs/recollectium/" in path or "/pipx/" in path:
        return "pipx"
    if "/uv/tools/recollectium/" in path or "/uv/tool/" in path:
        return "uv_tool"
    if "/site-packages/" in path or "/dist-packages/" in path:
        return "pip"

    source_root = find_source_checkout_root(Path.cwd())
    if source_root is not None:
        return "source"
    if executable_path is None and sys.prefix != getattr(
        sys, "base_prefix", sys.prefix
    ):
        return "pip"
    return "unknown"


def fetch_latest_release(
    client: ReleaseClient, *, repo: str = "AlfonsoDehesa/recollectium"
) -> ReleaseInfo:
    """Return the latest GitHub release as normalized version/tag data."""
    if not is_safe_github_repo(repo):
        raise ReleaseLookupError(
            "Invalid GitHub repository path.", reason="invalid_repo"
        )
    release = client.latest_release(repo)
    _log.info(
        "Fetched latest release",
        extra={
            "event": "update.release_fetched",
            "context": {"repo": repo, "tag": release.tag, "version": release.version},
        },
    )
    return release


def build_update_plan(
    *,
    current_version: str,
    latest_release: ReleaseInfo | None,
    install_method: InstallMethod,
    metadata: InstallMetadata,
    force: bool = False,
    dry_run: bool = False,
    allow_main: bool = False,
    repo: str = "AlfonsoDehesa/recollectium",
    platform_name: str | None = None,
    source_root: Path | None = None,
) -> UpdatePlan:
    """Compare versions and return the exact update command or no-op state."""
    _log.info(
        "Building update plan",
        extra={
            "event": "update.plan_building",
            "context": {
                "current_version": current_version,
                "install_method": install_method,
                "dry_run": dry_run,
            },
        },
    )
    metadata_path = str(metadata.metadata_path) if metadata.metadata_path else None
    if install_method == "unknown":
        _log.info(
            "Update blocked — unknown install method",
            extra={
                "event": "update.unknown_install_method",
                "context": {"current_version": current_version},
            },
        )
        return UpdatePlan(
            "unsupported_install_method",
            current_version,
            None,
            None,
            install_method,
            None,
            "unknown_install_method",
            metadata_path,
        )

    if not is_safe_github_repo(repo):
        _log.info(
            "Update blocked — invalid repo",
            extra={"event": "update.invalid_repo", "context": {"repo": repo}},
        )
        return UpdatePlan(
            "unsupported_install_method",
            current_version,
            None,
            None,
            install_method,
            None,
            "invalid_repo",
            metadata_path,
        )

    latest_tag = latest_release.tag if latest_release else None
    latest_version = latest_release.version if latest_release else None
    if latest_tag is None:
        if allow_main and install_method in {"bootstrap", "source"}:
            latest_tag = "main"
            latest_version = None
        else:
            return UpdatePlan(
                "network_error",
                current_version,
                None,
                None,
                install_method,
                None,
                "no_latest_release",
                metadata_path,
            )

    if not is_safe_ref(latest_tag):
        return UpdatePlan(
            "unsupported_install_method",
            current_version,
            latest_version,
            latest_tag,
            install_method,
            None,
            "invalid_release_ref",
            metadata_path,
        )

    if install_method == "source" and source_root is None:
        source_root = find_source_checkout_root(Path(__file__).resolve())
        if source_root is None:
            return UpdatePlan(
                "update_failed",
                current_version,
                latest_version,
                latest_tag,
                install_method,
                None,
                "source_checkout_not_found",
                metadata_path,
            )

    if latest_version is not None and not force:
        try:
            if Version(latest_version) <= Version(_public_version(current_version)):
                _log.info(
                    "Update not needed — already up to date",
                    extra={
                        "event": "update.up_to_date",
                        "context": {
                            "current_version": current_version,
                            "latest_version": latest_version,
                        },
                    },
                )
                return UpdatePlan(
                    "up_to_date",
                    current_version,
                    latest_version,
                    latest_tag,
                    install_method,
                    None,
                    None,
                    metadata_path,
                )
        except InvalidVersion:
            return UpdatePlan(
                "unsupported_install_method",
                current_version,
                latest_version,
                latest_tag,
                install_method,
                None,
                "could_not_parse_current_version",
                metadata_path,
            )

    command, cwd = _command_for_method(
        install_method,
        latest_tag=latest_tag,
        repo=repo,
        platform_name=platform_name,
        source_root=source_root,
    )
    plan_status = "dry_run" if dry_run else "update_available"
    _log.info(
        "Update plan complete",
        extra={
            "event": "update.plan_ready",
            "context": {
                "status": plan_status,
                "current_version": current_version,
                "latest_version": latest_version,
                "install_method": install_method,
            },
        },
    )
    return UpdatePlan(
        plan_status,
        current_version,
        latest_version,
        latest_tag,
        install_method,
        command,
        "main_fallback_allowed" if latest_tag == "main" else "update_available",
        metadata_path,
        cwd=str(cwd) if cwd else None,
    )


def apply_update(
    plan: UpdatePlan, *, runner: CommandRunner, timeout_seconds: int = 600
) -> CommandResult:
    """Run the plan command and return captured output."""
    if plan.command is None:
        _log.info(
            "Update skipped — nothing to apply",
            extra={"event": "update.apply_skipped", "context": {"status": plan.status}},
        )
        return CommandResult(0, "", "")
    _log.info(
        "Applying update",
        extra={
            "event": "update.applying",
            "context": {
                "install_method": plan.install_method,
                "latest_version": plan.latest_version,
            },
        },
    )
    if plan.install_method == "source":
        if plan.cwd is None:
            return CommandResult(1, "", "source checkout not found")
        dirty = runner.run(
            ["git", "status", "--porcelain"],
            timeout_seconds=timeout_seconds,
            cwd=plan.cwd,
        )
        if dirty.returncode != 0:
            return dirty
        if dirty.stdout.strip():
            _log.error(
                "Update blocked — source checkout dirty",
                extra={"event": "update.source_dirty", "context": {}},
            )
            return CommandResult(
                1,
                "",
                "source checkout has uncommitted changes (source_checkout_dirty)",
            )
        commands = plan.command if _is_command_sequence(plan.command) else []
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        for command in commands:
            executable = command[0]
            if shutil.which(executable) is None:
                return CommandResult(1, "", f"{executable} is not available on PATH")
            result = runner.run(command, timeout_seconds=timeout_seconds, cwd=plan.cwd)
            stdout_parts.append(result.stdout)
            stderr_parts.append(result.stderr)
            if result.returncode != 0:
                _log.error(
                    "Update command failed",
                    extra={
                        "event": "update.command_failed",
                        "context": {
                            "returncode": result.returncode,
                            "command": command,
                        },
                    },
                )
                return CommandResult(
                    result.returncode, "".join(stdout_parts), "".join(stderr_parts)
                )
        return CommandResult(0, "".join(stdout_parts), "".join(stderr_parts))

    command = plan.command if _is_single_command(plan.command) else []
    executable = command[0]
    if shutil.which(executable) is None:
        _log.error(
            "Update blocked — executable not found",
            extra={
                "event": "update.executable_missing",
                "context": {"executable": executable},
            },
        )
        return CommandResult(1, "", f"{executable} is not available on PATH")
    result = runner.run(command, timeout_seconds=timeout_seconds, cwd=plan.cwd)
    if result.returncode == 0:
        _log.info(
            "Update applied successfully",
            extra={
                "event": "update.apply_succeeded",
                "context": {
                    "install_method": plan.install_method,
                    "latest_version": plan.latest_version,
                },
            },
        )
    else:
        _log.error(
            "Update failed",
            extra={
                "event": "update.apply_failed",
                "context": {
                    "returncode": result.returncode,
                    "stderr": result.stderr[:200],
                },
            },
        )
    return result


def plan_to_dict(plan: UpdatePlan) -> dict[str, object]:
    """Return a JSON-ready plan dict."""
    return {
        "status": plan.status,
        "current_version": plan.current_version,
        "latest_version": plan.latest_version,
        "latest_tag": plan.latest_tag,
        "install_method": plan.install_method,
        "command": plan.command,
        "reason": plan.reason,
        "metadata_path": plan.metadata_path,
        "cwd": plan.cwd,
    }


def find_source_checkout_root(start: Path) -> Path | None:
    """Return nearest parent containing pyproject and .git for Recollectium."""
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists() and (candidate / "pyproject.toml").exists():
            try:
                text = (candidate / "pyproject.toml").read_text(encoding="utf-8")
            except OSError:
                continue
            if 'name = "recollectium"' in text:
                return candidate
    return None


def _version_from_tag(tag: str) -> str | None:
    normalized = tag[1:] if tag.startswith("v") else tag
    try:
        return str(Version(normalized))
    except InvalidVersion:
        return None


def _public_version(version: str) -> str:
    return str(Version(version).public)


def _command_for_method(
    install_method: InstallMethod,
    *,
    latest_tag: str,
    repo: str,
    platform_name: str | None,
    source_root: Path | None,
) -> tuple[CommandSpec, Path | None]:
    if install_method == "pip":
        return [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "recollectium",
        ], None
    if install_method == "pipx":
        return ["pipx", "upgrade", "recollectium"], None
    if install_method == "uv_tool":
        return ["uv", "tool", "upgrade", "recollectium"], None
    if install_method == "source":
        root = source_root or find_source_checkout_root(Path(__file__).resolve())
        return [["git", "pull", "--ff-only"], ["uv", "sync", "--group", "dev"]], root
    if install_method == "bootstrap":
        if (platform_name or platform.system()).lower().startswith("win"):
            script = (
                f"https://raw.githubusercontent.com/{repo}/{latest_tag}/install.ps1"
            )
            return [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-c",
                f"irm {script} | iex",
            ], None
        script = f"https://raw.githubusercontent.com/{repo}/{latest_tag}/install.sh"
        return ["sh", "-c", f"curl -LsSf {script} | sh"], None
    return [], None


def is_safe_github_repo(repo: str) -> bool:
    """Return True when repo is a safe GitHub OWNER/REPO path."""
    return bool(_GITHUB_REPO_PATTERN.fullmatch(repo))


def is_safe_ref(ref: str) -> bool:
    """Return True when a release tag/source ref is safe for raw GitHub URLs."""
    return (
        bool(_SAFE_REF_PATTERN.fullmatch(ref))
        and ".." not in ref
        and "@{" not in ref
        and not ref.endswith((".", "/"))
    )


def _is_single_command(command: CommandSpec) -> TypeGuard[list[str]]:
    return bool(command) and isinstance(command[0], str)


def _is_command_sequence(command: CommandSpec) -> TypeGuard[list[list[str]]]:
    return bool(command) and isinstance(command[0], list)
