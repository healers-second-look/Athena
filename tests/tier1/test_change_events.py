"""Change events: what counts as a change, and what deliberately does not."""

import json

from secondlook.tier1.change_events import (
    CollectingChangeEventSink,
    JsonlChangeEventSink,
    NullChangeEventSink,
    build_event,
    diff_properties,
    is_provenance_key,
    read_events,
)


class TestDiff:
    def test_reports_only_keys_that_actually_differ(self):
        changed = diff_properties(
            {"evidence_level": "C", "status": "accepted"},
            {"evidence_level": "B", "status": "accepted"},
        )
        assert changed == {"evidence_level": ("C", "B")}

    def test_provenance_keys_are_ignored(self):
        """`retrieved_at` moves on every run by definition. Counting it would
        mark every node changed on every pass and destroy the signal."""
        assert (
            diff_properties(
                {"retrieved_at": "2026-01-01", "source_version": "1"},
                {"retrieved_at": "2026-08-23", "source_version": "2"},
            )
            == {}
        )

    def test_per_property_provenance_is_ignored_too(self):
        """with_enrichment_provenance writes <prop>_source / <prop>_retrieved_at,
        one set per enriched property, so the key set is open-ended."""
        assert is_provenance_key("drug_class_source")
        assert is_provenance_key("drug_class_retrieved_at")
        assert not is_provenance_key("drug_class")
        assert (
            diff_properties({"drug_class_retrieved_at": "old"}, {"drug_class_retrieved_at": "new"})
            == {}
        )

    def test_a_key_absent_from_the_write_is_not_a_deletion(self):
        """Loaders write with `SET n += $props`, which cannot remove a property.
        A key in `old` and absent from `new` was simply not part of this write."""
        assert diff_properties({"a": 1, "b": 2}, {"a": 1}) == {}

    def test_a_new_key_counts_as_a_change_from_none(self):
        assert diff_properties({}, {"phase": "PHASE2"}) == {"phase": (None, "PHASE2")}


class TestBuildEvent:
    def test_no_change_returns_none_rather_than_an_empty_event(self):
        """Makes 'no change' unrepresentable downstream, so a consumer cannot
        count no-ops as activity."""
        assert (
            build_event(
                node_type="Gene",
                node_id="ABL1",
                old_props={"symbol": "ABL1"},
                new_props={"symbol": "ABL1"},
                source="CIViC",
            )
            is None
        )

    def test_records_what_changed(self):
        event = build_event(
            node_type="EvidenceItem",
            node_id="238",
            old_props={"evidence_level": "C"},
            new_props={"evidence_level": "B"},
            source="CIViC",
            retrieved_at="2026-08-23T00:00:00+00:00",
        )
        assert event is not None
        assert event.changed_keys == ("evidence_level",)
        assert event.changed["evidence_level"] == ("C", "B")
        assert event.node_id == "238"

    def test_to_dict_is_json_serialisable_with_an_explicit_shape(self):
        event = build_event(
            node_type="Trial",
            node_id="NCT1",
            old_props={"status": "RECRUITING"},
            new_props={"status": "ACTIVE_NOT_RECRUITING"},
            source="ClinicalTrials.gov",
        )
        payload = json.loads(json.dumps(event.to_dict(), sort_keys=True))
        assert payload["changed"]["status"] == {"old": "RECRUITING", "new": "ACTIVE_NOT_RECRUITING"}


class TestSinks:
    def test_null_sink_counts_what_it_drops(self):
        """Answers 'is the loader emitting at all?' without a real consumer."""
        sink = NullChangeEventSink()
        event = build_event(
            node_type="Gene",
            node_id="X",
            old_props={"a": 1},
            new_props={"a": 2},
            source="t",
        )
        sink.emit(event)
        assert sink.dropped == 1

    def test_jsonl_sink_round_trips(self, tmp_path):
        path = tmp_path / "events.jsonl"
        sink = JsonlChangeEventSink(path)
        for level in ("B", "A"):
            sink.emit(
                build_event(
                    node_type="EvidenceItem",
                    node_id="1",
                    old_props={"evidence_level": "C"},
                    new_props={"evidence_level": level},
                    source="CIViC",
                )
            )
        assert sink.written == 2
        assert len(read_events(path)) == 2

    def test_a_truncated_final_line_does_not_lose_the_whole_log(self, tmp_path):
        """Runs get killed mid-write; the completed events must still be readable."""
        path = tmp_path / "events.jsonl"
        sink = JsonlChangeEventSink(path)
        sink.emit(
            build_event(
                node_type="Gene", node_id="A", old_props={"a": 1}, new_props={"a": 2}, source="t"
            )
        )
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"node_type": "Gene", "node_i')
        assert len(read_events(path)) == 1

    def test_collecting_sink_keeps_order(self):
        sink = CollectingChangeEventSink()
        for node_id in ("1", "2"):
            sink.emit(
                build_event(
                    node_type="Gene",
                    node_id=node_id,
                    old_props={"a": 1},
                    new_props={"a": 2},
                    source="t",
                )
            )
        assert [e.node_id for e in sink.events] == ["1", "2"]
