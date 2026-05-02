"""Mechanical invariants for the documentation charter (#38).

These tests don't replace human judgment about content, but they
catch the structural errors a charter violation usually produces:
broken cross-references, missing skill links, anti-pattern phrases
("see the README" inside a skill), or charter-table-marker drift.
"""

import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"
CONTRIBUTING = REPO / "CONTRIBUTING.md"
AUTHOR_SKILL = REPO / "skills" / "author-mcp-app" / "SKILL.md"
ADMIN_SKILL = REPO / "skills" / "mcp-app-admin" / "SKILL.md"


def _read(path: Path) -> str:
    return path.read_text()


def _frontmatter(text: str) -> dict:
    """Extract YAML frontmatter as a dict. Minimal parser — name+description only."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end]
    out = {}
    current_key = None
    for line in block.splitlines():
        m = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if m:
            current_key = m.group(1)
            out[current_key] = m.group(2).strip().strip('"')
        elif current_key and line.startswith(" "):
            out[current_key] += " " + line.strip()
    return out


# --- README must link to both skills ---

def test_readme_links_to_author_skill():
    """The README must contain a markdown link to the author-mcp-app skill."""
    text = _read(README)
    assert "skills/author-mcp-app/SKILL.md" in text, (
        "README must contain a link to skills/author-mcp-app/SKILL.md so "
        "humans reading the rendered repo can navigate to the skill."
    )


def test_readme_links_to_admin_skill():
    """The README must contain a markdown link to the mcp-app-admin skill."""
    text = _read(README)
    assert "skills/mcp-app-admin/SKILL.md" in text, (
        "README must contain a link to skills/mcp-app-admin/SKILL.md so "
        "humans reading the rendered repo can navigate to the skill."
    )


# --- Skills must have valid frontmatter ---

def test_author_skill_has_required_frontmatter():
    fm = _frontmatter(_read(AUTHOR_SKILL))
    assert fm.get("name") == "author-mcp-app", (
        f"author-mcp-app/SKILL.md frontmatter `name` must be 'author-mcp-app', got {fm.get('name')!r}"
    )
    assert fm.get("description"), (
        "author-mcp-app/SKILL.md frontmatter must have a non-empty `description`."
    )


def test_admin_skill_has_required_frontmatter():
    fm = _frontmatter(_read(ADMIN_SKILL))
    assert fm.get("name") == "mcp-app-admin", (
        f"mcp-app-admin/SKILL.md frontmatter `name` must be 'mcp-app-admin', got {fm.get('name')!r}"
    )
    assert fm.get("description"), (
        "mcp-app-admin/SKILL.md frontmatter must have a non-empty `description`."
    )


# --- Skills must not redirect to the README ---
# Per CONTRIBUTING.md docs-hygiene rule: skills run in OTHER repos and
# don't have mcp-app's README in context. "See the README for details"
# is an anti-pattern that breaks the skill for an agent loaded into a
# different repo.

_README_REDIRECT_PATTERNS = [
    r"see the README\b",
    r"see the framework README\b",
    r"see README\.md\b",
    r"refer to the README\b",
]


def test_author_skill_does_not_redirect_to_readme():
    text = _read(AUTHOR_SKILL).lower()
    for pat in _README_REDIRECT_PATTERNS:
        assert not re.search(pat, text), (
            f"author-mcp-app/SKILL.md contains the anti-pattern phrase "
            f"matching {pat!r}. Skills run in OTHER repos and cannot "
            f"redirect to mcp-app's README — duplicate the content "
            f"into the skill instead. (CONTRIBUTING.md → 'Skills must "
            f"be self-contained'.)"
        )


def test_admin_skill_does_not_redirect_to_readme():
    text = _read(ADMIN_SKILL).lower()
    for pat in _README_REDIRECT_PATTERNS:
        assert not re.search(pat, text), (
            f"mcp-app-admin/SKILL.md contains the anti-pattern phrase "
            f"matching {pat!r}. Skills run in OTHER repos and cannot "
            f"redirect to mcp-app's README — duplicate the content "
            f"into the skill instead. (CONTRIBUTING.md → 'Skills must "
            f"be self-contained'.)"
        )


# --- CONTRIBUTING.md must contain the charter ---

def test_contributing_has_charter_section():
    """The charter table is the source-of-truth map for all docs.

    CONTRIBUTING.md must keep the marker heading so contributors and
    agents can find it before adding new content.
    """
    text = _read(CONTRIBUTING)
    assert "Charter — single source of truth per topic" in text, (
        "CONTRIBUTING.md must contain the section heading "
        "'Charter — single source of truth per topic' (the per-topic "
        "ownership map). If you renamed it, update this test too."
    )


def test_contributing_charter_table_is_present():
    """The charter table must include all three artifact column headers."""
    text = _read(CONTRIBUTING)
    assert "| Topic | SoT | README | `author-mcp-app` | `mcp-app-admin` |" in text, (
        "CONTRIBUTING.md is missing the charter table header row. The "
        "table must list per-topic SoT for README, author-mcp-app, and "
        "mcp-app-admin."
    )


def test_contributing_audience_legend_is_present():
    """The audience legend (H/AA/OA) must be defined alongside the charter."""
    text = _read(CONTRIBUTING)
    for marker in ("**H**", "**AA**", "**OA**"):
        assert marker in text, (
            f"CONTRIBUTING.md is missing audience-legend marker {marker}. "
            "The legend defines who each artifact serves and is referenced "
            "throughout the docs-hygiene rules."
        )
