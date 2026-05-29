from __future__ import annotations

import re
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
EXPECTED_SUBSECTIONS = ["### ✨ Features", "### 🐛 Fixes", "### 🧹 Chores"]
RELEASE_HEADING = re.compile(
    r"^## (Unreleased|v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)$"
)


def _release_sections(text: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_heading is not None:
                sections.append((current_heading, current_lines))
            current_heading = line
            current_lines = []
        elif current_heading is not None:
            current_lines.append(line)

    if current_heading is not None:
        sections.append((current_heading, current_lines))

    return sections


def test_changelog_exists() -> None:
    assert CHANGELOG.exists(), "CHANGELOG.md is required for release notes"


def test_changelog_release_sections_use_canonical_shape() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    sections = _release_sections(text)

    assert sections, "CHANGELOG.md must have at least one release section"

    for heading, lines in sections:
        assert RELEASE_HEADING.match(heading), (
            "Changelog release headings must be '## Unreleased' or "
            f"'## vX.Y.Z'; got {heading!r}"
        )
        subsections = [line for line in lines if line.startswith("### ")]
        assert subsections == EXPECTED_SUBSECTIONS, (
            f"{heading} must use exactly these subsections, in order: "
            + ", ".join(EXPECTED_SUBSECTIONS)
        )
