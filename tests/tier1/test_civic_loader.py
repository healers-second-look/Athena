"""Unit tests for civic_loader -- no network, no live FalkorDB.

Every test here mocks at the actual call boundary and asserts the mock was
really hit (RareCure rule #9: its "mocked" test still performed real network
I/O because the mock did not cover the real call path).
"""

from __future__ import annotations

import json

import httpx
import pytest

from secondlook.tier1 import civic_loader
from secondlook.tier1.civic_loader import (
    LoadSummary,
    citation_url_for,
    extract_hgvs_c,
    extract_hgvs_p,
    load_evidence_item,
    load_scope_config,
    map_direction,
    map_variant_type,
)
from secondlook.tier1.civic_verify import CivicApiError


class FakeGraph:
    """Records every Cypher query + params instead of talking to FalkorDB.

    Tests assert on `queries` directly, so a change from MERGE to CREATE, or
    a MERGE key losing a component, fails loudly.
    """

    def __init__(self):
        self.queries: list[tuple[str, dict]] = []

    def query(self, cypher: str, params: dict | None = None):
        self.queries.append((cypher, params or {}))
        return None

    def cypher_containing(self, needle: str) -> list[tuple[str, dict]]:
        return [(q, p) for q, p in self.queries if needle in q]


IN_SCOPE = {"1115"}


def make_item(**overrides) -> dict:
    """A well-formed CIViC evidence item, shaped exactly like the live API
    response verified in civic_verify.py."""
    item = {
        "id": 238,
        "name": "EID238",
        "link": "/evidence/238",
        "evidenceLevel": "A",
        "evidenceType": "PREDICTIVE",
        "evidenceDirection": "SUPPORTS",
        "significance": "RESISTANCE",
        "status": "ACCEPTED",
        "description": "EGFR T790M confers resistance to erlotinib.",
        "disease": {"id": 8, "name": "Sarcoma", "doid": "1115"},
        "therapies": [{"id": 15, "name": "Erlotinib", "ncitId": "C65530"}],
        "source": {
            "id": 167,
            "citationId": "25668228",
            "sourceType": "PUBMED",
            "sourceUrl": "http://www.ncbi.nlm.nih.gov/pubmed/25668228",
            "title": "EGFR T790M resistance mutation in NSCLC.",
            "publicationYear": 2015,
        },
        "molecularProfile": {
            "id": 34,
            "name": "EGFR T790M",
            "variants": [
                {
                    "id": 34,
                    "name": "T790M",
                    "feature": {"name": "EGFR"},
                    "hgvsDescriptions": [
                        "ENST00000275493.2:c.2369C>T",
                        "NM_005228.4:c.2369C>T",
                        "NP_005219.2:p.Thr790Met",
                    ],
                    "variantTypes": [{"name": "Missense Variant", "soid": "SO:0001583"}],
                }
            ],
        },
    }
    item.update(overrides)
    return item


def new_summary() -> LoadSummary:
    return LoadSummary(config_version="test-v1", retrieved_at="2026-08-21T00:00:00+00:00")


# ---------------------------------------------------------------------------
# Direction mapping -- the clinically load-bearing logic
# ---------------------------------------------------------------------------


class TestMapDirection:
    def test_sensitivity_supported_is_sensitive(self):
        assert map_direction("SENSITIVITYRESPONSE", "SUPPORTS") == "sensitive"

    def test_resistance_supported_is_resistant(self):
        assert map_direction("RESISTANCE", "SUPPORTS") == "resistant"

    def test_does_not_support_sensitivity_is_not_inverted_to_resistant(self):
        """The subtle one. "Evidence does NOT support sensitivity" is a
        different claim from "resistant" -- mapping it to resistant would
        fabricate a finding CIViC never made, so it must be skipped."""
        assert map_direction("SENSITIVITYRESPONSE", "DOES_NOT_SUPPORT") is None

    def test_does_not_support_resistance_is_unmapped(self):
        assert map_direction("RESISTANCE", "DOES_NOT_SUPPORT") is None

    @pytest.mark.parametrize(
        "significance",
        ["REDUCED_SENSITIVITY", "BETTER_OUTCOME", "POOR_OUTCOME", "PATHOGENIC", "NA", "UNKNOWN"],
    )
    def test_non_response_significances_are_unmapped(self, significance):
        assert map_direction(significance, "SUPPORTS") is None

    def test_na_direction_is_unmapped(self):
        assert map_direction("RESISTANCE", "NA") is None

    def test_missing_values_are_unmapped(self):
        assert map_direction(None, "SUPPORTS") is None
        assert map_direction("RESISTANCE", None) is None


