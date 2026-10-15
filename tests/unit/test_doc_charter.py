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
SKILL_DIR = REPO / "skills" / "mcp-app"
SKILL = SKILL_DIR / "SKILL.md"
REFERENCES = SKILL_DIR / "references"

# The six frontmatter keys agentskills.io defines. The Claude app's
# .skill uploader rejects any other key.
_ALLOWED_FRONTMATTER_KEYS = {
    "name", "description", "license", "compatibility", "metadata", "allowed-tools",
}


def _read(path: Path) -> str:
    return path.read_text()


def _frontmatter(text: str) -> dict:
    """Extract YAML frontmatter as a dict. Minimal parser — top-level keys only."""
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


def _skill_files() -> list[Path]:
    return [SKILL, *sorted(REFERENCES.glob("*.md"))]


# --- README must link to the skill ---

def test_readme_links_to_skill():
    """The README must contain a markdown link to the mcp-app skill."""
    text = _read(README)
    assert "skills/mcp-app/SKILL.md" in text, (
        "README must contain a link to skills/mcp-app/SKILL.md so "
        "humans reading the rendered repo can navigate to the skill."
    )


def test_only_one_skill_ships():
    """The repo ships exactly one skill; stale copies of merged skills must not linger."""
    skills = sorted(p.parent.name for p in (REPO / "skills").glob("*/SKILL.md"))
    assert skills == ["mcp-app"], f"expected only skills/mcp-app, found {skills}"


# --- Frontmatter follows the agentskills.io / skill-author rules ---

def test_skill_frontmatter_name_matches_directory():
    fm = _frontmatter(_read(SKILL))
    assert fm.get("name") == SKILL_DIR.name, (
        f"SKILL.md frontmatter `name` must be {SKILL_DIR.name!r}, got {fm.get('name')!r}"
    )


def test_skill_frontmatter_uses_only_standard_keys():
    fm = _frontmatter(_read(SKILL))
    extra = set(fm) - _ALLOWED_FRONTMATTER_KEYS
    assert not extra, (
        f"SKILL.md frontmatter has non-standard keys {sorted(extra)}; the "
        ".skill uploader rejects anything outside the six agentskills.io keys."
    )


def test_skill_description_fits_limits():
    desc = _frontmatter(_read(SKILL)).get("description", "")
    assert desc, "SKILL.md frontmatter must have a non-empty `description`."
    assert len(desc) <= 1024, f"description is {len(desc)} chars; the limit is 1024."
    assert not re.search(r"<[^>]*>", desc), (
        "description must not contain <...> text; the Claude app uploader rejects it."
    )
    assert desc.startswith("Use when"), "description should open with 'Use when...'."


# --- Progressive disclosure: small entry point, routed references ---

def test_skill_md_stays_small():
    text = _read(SKILL)
    lines = text.count("\n")
    assert lines < 500, f"SKILL.md is {lines} lines; keep it under 500."
    assert len(text.encode()) < 20_000, (
        f"SKILL.md is {len(text.encode())} bytes; keep it under ~20 KB (~5k tokens)."
    )


def test_references_fit_single_read():
    """Agents' file reads truncate around 800 lines / 46 KB."""
    for ref in sorted(REFERENCES.glob("*.md")):
        text = _read(ref)
        assert text.count("\n") < 800, f"{ref.name} is over 800 lines; split it."
        assert len(text.encode()) < 45_000, f"{ref.name} is over 45 KB; split it."


def test_every_reference_is_routed_from_skill_md():
    text = _read(SKILL)
    for ref in sorted(REFERENCES.glob("*.md")):
        assert f"`{ref.name}`" in text, (
            f"references/{ref.name} is not named in SKILL.md's routing table; "
            "an agent can't find what isn't routed."
        )


def test_reference_mentions_point_at_real_files():
    """Every `something.md` a skill file names must exist in references/ (or be a repo doc)."""
    known = {p.name for p in REFERENCES.glob("*.md")} | {
        "SKILL.md", "README.md", "CONTRIBUTING.md", "CLAUDE.md", "AGENTS.md",
    }
    for path in _skill_files():
        for name in re.findall(r"`([\w.-]+\.md)`", _read(path)):
            assert name in known, f"{path.name} names `{name}`, which doesn't exist."


# --- The skill must not redirect to the README ---
# Per CONTRIBUTING.md docs-hygiene rule: the skill runs in OTHER repos
# and doesn't have mcp-app's README in context. "See the README for
# details" is an anti-pattern that breaks it for an agent loaded into a
# different repo.

_README_REDIRECT_PATTERNS = [
    r"see the readme\b",
    r"see the framework readme\b",
    r"see readme\.md\b",
    r"refer to the readme\b",
]


def test_skill_does_not_redirect_to_readme():
    for path in _skill_files():
        text = _read(path).lower()
        for pat in _README_REDIRECT_PATTERNS:
            assert not re.search(pat, text), (
                f"{path.relative_to(REPO)} contains the anti-pattern phrase "
                f"matching {pat!r}. The skill runs in OTHER repos and cannot "
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
    """The charter table must include the README, skill, and skill-file columns."""
    text = _read(CONTRIBUTING)
    assert "| Topic | SoT | README | `mcp-app` skill | Skill file |" in text, (
        "CONTRIBUTING.md is missing the charter table header row. The "
        "table must list per-topic SoT, README and skill treatment, and "
        "the skill file that holds each topic."
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
