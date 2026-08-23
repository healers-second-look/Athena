import pytest

from secondlook.mutation_validation import validate_mutation
from secondlook.uniprot import parse_uniprot_fasta


def test_parse_uniprot_fasta_records_accession_gene_and_version():
    fasta = (
        ">sp|P04637|P53_HUMAN Cellular tumor antigen p53 OS=Homo sapiens "
        "OX=9606 GN=TP53 PE=1 SV=4\n"
        "MEEPQSDPSV\n"
        "EPPLSQETFS\n"
    )
    protein = parse_uniprot_fasta(fasta)
    assert protein.accession == "P04637"
    assert protein.gene == "TP53"
    assert protein.sequence == "MEEPQSDPSVEPPLSQETFS"
    assert protein.isoform_note == "P04637 (canonical; UniProt sequence version 4)"


@pytest.mark.integration
def test_live_uniprot_tp53_r175h_validates_and_mutates():
    result = validate_mutation("P04637", "R175H")
    assert result.status == "valid"
    assert result.mutation_type == "missense"
    assert result.hgvs_normalized == "p.Arg175His"
    assert result.uniprot_accession == "P04637"
    assert result.gene == "TP53"
    assert result.position == 175
    assert result.reference_residue_expected == "R"
    assert result.reference_residue_actual == "R"
    assert result.error_message is None
    assert result.wildtype_sequence is not None
    assert result.mutant_sequence is not None
    assert result.wildtype_sequence[174] == "R"
    assert result.mutant_sequence[174] == "H"
    assert result.isoform_note is not None
    assert "P04637" in result.isoform_note


@pytest.mark.integration
def test_live_uniprot_resolves_gene_symbol_tp53():
    result = validate_mutation("TP53", "p.Arg175His")
    assert result.status == "valid"
    assert result.uniprot_accession == "P04637"
    assert result.gene == "TP53"
    assert result.mutant_sequence is not None
    assert result.mutant_sequence[174] == "H"
