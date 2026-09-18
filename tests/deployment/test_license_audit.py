"""Subsystem O: license-audit enforcement.

Offline, deterministic, no network calls -- matches this repo's existing
convention (e.g. NO_PHI_COLUMN_PATTERN in case/models.py) rather than a
live PyPI/npm lookup, which would be fragile and non-deterministic in CI.

`docs/deployment/license-audit.yaml` is a checked-in, human-reviewed
table. This test only checks two things:

1. Every dependency actually declared in pyproject.toml / web/package.json
   has a corresponding entry in the audit file. A new dependency added
   without updating the audit fails the build -- this is the actual
   enforcement issue #16 asks for ("fail the build if a new dependency
   with an incompatible license is added"): a human must look at and
   record the license before it can silently ship.
2. No audited entry's license is in DENYLIST -- proprietary, non-commercial,
   or otherwise redistribution-incompatible licenses that would conflict
   with Athena's own AGPL-3.0 + commercial-dual-license model
   (see docs/data-sources.md's "Explicitly avoid depending on" for the
   same principle already applied to data sources).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = REPO_ROOT / "docs" / "deployment" / "license-audit.yaml"

#: Licenses that would conflict with redistributing Athena under
#: AGPL-3.0 + a commercial option -- non-commercial-only, academic-only,
#: or proprietary terms. Not "every non-permissive license" -- LGPL/MPL
#: are fine as dependencies (see license-audit.yaml's notes on psycopg,
#: meeko, gemmi) since they don't restrict the licensing of the work
#: that merely depends on them.
DENYLIST_PATTERNS = (
    re.compile(r"non-?commercial", re.I),
    re.compile(r"academic[- ]only", re.I),
    re.compile(r"proprietary", re.I),
    re.compile(r"^unknown$", re.I),
)


def _load_audit() -> dict:
    return yaml.safe_load(AUDIT_PATH.read_text(encoding="utf-8"))


def _strip_version_specifier(requirement: str) -> str:
    """'hgvs>=1.5' -> 'hgvs'. No `packaging` dependency needed for this."""
    return re.split(r"[<>=!~\[; ]", requirement.strip(), maxsplit=1)[0].strip()


def _pyproject_dependencies() -> set[str]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    names = {_strip_version_specifier(r) for r in project.get("dependencies", [])}
    for group in project.get("optional-dependencies", {}).values():
        names.update(_strip_version_specifier(r) for r in group)
    return names


def _package_json_dependencies() -> set[str]:
    import json

    data = json.loads((REPO_ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    names: set[str] = set()
    names.update(data.get("dependencies", {}).keys())
    names.update(data.get("devDependencies", {}).keys())
    return names


def test_every_python_dependency_has_an_audited_license():
    audit = _load_audit()
    audited = set(audit["python"])
    declared = _pyproject_dependencies()
    missing = declared - audited
    assert not missing, (
        f"{missing} in pyproject.toml has no entry in "
        f"{AUDIT_PATH.relative_to(REPO_ROOT)} -- add one in this PR before "
        "the dependency can ship."
    )


def test_every_javascript_dependency_has_an_audited_license():
    audit = _load_audit()
    audited = set(audit["javascript"])
    declared = _package_json_dependencies()
    missing = declared - audited
    assert not missing, (
        f"{missing} in web/package.json has no entry in "
        f"{AUDIT_PATH.relative_to(REPO_ROOT)} -- add one in this PR before "
        "the dependency can ship."
    )


def test_no_audited_license_is_denylisted():
    audit = _load_audit()
    offenders = []
    # All four audited categories, not just python/javascript -- an
    # infrastructure image or a self-hostable model checkpoint (issue
    # #122's `models:` section) can carry a non-commercial or proprietary
    # license just as easily as a pip/npm package can, and this check
    # existing only for the two dependency-manager-tracked ecosystems was
    # itself a gap worth closing while touching this file.
    for ecosystem in ("python", "javascript", "infrastructure", "models"):
        for name, entry in audit[ecosystem].items():
            license_text = entry["license"]
            if any(p.search(license_text) for p in DENYLIST_PATTERNS):
                offenders.append(f"{ecosystem}/{name}: {license_text}")
    assert not offenders, f"Denylisted license(s) found: {offenders}"


def test_audit_file_has_no_stale_entries():
    """The reverse check: an audited package that's no longer a real
    dependency should be removed, not left to rot -- a stale entry makes
    the audit unreliable as a record of what's actually shipping."""
    audit = _load_audit()
    stale_python = set(audit["python"]) - _pyproject_dependencies()
    stale_js = set(audit["javascript"]) - _package_json_dependencies()
    assert not stale_python, f"Stale python audit entries, no longer a dependency: {stale_python}"
    assert not stale_js, f"Stale javascript audit entries, no longer a dependency: {stale_js}"


def test_every_entry_has_required_fields():
    audit = _load_audit()
    for ecosystem in ("python", "javascript", "infrastructure", "models"):
        for name, entry in audit[ecosystem].items():
            for field in ("license", "checked_on"):
                assert field in entry, f"{ecosystem}/{name} is missing required field {field!r}"


# --- issue #122: self-hostable model checkpoints -----------------------


def test_biomistral_7b_is_recorded_and_permissively_licensed():
    """The specific check issue #122's "License check recorded (not just
    assumed)" deliverable asks for."""
    audit = _load_audit()
    assert "biomistral-7b" in audit["models"]
    entry = audit["models"]["biomistral-7b"]
    assert entry["license"] == "Apache-2.0"
    assert "huggingface.co/BioMistral" in entry["source"]
