import pytest

from secondlook.binding import (
    BindingScore,
    McsmApoStructureError,
    McsmLigResult,
    McsmPageError,
    McsmTimeoutError,
    chain_for_residue,
    mutation_shorthand,
    parse_mcsm_result,
    score_binding,
)
from secondlook.candidates import DrugCandidate
from secondlook.mutation_validation import MutationValidationResult
from secondlook.structure import StructureResult
from secondlook.vina_dock import VinaError

EXAMPLE_HTML = """
<html><body>
<p>Predicted Affinity Change: -2.056 log(affinity fold change) - Destabilizing</p>
<p>Wild-type: D</p>
<p>Position: 30</p>
<p>Mutant-type: N</p>
<p>Chain: A</p>
<p>Ligand ID: 065</p>
<p>Distance to ligand: 2.814 Å</p>
<p>DUET stability change: -0.087 Kcal/mol</p>
</body></html>
"""

CHAIN_B_PDB = """\
ATOM      1  CA  ASP B  30      1.000   0.000   0.000  1.00 20.00           C
"""


def _validation(*, position: int = 30, ref: str = "D", alt: str = "N") -> MutationValidationResult:
    wt = "A" * (position - 1) + ref + "A" * 10
    mut = "A" * (position - 1) + alt + "A" * 10
    return MutationValidationResult(
        status="valid",
        gene="TEST",
        hgvs_normalized=f"p.Asp{position}Asn" if ref == "D" else f"p.Xaa{position}Xaa",
        uniprot_accession="P00000",
        isoform_note="canonical",
        position=position,
        reference_residue_expected=ref,
        reference_residue_actual=ref,
        mutation_type="missense",
        error_message=None,
        wildtype_sequence=wt,
        mutant_sequence=mut,
    )


def _structure(
    *, ligand_bound: bool = True, source: str = "PDB", pdb_id: str = "2Z4O"
) -> StructureResult:
    return StructureResult(
        status="found",
        source=source,  # type: ignore[arg-type]
        id=pdb_id,
        plddt_at_residue=None,
        plddt_global=None,
        reliability_flag="high",
        ligand_bound=ligand_bound,
        annotated_position=30,
        pdb_text=CHAIN_B_PDB,
    )


def _candidate(*, name: str = "EXAMPLE", smiles: str = "C") -> DrugCandidate:
    return DrugCandidate(
        name=name,
        source="DGIdb",
        target_tier="exact_protein",
        approved=True,
        smiles=smiles,
        smiles_source="PubChem",
    )


