"""Tests for Subsystem Y (Agent Harness Runtime)."""

import pytest

from secondlook.board.charters import (
    CharterRegistry,
    ClaimKind,
    RoleCharter,
)
from secondlook.board.fabric import (
    AnchorType,
    ComputedCitationForbiddenError,
    EvidenceClass,
    GraphFabric,
    GraphNode,
    IdentityAnchor,
    RoleKnowledgeGraph,
)
from secondlook.board.harness import (
    AgentHarness,
    Finding,
    RoleExecutionResult,
    RuntimeJurisdictionError,
    SandboxedKGViolationError,
    ToolNotPermittedError,
    UnstructuredClaimError,
)


@pytest.fixture
def test_charter() -> RoleCharter:
    return RoleCharter(
        role_id="medical_oncologist",
        charter_version="1.0.0",
        jurisdiction=(
            ClaimKind.SYSTEMIC_THERAPY_OPTION,
            ClaimKind.LINE_OF_THERAPY,
            ClaimKind.SEQUENCING,
            ClaimKind.EXHAUSTION_STATUS,
        ),
        prohibited_claims=(
            ClaimKind.MOLECULAR_VARIANT_INTERPRETATION,
            ClaimKind.RADIATION_DOSE_CONSTRAINT,
        ),
        kg_id="medical_oncology_kg",
        allowed_tools=("guideline_kb_query",),
        abstention_rules=("insufficient_staging",),
    )


@pytest.fixture
def test_fabric() -> GraphFabric:
    fabric = GraphFabric()
    kg_med = RoleKnowledgeGraph(role_id="medical_oncologist", graph_id="medical_oncology_kg")
    node = GraphNode(
        node_id="fnd-1",
        role_provenance="medical_oncologist",
        evidence_class=EvidenceClass.DOCUMENTED,
        claim="Fulvestrant plus CDK4/6 inhibitor recommended",
        citation_id="ESMO-2024-BC",
        citation_url="https://doi.org/10.1016/j.annonc.2024.01.001",
        anchors=(IdentityAnchor(AnchorType.HGNC, "ESR1"),),
    )
    kg_med.add_node(node)
    fabric.register_graph(kg_med)

    # Register an isolated molecular KG
    kg_mol = RoleKnowledgeGraph(role_id="molecular_pathologist", graph_id="molecular_kg")
    fabric.register_graph(kg_mol)
    return fabric


def test_harness_sandboxed_kg_enforcement(
    test_charter: RoleCharter, test_fabric: GraphFabric
) -> None:
    registry = CharterRegistry({"medical_oncologist": test_charter})
    harness = AgentHarness(registry=registry, fabric=test_fabric)

    # Normal access to medical_oncology_kg succeeds
    result = harness.execute_role(
        role_id="medical_oncologist",
        case_state={"case_id": "case-123"},
        round_number=1,
    )
    assert len(result.findings) == 1
    assert result.findings[0].role_id == "medical_oncologist"

    # Attempting to access molecular_kg raises SandboxedKGViolationError
    with pytest.raises(SandboxedKGViolationError) as exc_info:
        harness.execute_role(
            role_id="medical_oncologist",
            case_state={"case_id": "case-123"},
            round_number=1,
            requested_kg_id="molecular_kg",
        )
    assert "restricts access strictly to 'medical_oncology_kg'" in str(exc_info.value)


def test_harness_tool_permission_enforcement(
    test_charter: RoleCharter, test_fabric: GraphFabric
) -> None:
    registry = CharterRegistry({"medical_oncologist": test_charter})
    harness = AgentHarness(registry=registry, fabric=test_fabric)

    # Runner attempting to call an unpermitted tool
    def illegal_tool_runner(req, tool_invoker):
        tool_invoker("unauthorized_tool", {})
        return RoleExecutionResult(role_id="medical_oncologist")

    harness.register_runner("medical_oncologist", illegal_tool_runner)

    with pytest.raises(ToolNotPermittedError) as exc_info:
        harness.execute_role("medical_oncologist", case_state={}, round_number=1)
    assert "not in allowed_tools" in str(exc_info.value)


def test_harness_jurisdiction_violation_enforcement(
    test_charter: RoleCharter, test_fabric: GraphFabric
) -> None:
    registry = CharterRegistry({"medical_oncologist": test_charter})
    harness = AgentHarness(registry=registry, fabric=test_fabric)

    # Runner emitting a prohibited claim
    def prohibited_claim_runner(req, tool_invoker):
        finding = Finding(
            finding_id="fnd-illegal",
            role_id="medical_oncologist",
            claim_kind=ClaimKind.MOLECULAR_VARIANT_INTERPRETATION,  # Prohibited!
            statement="PIK3CA H1047R is pathogenic",
            evidence_class=EvidenceClass.DOCUMENTED,
            citations=("CIVIC-123",),
        )
        return RoleExecutionResult(role_id="medical_oncologist", findings=(finding,))

    harness.register_runner("medical_oncologist", prohibited_claim_runner)

    with pytest.raises(RuntimeJurisdictionError) as exc_info:
        harness.execute_role("medical_oncologist", case_state={}, round_number=1)
    assert "emitted prohibited claim" in str(exc_info.value)


def test_finding_computed_evidence_citation_prohibited() -> None:
    # ARCHITECTURE.md §5: Computed evidence cannot carry citations
    with pytest.raises(ComputedCitationForbiddenError):
        Finding(
            finding_id="fnd-computed-bad",
            role_id="molecular_pathologist",
            claim_kind=ClaimKind.ACTIONABILITY_CLASS,
            statement="Predicted destabilizing affinity",
            evidence_class=EvidenceClass.COMPUTED,
            citations=("PMID:12345",),  # Forbidden!
        )


def test_finding_unstructured_statement_refused() -> None:
    with pytest.raises(UnstructuredClaimError):
        Finding(
            finding_id="fnd-empty",
            role_id="medical_oncologist",
            claim_kind=ClaimKind.LINE_OF_THERAPY,
            statement="   ",
            evidence_class=EvidenceClass.DOCUMENTED,
        )
