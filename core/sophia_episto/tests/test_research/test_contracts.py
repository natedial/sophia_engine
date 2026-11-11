from sophia_episto.research.contracts import ProvenanceStatus, SourceClaimRef


def test_identity_and_excerpt_is_only_well_formed():
    """An identity field plus a locus is a shape check, not verification."""
    claim = SourceClaimRef(
        namespace="analyst",
        occurrence_id="doc:1:span:4",
        snapshot_hash="sha256:abc",
        locations=["paragraph 4"],
        excerpt="quoted text",
        author="A",
    )
    assert claim.provenance_status() == ProvenanceStatus.WELL_FORMED


def test_bare_citation_is_unverified():
    claim = SourceClaimRef(
        namespace="web",
        occurrence_id="model-generated-1",
        citation="Smith 2024 argues X",
    )
    assert claim.provenance_status() == ProvenanceStatus.UNVERIFIED