class TestMapVariantType:
    def test_missense_so_id(self):
        assert map_variant_type([{"name": "Missense Variant", "soid": "SO:0001583"}]) == "missense"

    def test_fusion_so_id(self):
        assert map_variant_type([{"name": "Gene Fusion", "soid": "SO:0001565"}]) == "fusion"

    def test_civic_transcript_fusion_so_id(self):
        assert map_variant_type([{"name": "Transcript Fusion", "soid": "SO:0001886"}]) == "fusion"

    def test_unknown_so_id_returns_none_rather_than_guessing(self):
        assert map_variant_type([{"name": "Transcript Variant", "soid": "SO:0001576"}]) is None

    def test_empty_returns_none(self):
        assert map_variant_type([]) is None
        assert map_variant_type(None) is None


class TestHgvsExtraction:
    def test_extracts_protein_level(self):
        assert (
            extract_hgvs_p(["NM_005228.4:c.2369C>T", "NP_005219.2:p.Thr790Met"])
            == "NP_005219.2:p.Thr790Met"
        )

    def test_prefers_refseq_transcript(self):
        assert (
            extract_hgvs_c(["ENST00000275493.2:c.2369C>T", "NM_005228.4:c.2369C>T"])
            == "NM_005228.4:c.2369C>T"
        )

    def test_returns_none_when_absent(self):
        assert extract_hgvs_p(["NC_000007.13:g.55249071C>T"]) is None
        assert extract_hgvs_c([]) is None


# ---------------------------------------------------------------------------
# Skip accounting -- every drop is counted, never log-only
# ---------------------------------------------------------------------------


class TestSkipCounting:
    def test_bad_direction_is_skipped_and_counted_not_guessed(self):
        graph, summary = FakeGraph(), new_summary()
        item = make_item(significance="SENSITIVITYRESPONSE", evidenceDirection="DOES_NOT_SUPPORT")

        assert load_evidence_item(graph, item, summary, IN_SCOPE) is False
        assert summary.skipped["bad_direction"] == 1
        assert graph.queries == [], "a skipped record must not reach any write call"

    def test_missing_citation_never_reaches_a_write_call(self):
        graph, summary = FakeGraph(), new_summary()
        item = make_item(
            source={"id": 1, "citationId": None, "sourceType": "ASCO", "sourceUrl": ""},
            link="",
        )

        assert load_evidence_item(graph, item, summary, IN_SCOPE) is False
        assert summary.skipped["missing_citation"] == 1
        assert graph.queries == []

    def test_out_of_scope_disease_is_skipped_and_counted(self):
        graph, summary = FakeGraph(), new_summary()
        item = make_item(disease={"id": 99, "name": "Melanoma", "doid": "1909"})

        assert load_evidence_item(graph, item, summary, IN_SCOPE) is False
        assert summary.skipped["out_of_scope_disease"] == 1
        assert graph.queries == []

    def test_multi_variant_profile_is_skipped(self):
        graph, summary = FakeGraph(), new_summary()
        profile = {
            "id": 99,
            "name": "BRAF V600E AND NRAS Q61",
            "variants": [
                {"id": 1, "name": "V600E", "feature": {"name": "BRAF"}},
                {"id": 2, "name": "Q61", "feature": {"name": "NRAS"}},
            ],
        }
        item = make_item(molecularProfile=profile)
        assert load_evidence_item(graph, item, summary, IN_SCOPE) is False
        assert summary.skipped["multi_variant_profile"] == 1

    def test_no_therapy_is_skipped(self):
        graph, summary = FakeGraph(), new_summary()
        assert load_evidence_item(graph, make_item(therapies=[]), summary, IN_SCOPE) is False
        assert summary.skipped["no_therapy"] == 1

    def test_bad_evidence_level_is_skipped(self):
        graph, summary = FakeGraph(), new_summary()
        assert load_evidence_item(graph, make_item(evidenceLevel="Z"), summary, IN_SCOPE) is False
        assert summary.skipped["bad_evidence_level"] == 1

    def test_unknown_skip_reason_raises(self):
        summary = new_summary()
        with pytest.raises(ValueError, match="unknown skip reason"):
            summary.skip("not_a_real_reason")

    def test_summary_exposes_skips_as_structured_data(self):
        summary = new_summary()
        summary.skip("bad_direction")
        summary.skip("missing_citation")
        as_dict = summary.to_dict()
        assert as_dict["skipped"]["bad_direction"] == 1
        assert as_dict["total_skipped"] == 2


