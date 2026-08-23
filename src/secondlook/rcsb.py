"""RCSB PDB search and entry metadata for structure sourcing."""

from __future__ import annotations

import os
import time

import httpx

from secondlook.http_retry import with_retry

DEFAULT_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
DEFAULT_DATA_URL = "https://data.rcsb.org/rest/v1"
DEFAULT_FILE_URL = "https://files.rcsb.org/download"


class RcsbError(RuntimeError):
    pass


class RcsbPdbClient:
    def __init__(
        self,
        search_url: str | None = None,
        data_url: str | None = None,
        client: httpx.Client | None = None,
        file_url: str | None = None,
    ) -> None:
        self.search_url = search_url or os.environ.get("RCSB_SEARCH_URL") or DEFAULT_SEARCH_URL
        self.data_url = (data_url or os.environ.get("RCSB_DATA_URL") or DEFAULT_DATA_URL).rstrip(
            "/"
        )
        self.file_url = (file_url or os.environ.get("RCSB_FILE_URL") or DEFAULT_FILE_URL).rstrip(
            "/"
        )
        self._client = client

    #: How many candidate entries to download while looking for one that covers
    #: the mutated residue. Each check costs a full structure download — hundreds
    #: of KB for a large complex — so this is deliberately small. Entries are
    #: already ranked by resolution. Ten is not arbitrary: ABL1 T315I found no
    #: dockable entry within four and fell through to an apo AlphaFold model, because
    #: the highest-resolution ABL1 entries are small fragments rather than the
    #: imatinib-bound kinase domain. Results are cached per case by the harness.
    MAX_COVERAGE_CHECKS = 10

    #: Seconds to wait between coordinate downloads during a coverage scan.
    #: RCSB resets the connection under rapid repeated fetches; this keeps the
    #: scan a well-behaved client of a shared public resource.
    COVERAGE_SCAN_DELAY_SECONDS = 0.5

    def search_by_uniprot(
        self,
        accession: str,
        preferred_ligands: tuple[str, ...] = (),
        covering_residue: int | None = None,
    ) -> dict | None:
        """Find an experimental structure for `accession`.

        When `covering_residue` is given, only an entry that actually contains
        that residue is returned. This matters more than it sounds: the search
        matches any entry linked to the UniProt accession, which includes
        complexes containing only a short *peptide* from the protein. For BRAF
        V600E the top hit was 8VSO — a 14-3-3 sigma / BRAF-phosphopeptide ternary
        complex whose BRAF chain spans residues 255-263 and whose only atom
        numbered 600 is a water. Scoring a V600E substitution against it is
        impossible, and without this check the pipeline reported it as a
        high-reliability experimental structure and then blamed the binding
        methods for the resulting failure.

        Returns None when no candidate covers the residue, so `source_structure`
        falls through to AlphaFold, whose models are full-length by construction.
        """
        ligand_ids = self._search(accession, ligand_bound_only=True)
        apo_ids = [] if ligand_ids else self._search(accession, ligand_bound_only=False)
        candidates = ligand_ids or apo_ids
        if not candidates:
            return None
        ligand_bound = bool(ligand_ids)

        if covering_residue is None:
            chosen = candidates[0]
            if preferred_ligands:
                for pdb_id in candidates:
                    meta = self._entry_hit(pdb_id, ligand_bound=ligand_bound)
                    if self._matches_preferred(meta, preferred_ligands):
                        return self._with_coordinates(meta)
            return self._with_coordinates(self._entry_hit(chosen, ligand_bound=ligand_bound))

        # Ranked preference, best first:
        #   1. dockable (residue + ligand in one chain) AND a preferred ligand
        #   2. dockable
        #   3. merely covers the residue — still useful for AlphaMissense and
        #      binding-site distance, just not for a docking delta
        # Scanning past the first covering hit matters: for BRAF V600E the
        # top-ranked covering entry is 3OG7, which splits the residue and the
        # ligand across two chains and cannot be docked at all.
        first_dockable: dict | None = None
        first_covering: dict | None = None
        for index, pdb_id in enumerate(candidates[: self.MAX_COVERAGE_CHECKS]):
            if index and self.COVERAGE_SCAN_DELAY_SECONDS:
                time.sleep(self.COVERAGE_SCAN_DELAY_SECONDS)
            meta = self._entry_hit(pdb_id, ligand_bound=ligand_bound)
            try:
                hit = self._with_coordinates(meta)
            except RcsbError:
                # Coordinate file unavailable (e.g. mmCIF-only for very large
                # entries) — skip this candidate rather than abandoning the search.
                continue
            if not self._covers(hit, covering_residue):
                continue
            if first_covering is None:
                first_covering = hit
            if not self._dockable(hit, covering_residue):
                continue
            if preferred_ligands and self._matches_preferred(meta, preferred_ligands):
                return hit
            if first_dockable is None:
                first_dockable = hit
                if not preferred_ligands:
                    break
        return first_dockable or first_covering

    @staticmethod
    def _matches_preferred(meta: dict, preferred_ligands: tuple[str, ...]) -> bool:
        ligands = {ligand.upper() for ligand in meta.get("ligands") or ()}
        return bool(ligands & {ligand.upper() for ligand in preferred_ligands})

    @staticmethod
    def _covers(hit: dict, residue_number: int) -> bool:
        from secondlook.structure import covers_residue

        return covers_residue(hit.get("pdb_text") or "", residue_number)

    @staticmethod
    def _dockable(hit: dict, residue_number: int) -> bool:
        from secondlook.structure import is_dockable

        return is_dockable(hit.get("pdb_text") or "", residue_number)

    def fetch_chem_comp(self, het_code: str) -> dict:
        """Chemical-component record for a HET code: InChIKey, SMILES, name.

        Needed because a HET code is an opaque three-character identifier — `KY9`
        says nothing about which drug it is. Matching a drug name against it by
        string is guesswork; matching InChIKeys is identity.
        """
        data = self._request("GET", f"{self.data_url}/core/chemcomp/{het_code}").json()
        descriptor = data.get("rcsb_chem_comp_descriptor") or {}
        info = data.get("chem_comp") or {}
        return {
            "het_code": het_code,
            "inchikey": descriptor.get("in_ch_i_key") or descriptor.get("InChIKey"),
            "smiles": descriptor.get("smiles"),
            "name": info.get("name"),
        }

    def _search(self, accession: str, *, ligand_bound_only: bool) -> list[str]:
        nodes: list[dict] = [
            {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": (
                        "rcsb_polymer_entity_container_identifiers."
                        "reference_sequence_identifiers.database_accession"
                    ),
                    "operator": "exact_match",
                    "value": accession,
                },
            },
            {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": (
                        "rcsb_polymer_entity_container_identifiers."
                        "reference_sequence_identifiers.database_name"
                    ),
                    "operator": "exact_match",
                    "value": "UniProt",
                },
            },
            {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": "rcsb_entry_info.structure_determination_methodology",
                    "operator": "exact_match",
                    "value": "experimental",
                },
            },
        ]
        if ligand_bound_only:
            nodes.append(
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "rcsb_entry_info.deposited_nonpolymer_entity_instance_count",
                        "operator": "greater",
                        "value": 0,
                    },
                }
            )
        payload = {
            "query": {"type": "group", "logical_operator": "and", "nodes": nodes},
            "return_type": "entry",
            "request_options": {
                "paginate": {"start": 0, "rows": 25},
                "sort": [{"sort_by": "rcsb_entry_info.resolution_combined", "direction": "asc"}],
            },
        }
        response = self._request("POST", self.search_url, json=payload)
        if response.status_code == 204:
            return []
        data = response.json()
        return [hit["identifier"] for hit in data.get("result_set") or []]

    def _entry_hit(self, pdb_id: str, *, ligand_bound: bool) -> dict:
        data = self._request("GET", f"{self.data_url}/core/entry/{pdb_id}").json()
        info = data.get("rcsb_entry_info") or {}
        identifiers = data.get("rcsb_entry_container_identifiers") or {}
        resolution = info.get("resolution_combined")
        if isinstance(resolution, list) and resolution:
            resolution = resolution[0]
        ligands = tuple(identifiers.get("non_polymer_entity_ids") or ())
        return {
            "pdb_id": pdb_id,
            "ligand_bound": ligand_bound or bool(identifiers.get("non_polymer_entity_ids")),
            "resolution": resolution,
            "ligands": ligands,
        }

    def fetch_pdb_text(self, pdb_id: str) -> str:
        """Download atomic coordinates for `pdb_id`.

        Entry metadata alone is not enough: `score_binding` needs real coordinates
        for chain resolution, HET-code lookup, and docking. Mirrors
        `AlphaFoldDbClient.fetch_pdb`.

        Raises `RcsbError` when the coordinate file is unavailable — notably for
        entries too large for the legacy PDB format, which are mmCIF-only and 404
        here. `source_structure` already catches `RcsbError` and falls through to
        AlphaFold, which is the right outcome: a coordinate-less entry is no more
        usable than a missing one.
        """
        return self._request("GET", f"{self.file_url}/{pdb_id}.pdb").text

    def _with_coordinates(self, meta: dict) -> dict:
        """Attach coordinates to a chosen entry.

        Called only for the entry actually returned, never during the
        preferred-ligand scan — otherwise every candidate's full structure would
        be downloaded just to read its ligand list.
        """
        return {**meta, "pdb_text": self.fetch_pdb_text(str(meta["pdb_id"]))}

    def _request(self, method: str, url: str, json: dict | None = None) -> httpx.Response:
        # The request call belongs inside the try — connection resets and
        # timeouts are raised there, not by raise_for_status(). RCSB resets
        # connections under sustained load, which made this gap reachable in
        # normal operation rather than only on an outage.
        def attempt() -> httpx.Response:
            if self._client is not None:
                response = self._client.request(method, url, json=json, timeout=40.0)
            else:
                response = httpx.request(
                    method, url, json=json, timeout=40.0, follow_redirects=True
                )
            if response.status_code != 204:
                response.raise_for_status()
            return response

        try:
            return with_retry(attempt)
        except httpx.HTTPError as exc:
            raise RcsbError(f"RCSB request failed for {url}") from exc
