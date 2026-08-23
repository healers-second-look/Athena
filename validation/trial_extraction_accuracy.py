"""Score criteria extraction against the hand-annotated corpus.

Evaluates the criteria pre-registered in `docs/trial-extraction-validation-plan.md`.
Those criteria were fixed before any number was measured and must not be adjusted
after seeing results.

    python validation/trial_extraction_accuracy.py
    python validation/trial_extraction_accuracy.py --verbose   # show every miss

Exit status is 0 only when all four criteria pass, so this is usable in CI once
the corpus reaches its target size.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from secondlook.tier1.criteria_extraction import (  # noqa: E402
    RuleBasedExtractor,
    split_criteria,
)

FIXTURES_DIR = REPO_ROOT / "tests" / "trials" / "fixtures"

#: C2 applies only to the types the rule-based extractor claims to handle well.
REGULAR_TYPES = frozenset({"AGE_RANGE", "ECOG_MAX"})
C2_THRESHOLD = 0.70


@dataclass
class LineOutcome:
    registry_id: str
    line: str
    expected: str
    actual: str
    expected_section: str | None
    actual_section: str

    @property
    def verdict(self) -> str:
        if self.actual == self.expected:
            return "correct"
        if self.actual == "UNPARSEABLE":
            return "missed"
        return "wrong"


@dataclass
class Report:
    outcomes: list[LineOutcome] = field(default_factory=list)
    #: registry_id -> (lines_seen, predicates_produced), for C3.
    counts: dict[str, tuple[int, int]] = field(default_factory=dict)
    section_errors: list[LineOutcome] = field(default_factory=list)
    fixtures: int = 0

    def verdicts(self, name: str) -> list[LineOutcome]:
        return [o for o in self.outcomes if o.verdict == name]

    # --- the four pre-registered criteria --------------------------------
    @property
    def c1_no_wrong(self) -> bool:
        return not self.verdicts("wrong")

    @property
    def c2_regular_recall(self) -> tuple[int, int]:
        relevant = [o for o in self.outcomes if o.expected in REGULAR_TYPES]
        return sum(1 for o in relevant if o.verdict == "correct"), len(relevant)

    @property
    def c3_nothing_dropped(self) -> bool:
        return all(seen == produced for seen, produced in self.counts.values())

    @property
    def c4_sections(self) -> bool:
        return not self.section_errors

    @property
    def passed(self) -> bool:
        correct, total = self.c2_regular_recall
        c2 = total == 0 or correct / total >= C2_THRESHOLD
        return self.c1_no_wrong and c2 and self.c3_nothing_dropped and self.c4_sections


def load_fixtures(directory: Path = FIXTURES_DIR) -> list[dict]:
    if not directory.is_dir():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"))]


def score(fixtures: list[dict], extractor=None) -> Report:
    extractor = extractor or RuleBasedExtractor()
    report = Report(fixtures=len(fixtures))

    for fixture in fixtures:
        registry_id = fixture["registry_id"]
        text = fixture["criteria_text"]
        annotations = fixture["annotations"]

        result = extractor.extract(registry_id, text)
        report.counts[registry_id] = (result.lines_seen, len(result.predicates))

        # Annotations are keyed by the line text so a fixture stays valid if the
        # extractor's ordering ever changes.
        by_line = {a["line"]: a for a in annotations}
        # strict=True: C3 guarantees one predicate per line, so a length
        # mismatch is a real defect and must surface rather than be truncated.
        for (section, line), predicate in zip(split_criteria(text), result.predicates, strict=True):
            annotation = by_line.get(line)
            if annotation is None:
                continue
            outcome = LineOutcome(
                registry_id=registry_id,
                line=line,
                expected=annotation["type"],
                actual=predicate.type,
                expected_section=annotation.get("section"),
                actual_section=section,
            )
            report.outcomes.append(outcome)
            if outcome.expected_section and outcome.expected_section != outcome.actual_section:
                report.section_errors.append(outcome)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="list every non-correct line")
    args = parser.parse_args(argv)

    fixtures = load_fixtures()
    if not fixtures:
        print(f"No fixtures in {FIXTURES_DIR}. Nothing to score.")
        return 2

    report = score(fixtures)
    correct, total = report.c2_regular_recall

    print(f"Corpus: {report.fixtures} fixture(s), {len(report.outcomes)} annotated line(s)\n")
    print(f"  correct : {len(report.verdicts('correct'))}")
    print(f"  missed  : {len(report.verdicts('missed'))}   (-> UNPARSEABLE -> needs_verification)")
    print(f"  wrong   : {len(report.verdicts('wrong'))}   (confidently the wrong predicate)\n")

    rate = f"{correct}/{total}" if total else "n/a"
    print(
        f"C1  no wrong extractions                      {'PASS' if report.c1_no_wrong else 'FAIL'}"
    )
    print(
        f"C2  recall on AGE_RANGE / ECOG_MAX (>= 70%)   {rate}"
        f"  {'PASS' if total == 0 or correct / total >= C2_THRESHOLD else 'FAIL'}"
    )
    c3 = "PASS" if report.c3_nothing_dropped else "FAIL"
    print(f"C3  nothing silently dropped                  {c3}")
    print(
        f"C4  section attribution                       {'PASS' if report.c4_sections else 'FAIL'}"
    )

    if args.verbose:
        for outcome in report.outcomes:
            if outcome.verdict != "correct":
                print(
                    f"\n  [{outcome.verdict}] {outcome.registry_id}"
                    f"\n    expected {outcome.expected}, got {outcome.actual}"
                    f"\n    {outcome.line[:100]}"
                )

    print()
    if report.fixtures < 30:
        print(
            f"NOTE: the issue's target corpus is ~30 sections; this run scored "
            f"{report.fixtures}. Treat the numbers above as provisional until the "
            "corpus reaches that size."
        )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