# ---------------------------------------------------------------------------
# Well-formed record -> correct nodes/edges
# ---------------------------------------------------------------------------


class TestWellFormedRecord:
    def test_writes_expected_nodes_and_edges(self):
        graph, summary = FakeGraph(), new_summary()
        assert load_evidence_item(graph, make_item(), summary, IN_SCOPE) is True

        assert summary.nodes_written == {
            "Gene": 1,
            "Variant": 1,
            "Disease": 1,
            "EvidenceItem": 1,
            "Publication": 1,
            "Drug": 1,
        }
        assert summary.edges_written == {
            "HAS_VARIANT": 1,
            "OBSERVED_IN": 1,
            "SUPPORTS": 1,
            "CITES": 1,
            "PREDICTS_RESPONSE_TO": 1,
        }
        assert summary.total_skipped == 0

    def test_every_node_write_carries_provenance(self):
        graph, summary = FakeGraph(), new_summary()
        load_evidence_item(graph, make_item(), summary, IN_SCOPE)

        node_writes = graph.cypher_containing("MERGE (n:")
        assert node_writes, "expected node MERGE queries"
        for _cypher, params in node_writes:
            props = params["props"]
            assert props["source"] == "CIViC"
            assert props["retrieved_at"] == "2026-08-21T00:00:00+00:00"
            assert props["source_version"] == "test-v1"

    def test_direction_is_written_onto_the_response_edge(self):
        graph, summary = FakeGraph(), new_summary()
        load_evidence_item(graph, make_item(), summary, IN_SCOPE)

        edges = graph.cypher_containing("PREDICTS_RESPONSE_TO")
        assert len(edges) == 1
        cypher, params = edges[0]
        assert "direction: $rel_direction" in cypher
        assert params["rel_direction"] == "resistant"

    def test_variant_carries_parsed_hgvs_and_type(self):
        graph, summary = FakeGraph(), new_summary()
        load_evidence_item(graph, make_item(), summary, IN_SCOPE)

        variant_writes = [p for q, p in graph.cypher_containing("MERGE (n:Variant")]
        assert len(variant_writes) == 1
        props = variant_writes[0]["props"]
        assert props["hgvs_p"] == "NP_005219.2:p.Thr790Met"
        assert props["hgvs_c"] == "NM_005228.4:c.2369C>T"
        assert props["variant_type"] == "missense"

    def test_unmapped_variant_type_is_counted_but_still_loaded(self):
        graph, summary = FakeGraph(), new_summary()
        item = make_item()
        item["molecularProfile"]["variants"][0]["variantTypes"] = [
            {"name": "Transcript Variant", "soid": "SO:0001576"}
        ]

        assert load_evidence_item(graph, item, summary, IN_SCOPE) is True
        assert summary.unmapped_variant_type == 1
        props = [p for q, p in graph.cypher_containing("MERGE (n:Variant")][0]["props"]
        assert props["variant_type"] is None


# ---------------------------------------------------------------------------
# Idempotency + MERGE key shape
# ---------------------------------------------------------------------------