class FakeMcsm:
    def __init__(self, result: McsmLigResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    def submit(self, **kwargs) -> McsmLigResult:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        assert self.result is not None
        return self.result


class FakeVina:
    def __init__(self, result: BindingScore | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    def score(self, **kwargs) -> BindingScore:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        assert self.result is not None
        return self.result


class FakeHet:
    def __init__(self, code: str | None = "065") -> None:
        self.code = code
        self.calls: list[str] = []

    def resolve(self, drug_name: str, structure: StructureResult) -> str | None:
        self.calls.append(drug_name)
        return self.code


def _parsed_example() -> McsmLigResult:
    return parse_mcsm_result(EXAMPLE_HTML)


def test_parses_verified_mcsm_lig_example_result():
    result = parse_mcsm_result(EXAMPLE_HTML)
    assert result.affinity_change == -2.056
    assert result.affinity_class == "Destabilizing"
    assert result.wild_type == "D"
    assert result.position == 30
    assert result.mutant_type == "N"
    assert result.chain == "A"
    assert result.ligand_id == "065"
    assert result.distance_angstrom == 2.814
    assert result.duet_stability_kcal == -0.087


def test_mutation_shorthand_from_validated_result():
    assert mutation_shorthand(_validation()) == "D30N"


def test_chain_comes_from_structure_not_assumed_a():
    assert chain_for_residue(CHAIN_B_PDB, 30) == "B"


def test_mcsm_success_uses_parsed_delta_as_the_reported_score():
    mcsm = FakeMcsm(_parsed_example())
    result = score_binding(
        _validation(),
        _structure(),
        _candidate(),
        mcsm_client=mcsm,
        vina_client=FakeVina(error=VinaError("unused")),
        het_resolver=FakeHet("065"),
        sleeper=lambda _: None,
    )
    assert result.status == "scored"
    assert result.method == "mCSM-lig"
    assert result.delta_score == -2.056
    assert result.affinity_class == "Destabilizing"
    assert result.distance_angstrom == 2.814
    assert mcsm.calls[0]["pdb_code"] == "2Z4O"
    assert mcsm.calls[0]["mutation"] == "D30N"
    assert mcsm.calls[0]["chain"] == "B"
    assert mcsm.calls[0]["lig_id"] == "065"


def test_page_error_falls_back_to_vina():
    vina = FakeVina(
        BindingScore(
            status="scored",
            method="docking",
            delta_score=1.2,
            affinity_class=None,
            distance_angstrom=None,
            ligand_id=None,
            chain=None,
        )
    )
    result = score_binding(
        _validation(),
        _structure(),
        _candidate(),
        mcsm_client=FakeMcsm(error=McsmPageError("selectors missing")),
        vina_client=vina,
        het_resolver=FakeHet("065"),
        sleeper=lambda _: None,
    )
    assert result.method == "docking"
    assert result.delta_score == 1.2
    assert vina.calls


def test_timeout_falls_back_to_vina():
    vina = FakeVina(
        BindingScore(
            status="scored",
            method="docking",
            delta_score=0.5,
            affinity_class=None,
            distance_angstrom=None,
            ligand_id=None,
            chain=None,
        )
    )
    result = score_binding(
        _validation(),
        _structure(),
        _candidate(),
        mcsm_client=FakeMcsm(error=McsmTimeoutError("timed out")),
        vina_client=vina,
        het_resolver=FakeHet("065"),
        sleeper=lambda _: None,
    )
    assert result.method == "docking"


def test_missing_het_code_falls_back_to_vina_without_calling_mcsm():
    mcsm = FakeMcsm(_parsed_example())
    vina = FakeVina(
        BindingScore(
            status="scored",
            method="docking",
            delta_score=0.1,
            affinity_class=None,
            distance_angstrom=None,
            ligand_id=None,
            chain=None,
        )
    )
    result = score_binding(
        _validation(),
        _structure(),
        _candidate(name="OXALIPLATIN"),
        mcsm_client=mcsm,
        vina_client=vina,
        het_resolver=FakeHet(None),
        sleeper=lambda _: None,
    )
    assert result.method == "docking"
    assert mcsm.calls == []
    assert vina.calls


def test_apo_structure_skips_mcsm_and_tries_vina():
    mcsm = FakeMcsm(_parsed_example())
    vina = FakeVina(
        BindingScore(
            status="scored",
            method="docking",
            delta_score=0.3,
            affinity_class=None,
            distance_angstrom=None,
            ligand_id=None,
            chain=None,
        )
    )
    result = score_binding(
        _validation(),
        _structure(ligand_bound=False, source="AlphaFoldDB", pdb_id="AF-P04637-F1"),
        _candidate(),
        mcsm_client=mcsm,
        vina_client=vina,
        het_resolver=FakeHet("065"),
        sleeper=lambda _: None,
    )
    assert result.method == "docking"
    assert mcsm.calls == []


def test_apo_and_vina_failure_returns_binding_unavailable_not_low_plddt_message():
    result = score_binding(
        _validation(),
        _structure(ligand_bound=False),
        _candidate(),
        mcsm_client=FakeMcsm(error=McsmApoStructureError("apo")),
        vina_client=FakeVina(error=VinaError("no grid box")),
        het_resolver=FakeHet(None),
        sleeper=lambda _: None,
    )
    assert result.status == "unavailable"
    assert result.method is None
    assert "AlphaMissense functional score and structural context remain available" in (
        result.error_message or ""
    )
    # This structure is reliability_flag="high" — the message must not falsely
    # claim low pLDDT/unreliable structure, which structure_unavailable_message()
    # would (that message is reserved for when Step 3 itself couldn't find a
    # usable structure, not for binding-scoring failing on a perfectly good one).
    assert "below reliability threshold" not in (result.error_message or "")


def test_high_confidence_structure_never_gets_the_low_plddt_message():
    """Regression test: a 1.01 Å experimental structure (reliability_flag='high')
    must never be reported as low-confidence just because binding scoring failed."""
    result = score_binding(
        _validation(),
        _structure(ligand_bound=True),
        _candidate(name="NO_HET_MATCH"),
        mcsm_client=FakeMcsm(_parsed_example()),
        vina_client=FakeVina(error=VinaError("no smiles usable")),
        het_resolver=FakeHet(None),
        sleeper=lambda _: None,
    )
    assert result.status == "unavailable"
    assert "below reliability threshold" not in (result.error_message or "")
    assert "pLDDT" not in (result.error_message or "")


PROCESSING_HTML = """
<html><body>
<div>Processing Submission</div>
<p>We are processing your submission.</p>
</body></html>
"""

FORM_ERROR_HTML = """
<html><body>
<div class="alert alert-error">
<h4>Error</h4>
Wild-type affinity value must be greater than zero.
</div>
</body></html>
"""


class FakePage:
    def __init__(
        self,
        html: str = EXAMPLE_HTML,
        *,
        fail_goto: Exception | None = None,
        after_reload: str | None = None,
        missing_selectors: bool = False,
    ) -> None:
        self.html = html
        self.fail_goto = fail_goto
        self.after_reload = after_reload
        self.missing_selectors = missing_selectors
        self.fills: dict[str, str] = {}
        self.clicked = False
        self.files: str | None = None
        self.reloads = 0

    def goto(self, url: str, **kwargs) -> None:
        if self.fail_goto:
            raise self.fail_goto

    def fill(self, selector: str, value: str) -> None:
        self.fills[selector] = value

    def locator(self, selector: str) -> "FakePage":
        return self

    def count(self) -> int:
        return 0 if self.missing_selectors else 1

    def click(self) -> None:
        self.clicked = True

    def wait_for_timeout(self, timeout: int | None = None) -> None:
        return None

    def reload(self, **kwargs) -> None:
        self.reloads += 1
        if self.after_reload is not None:
            self.html = self.after_reload

    def content(self) -> str:
        return self.html

    def set_input_files(self, selector: str, path: str) -> None:
        self.files = path


def test_playwright_client_fills_confirmed_fields_and_parses_result():
    from secondlook.mcsm_lig import McsmLigPlaywrightClient

    page = FakePage()
    client = McsmLigPlaywrightClient(page_factory=lambda: page)
    parsed = client.submit(pdb_code="2Z4O", pdb_text=None, mutation="D30N", chain="A", lig_id="065")
    assert page.fills['[name="pdb_code"]'] == "2Z4O"
    assert page.fills['[name="mutation"]'] == "D30N"
    assert page.fills['[name="chain"]'] == "A"
    assert page.fills['[name="lig_id"]'] == "065"
    assert page.fills['[name="affin_wt"]'] == "1.0"
    assert page.clicked is True
    assert parsed.affinity_change == -2.056
    assert parsed.affinity_class == "Destabilizing"


def test_playwright_client_fills_example_wildtype_affinity_when_given():
    from secondlook.mcsm_lig import McsmLigPlaywrightClient

    page = FakePage()
    client = McsmLigPlaywrightClient(page_factory=lambda: page)
    client.submit(
        pdb_code="2Z4O",
        pdb_text=None,
        mutation="D30N",
        chain="A",
        lig_id="065",
        wildtype_affinity_nm=0.270,
    )
    assert page.fills['[name="affin_wt"]'] == "0.27"


def test_playwright_client_polls_processing_page_until_result():
    from secondlook.mcsm_lig import McsmLigPlaywrightClient

    page = FakePage(PROCESSING_HTML, after_reload=EXAMPLE_HTML)
    client = McsmLigPlaywrightClient(page_factory=lambda: page)
    parsed = client.submit(pdb_code="2Z4O", pdb_text=None, mutation="D30N", chain="A", lig_id="065")
    assert page.reloads >= 1
    assert parsed.affinity_change == -2.056


def test_playwright_form_error_raises_page_error():
    from secondlook.mcsm_lig import McsmLigPlaywrightClient

    page = FakePage(FORM_ERROR_HTML)
    client = McsmLigPlaywrightClient(page_factory=lambda: page)
    with pytest.raises(McsmPageError, match="greater than zero"):
        client.submit(pdb_code="2Z4O", pdb_text=None, mutation="D30N", chain="A", lig_id="065")


def test_playwright_missing_selectors_raises_page_error():
    from secondlook.mcsm_lig import McsmLigPlaywrightClient

    page = FakePage(missing_selectors=True)
    client = McsmLigPlaywrightClient(page_factory=lambda: page)
    with pytest.raises(McsmPageError, match="missing"):
        client.submit(pdb_code="2Z4O", pdb_text=None, mutation="D30N", chain="A", lig_id="065")


def test_playwright_unreachable_page_raises_page_error():
    from secondlook.mcsm_lig import McsmLigPlaywrightClient

    page = FakePage(fail_goto=ConnectionError("dns"))
    client = McsmLigPlaywrightClient(page_factory=lambda: page)
    with pytest.raises(McsmPageError):
        client.submit(pdb_code="2Z4O", pdb_text=None, mutation="D30N", chain="A", lig_id="065")


def test_playwright_timeout_raises_timeout_error():
    from secondlook.mcsm_lig import McsmLigPlaywrightClient

    page = FakePage(PROCESSING_HTML)
    client = McsmLigPlaywrightClient(page_factory=lambda: page, timeout_ms=1)
    with pytest.raises(McsmTimeoutError):
        client.submit(pdb_code="2Z4O", pdb_text=None, mutation="D30N", chain="A", lig_id="065")


def test_het_resolver_survives_a_chemcomp_lookup_failure_without_nameerror():
    # Regression: StructureHetResolver.resolve() catches RcsbError around the
    # per-HET-code chemcomp lookup, but RcsbError was never imported at module
    # scope in binding.py — only RcsbPdbClient was, and only lazily inside the
    # `client is None` branch. The bare name in `except RcsbError:` resolved to
    # nothing, so a real RCSB failure during resolution raised NameError instead
    # of being handled — crashing exactly during the outage this was meant to
    # tolerate. Assert it degrades to "no match" instead of raising.
    from secondlook.binding import StructureHetResolver
    from secondlook.rcsb import RcsbError
    from secondlook.structure import StructureResult

    class RaisingChemCompClient:
        def fetch_chem_comp(self, code):
            raise RcsbError(f"simulated RCSB outage for {code}")

    structure = StructureResult(
        status="found",
        source="rcsb",
        id="2Z4O",
        plddt_at_residue=None,
        plddt_global=None,
        reliability_flag=None,
        ligand_bound=True,
        annotated_position=None,
        pdb_text="HETATM    1  C1  065 A 200      0.000   0.000   0.000  1.00 20.00           C\n",
    )
    resolver = StructureHetResolver(chem_comp_client=RaisingChemCompClient())
    resolver._candidate_smiles = "CCO"

    result = resolver.resolve("SOME DRUG", structure)

    assert result is None


@pytest.mark.integration
def test_live_mcsm_lig_example_d30n_2z4o():
    from secondlook.mcsm_lig import McsmLigPlaywrightClient

    client = McsmLigPlaywrightClient()
    result = client.submit_example()
    assert result.affinity_change == pytest.approx(-2.056, abs=0.001)
    assert result.affinity_class == "Destabilizing"
    assert result.distance_angstrom == pytest.approx(2.814, abs=0.001)
    assert result.ligand_id == "065"
    assert result.position == 30
