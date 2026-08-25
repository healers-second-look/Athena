"""Tests for the PR evidence gate (issue #103's bar, enforced in CI)."""

from __future__ import annotations

import pytest

from secondlook.devtools.pr_evidence import (
    check,
    evidence_section,
    touches_a_drivable_surface,
)

SCREENSHOT = "![chat flow](https://github.com/user-attachments/assets/abc123)"
PAYLOAD = """```json
{"user_message": {"role": "user", "content": "EGFR T790M?"},
 "assistant_message": {"role": "assistant", "sources_count": 3}}
```"""


class TestScope:
    @pytest.mark.parametrize(
        "path",
        [
            "web/src/routes/ChatInterface.jsx",
            "web/src/styles/chat.css",
            "src/secondlook/api/routes/chat.py",
        ],
    )
    def test_drivable_surfaces(self, path):
        assert touches_a_drivable_surface([path])

    @pytest.mark.parametrize(
        "path",
        [
            "src/secondlook/signals/literature.py",
            "docs/architecture.md",
            "tests/chat/test_engine.py",
            "src/secondlook/tier1/civic_loader.py",
        ],
    )
    def test_non_drivable_changes_are_out_of_scope(self, path):
        # Not exempt from review -- exempt from THIS check, because there is
        # no UI flow to record.
        assert not touches_a_drivable_surface([path])

    def test_a_test_file_alone_does_not_trigger_it(self):
        assert not touches_a_drivable_surface(["web/src/routes/ChatInterface.test.jsx"])

    def test_but_the_component_beside_it_does(self):
        paths = ["web/src/routes/ChatInterface.test.jsx", "web/src/routes/ChatInterface.jsx"]
        assert touches_a_drivable_surface(paths)


class TestTheBar:
    UI = ["web/src/routes/ChatInterface.jsx"]

    def test_a_screenshot_passes(self):
        ok, _ = check(f"## Evidence\n\n{SCREENSHOT}\n", self.UI)
        assert ok

    def test_a_real_payload_passes(self):
        ok, _ = check(f"## Evidence\n\n{PAYLOAD}\n", self.UI)
        assert ok

    def test_no_evidence_section_fails(self):
        ok, message = check("## Summary\n\nImplements all six phases.\n", self.UI)
        assert not ok
        assert "no '## Evidence' section" in message

    def test_confident_prose_alone_fails(self):
        """The exact failure mode of PR #106."""
        body = (
            "## Evidence\n\n"
            "Tested locally end to end. All 6 phases verified working. "
            "Pytest 21 passed, vitest 24 passed, bundle budget green.\n"
        )
        ok, message = check(body, self.UI)
        assert not ok
        assert "only prose" in message

    def test_an_empty_fenced_block_does_not_count(self):
        ok, _ = check("## Evidence\n\n```\n```\n", self.UI)
        assert not ok

    def test_a_placeholder_block_does_not_count(self):
        ok, _ = check("## Evidence\n\n```\nTODO: paste the payload here\n```\n", self.UI)
        assert not ok

    def test_a_backend_only_change_still_needs_the_payload(self):
        ok, _ = check("## Summary\n\nAdds a route.\n", ["src/secondlook/api/routes/chat.py"])
        assert not ok

    def test_a_non_surface_pr_passes_without_evidence(self):
        ok, message = check(
            "## Summary\n\nFixes a loader.\n", ["src/secondlook/tier1/civic_loader.py"]
        )
        assert ok
        assert "does not apply" in message


class TestSectionParsing:
    def test_it_stops_at_the_next_heading(self):
        body = f"## Evidence\n\n{SCREENSHOT}\n\n## Checklist\n\n- [x] tests\n"
        section = evidence_section(body)
        assert "Checklist" not in section
        assert SCREENSHOT in section

    def test_evidence_under_a_later_heading_is_not_borrowed(self):
        """A screenshot in some other section is not evidence for this one."""
        body = f"## Evidence\n\nnothing yet\n\n## Design notes\n\n{SCREENSHOT}\n"
        ok, _ = check(body, ["web/src/routes/ChatInterface.jsx"])
        assert not ok

    @pytest.mark.parametrize(
        "heading", ["## Evidence", "### Evidence", "## evidence", "## Evidence required"]
    )
    def test_heading_variants(self, heading):
        assert evidence_section(f"{heading}\n\n{SCREENSHOT}\n") is not None

    def test_an_empty_body_is_not_evidence(self):
        ok, _ = check("", ["web/src/routes/ChatInterface.jsx"])
        assert not ok


class TestFencedBlocksAreNotMistakenForHeadings:
    """Evidence in this repo routinely contains markdown.

    A captured assistant reply opens with `## On: ...`. Scanning for `^#`
    without tracking code fences truncates the Evidence section at the first
    line of the payload being checked -- so a PR with real evidence reads as
    having none. Found by running this checker against PR #111.
    """

    UI = ["web/src/routes/ChatInterface.jsx"]

    REPLY_EVIDENCE = """## Evidence

The reply, captured live:

```
## On: What treatment options exist for EGFR T790M in NSCLC?

### Evidence search could not be run
- RETRIEVAL UNAVAILABLE -- the evidence store could not be reached.
```
"""

    def test_a_payload_containing_headings_still_counts(self):
        ok, message = check(self.REPLY_EVIDENCE, self.UI)
        assert ok, message

    def test_the_section_keeps_the_whole_fenced_block(self):
        section = evidence_section(self.REPLY_EVIDENCE)
        assert "RETRIEVAL UNAVAILABLE" in section

    def test_a_real_heading_after_the_fence_still_ends_the_section(self):
        body = self.REPLY_EVIDENCE + "\n## Checklist\n\n- [x] tests pass\n"
        section = evidence_section(body)
        assert "RETRIEVAL UNAVAILABLE" in section
        assert "Checklist" not in section

    def test_tilde_fences_work_too(self):
        body = (
            "## Evidence\n\n~~~\n## On: a question\n"
            "real payload content here, long enough\n~~~\n"
        )
        assert "real payload content" in evidence_section(body)