class TestFusionVariants:
    """Fusions load as a single Gene node carrying CIViC's fusion label."""

    @staticmethod
    def fusion_item(**overrides) -> dict:
        item = make_item(**overrides)
        item["molecularProfile"] = {
            "id": 419,
            "name": "TPM3::NTRK1",
            "variants": [
                {
                    "id": 419,
                    "name": "Fusion",
                    "__typename": "FusionVariant",
                    "feature": {"name": "TPM3::NTRK1"},
                    "variantTypes": [{"name": "Transcript Fusion", "soid": "SO:0001886"}],
                }
            ],
        }
        return item

    def test_fusion_is_loaded_not_skipped(self):
        graph, summary = FakeGraph(), new_summary()
        assert load_evidence_item(graph, self.fusion_item(), summary, IN_SCOPE) is True
        assert summary.total_skipped == 0
        assert summary.nodes_written["Gene"] == 1

    def test_gene_symbol_is_the_fusion_label(self):
        graph, summary = FakeGraph(), new_summary()
        load_evidence_item(graph, self.fusion_item(), summary, IN_SCOPE)

        gene_writes = [p for _q, p in graph.cypher_containing("MERGE (n:Gene")]
        assert len(gene_writes) == 1
        assert gene_writes[0]["key"] == "TPM3::NTRK1"

    def test_fusion_gene_is_flagged(self):
        """Retrieval branches on this flag rather than on string shape -- a
        CONTAINS/substring check on symbol would reintroduce RareCure rule
        #8's free-text matching failure mode."""
        graph, summary = FakeGraph(), new_summary()
        load_evidence_item(graph, self.fusion_item(), summary, IN_SCOPE)

        props = [p for _q, p in graph.cypher_containing("MERGE (n:Gene")][0]["props"]
        assert props["is_fusion"] is True

    def test_non_fusion_gene_is_not_flagged(self):
        graph, summary = FakeGraph(), new_summary()
        load_evidence_item(graph, make_item(), summary, IN_SCOPE)

        props = [p for _q, p in graph.cypher_containing("MERGE (n:Gene")][0]["props"]
        assert props["is_fusion"] is False

    def test_fusion_variant_type_is_mapped(self):
        graph, summary = FakeGraph(), new_summary()
        load_evidence_item(graph, self.fusion_item(), summary, IN_SCOPE)

        props = [p for _q, p in graph.cypher_containing("MERGE (n:Variant")][0]["props"]
        assert props["variant_type"] == "fusion"
        # Fusions carry no hgvsDescriptions -- absent, not fabricated.
        assert props["hgvs_p"] is None
        assert props["hgvs_c"] is None

    def test_fusion_still_gets_a_direction_bearing_response_edge(self):
        graph, summary = FakeGraph(), new_summary()
        load_evidence_item(graph, self.fusion_item(), summary, IN_SCOPE)

        edges = graph.cypher_containing("PREDICTS_RESPONSE_TO")
        assert len(edges) == 1
        assert edges[0][1]["rel_direction"] == "resistant"

    def test_fusion_without_a_feature_name_is_still_skipped(self):
        graph, summary = FakeGraph(), new_summary()
        item = self.fusion_item()
        item["molecularProfile"]["variants"][0]["feature"] = None

        assert load_evidence_item(graph, item, summary, IN_SCOPE) is False
        assert summary.skipped["missing_gene_or_variant"] == 1


class TestIdempotencyAndMergeKeys:
    def test_uses_merge_never_create(self):
        graph, summary = FakeGraph(), new_summary()
        load_evidence_item(graph, make_item(), summary, IN_SCOPE)

        assert graph.queries
        for cypher, _params in graph.queries:
            assert "MERGE" in cypher
            assert "CREATE" not in cypher, f"CREATE would break idempotency: {cypher}"

    def test_running_twice_issues_identical_merges(self):
        graph, summary = FakeGraph(), new_summary()
        load_evidence_item(graph, make_item(), summary, IN_SCOPE)
        first_pass = list(graph.queries)

        load_evidence_item(graph, make_item(), summary, IN_SCOPE)
        second_pass = graph.queries[len(first_pass) :]

        assert first_pass == second_pass, "re-running must replay the same MERGEs"

    def test_response_edge_merge_key_includes_variant_drug_and_direction(self):
        """RareCure rule #3: its dedup collapsed on drug name alone and lost
        gene attribution (`"Pazopanib" | gene: "TP53"`). The MERGE pattern
        must bind all three components."""
        graph, summary = FakeGraph(), new_summary()
        load_evidence_item(graph, make_item(), summary, IN_SCOPE)

        cypher, params = graph.cypher_containing("PREDICTS_RESPONSE_TO")[0]
        assert "MATCH (a:Variant {civic_variant_id: $from_value})" in cypher
        assert "MATCH (b:Drug {name: $to_value})" in cypher
        assert "direction: $rel_direction" in cypher
        assert params["from_value"] == 34
        assert params["to_value"] == "Erlotinib"
        assert params["rel_direction"] == "resistant"

    def test_same_drug_different_variants_are_distinct_edges(self):
        graph, summary = FakeGraph(), new_summary()

        load_evidence_item(graph, make_item(), summary, IN_SCOPE)
        other = make_item(id=999)
        other["molecularProfile"] = {
            "id": 77,
            "name": "EGFR L858R",
            "variants": [
                {
                    "id": 77,
                    "name": "L858R",
                    "feature": {"name": "EGFR"},
                    "hgvsDescriptions": [],
                    "variantTypes": [{"name": "Missense Variant", "soid": "SO:0001583"}],
                }
            ],
        }
        load_evidence_item(graph, other, summary, IN_SCOPE)

        edges = graph.cypher_containing("PREDICTS_RESPONSE_TO")
        variant_keys = {p["from_value"] for _q, p in edges}
        assert variant_keys == {34, 77}, "two variants must not collapse onto one edge"
        assert summary.edges_written["PREDICTS_RESPONSE_TO"] == 2

    def test_same_variant_and_drug_but_opposite_direction_are_distinct(self):
        graph, summary = FakeGraph(), new_summary()

        load_evidence_item(graph, make_item(), summary, IN_SCOPE)
        flipped = make_item(id=1000, significance="SENSITIVITYRESPONSE")
        load_evidence_item(graph, flipped, summary, IN_SCOPE)

        edges = graph.cypher_containing("PREDICTS_RESPONSE_TO")
        directions = {p["rel_direction"] for _q, p in edges}
        assert directions == {"resistant", "sensitive"}


# ---------------------------------------------------------------------------
# Citation URL construction
# ---------------------------------------------------------------------------


class TestCitationUrl:
    def test_prefers_source_url(self):
        assert citation_url_for(make_item()) == "http://www.ncbi.nlm.nih.gov/pubmed/25668228"

    def test_builds_pubmed_url_from_citation_id(self):
        item = make_item(source={"citationId": "12345", "sourceType": "PUBMED", "sourceUrl": ""})
        assert citation_url_for(item) == "https://pubmed.ncbi.nlm.nih.gov/12345/"

    def test_falls_back_to_civic_evidence_link(self):
        item = make_item(source={"citationId": "", "sourceType": "ASCO", "sourceUrl": ""})
        assert citation_url_for(item) == "https://civicdb.org/evidence/238"

    def test_returns_none_when_nothing_resolvable(self):
        item = make_item(source={}, link="")
        assert citation_url_for(item) is None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestScopeConfig:
    def test_real_config_loads_and_is_versioned(self):
        config = load_scope_config()
        assert config["config_version"]
        assert config["diseases"]
        doids = {str(d["doid"]) for d in config["diseases"]}
        assert "1115" in doids, "sarcoma (DOID:1115) must be in scope"
        assert "1612" in doids, "breast cancer (DOID:1612) must be in scope"
        assert "0070780" in doids, "HR+/HER2- breast cancer (DOID:0070780) must be in scope"

    def test_missing_file_raises_civic_api_error(self, tmp_path):
        with pytest.raises(CivicApiError, match="not found"):
            load_scope_config(tmp_path / "nope.yaml")

    def test_config_without_version_is_rejected(self, tmp_path):
        path = tmp_path / "scope.yaml"
        path.write_text("diseases:\n  - doid: '1115'\n", encoding="utf-8")
        with pytest.raises(CivicApiError, match="config_version"):
            load_scope_config(path)

    def test_disease_without_doid_is_rejected(self, tmp_path):
        path = tmp_path / "scope.yaml"
        path.write_text("config_version: '1'\ndiseases:\n  - name: Sarcoma\n", encoding="utf-8")
        with pytest.raises(CivicApiError, match="doid"):
            load_scope_config(path)


# ---------------------------------------------------------------------------
# Concurrency primitive scoping (RareCure rule #7)
# ---------------------------------------------------------------------------


class TestNoModuleLevelConcurrencyPrimitives:
    def test_module_defines_no_semaphore_or_lock_at_import_scope(self):
        import asyncio as _asyncio

        offenders = [
            name
            for name, value in vars(civic_loader).items()
            if isinstance(value, (_asyncio.Semaphore, _asyncio.Lock))
        ]
        assert not offenders, (
            f"module-level concurrency primitives found: {offenders}. These bind to the "
            "first event loop that awaits them and silently break every later "
            "asyncio.run() (RareCure rule #7)."
        )


# ---------------------------------------------------------------------------
# _post() -- CIViC GraphQL shape-checking (RareCure rule #1: a 200 status is
# not success). Mirrors test_chembl_enrich.py's httpx.MockTransport pattern
# at the actual call boundary. Previously this shape-check had zero coverage
# of any kind, live or offline -- the live integration test only exercises
# CIViC's happy path, so these branches had never been proven to fire
# correctly under any test at all.
# ---------------------------------------------------------------------------


def _civic_response(
    body: dict, *, status: int = 200, content_type: str = "application/json"
) -> httpx.Response:
    return httpx.Response(
        status, headers={"content-type": content_type}, content=json.dumps(body).encode()
    )


class TestPost:
    QUERY = "query { x }"
    VARIABLES = {"a": 1}

    def _run(self, client: httpx.AsyncClient):
        return civic_loader.asyncio.run(civic_loader._post(client, self.QUERY, self.VARIABLES))

    def test_request_error_raises_civic_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("simulated connection failure", request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(CivicApiError, match="CIViC request failed"):
            self._run(client)

    def test_non_200_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _civic_response({}, status=500)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(CivicApiError, match="HTTP 500"):
            self._run(client)

    def test_wrong_content_type_raises_even_on_200(self):
        """The exact RareCure DGIdb failure shape: 200 status, wrong body."""

        def handler(request: httpx.Request) -> httpx.Response:
            return _civic_response({}, content_type="text/html")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(CivicApiError, match="content-type"):
            self._run(client)

    def test_malformed_json_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, headers={"content-type": "application/json"}, content=b"not json"
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(CivicApiError, match="undecodable JSON"):
            self._run(client)

    def test_graphql_errors_key_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _civic_response({"errors": [{"message": "simulated GraphQL error"}]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(CivicApiError, match="GraphQL errors"):
            self._run(client)

    def test_missing_data_object_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _civic_response({"notdata": True})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(CivicApiError, match="no 'data' object"):
            self._run(client)

    def test_success_returns_data_object_and_hits_the_mock(self):
        """Same discipline as RareCure rule #9 elsewhere in this file: a
        mock that's never actually asserted-hit could sit upstream of a
        real network call without the test noticing."""
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return _civic_response({"data": {"ok": True}})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        result = self._run(client)

        assert result == {"ok": True}
        assert calls == [civic_loader.CIVIC_GRAPHQL_URL]


# ---------------------------------------------------------------------------
# Mock-interception proof (RareCure rule #9)
# ---------------------------------------------------------------------------


class TestMockActuallyIntercepts:
    def test_no_real_http_call_escapes_the_mock(self, monkeypatch):
        """Proves the mock covers the real call path, rather than sitting
        upstream of it while live I/O still happens underneath."""
        calls: list[str] = []

        class ExplodingAsyncClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, **kwargs):
                calls.append(url)
                raise AssertionError("a real HTTP call escaped the mock and reached the network")

        monkeypatch.setattr(civic_loader.httpx, "AsyncClient", ExplodingAsyncClient)

        summary = new_summary()
        config = {"config_version": "t", "diseases": [{"doid": "1115", "name": "Sarcoma"}]}

        with pytest.raises(AssertionError, match="escaped the mock"):
            civic_loader.asyncio.run(civic_loader._fetch_all(config, summary))

        assert calls == [civic_loader.CIVIC_GRAPHQL_URL], (
            "the mocked client was never actually invoked -- this test would "
            "pass vacuously without this assertion"
        )

    def test_disease_fetch_failure_is_recorded_not_swallowed(self, monkeypatch):
        async def failing_resolve(client, doid):
            raise CivicApiError("simulated CIViC outage")

        monkeypatch.setattr(civic_loader, "resolve_disease_id", failing_resolve)

        class NoopAsyncClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(civic_loader.httpx, "AsyncClient", NoopAsyncClient)

        summary = new_summary()
        config = {"config_version": "t", "diseases": [{"doid": "1115", "name": "Sarcoma"}]}
        items = civic_loader.asyncio.run(civic_loader._fetch_all(config, summary))

        assert items == []
        assert "1115" in summary.disease_errors
        assert "simulated CIViC outage" in summary.disease_errors["1115"]
