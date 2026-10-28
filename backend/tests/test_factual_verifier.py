from app.services.factual_verifier import classify_claim, verification_fields


def source(name, excerpt, **extra):
    return {"name": name, "excerpt": excerpt, "freshness": "current", **extra}


def test_matching_approved_evidence_verifies_numeric_claim():
    evidence = [source("Approved report", "Our product increases revenue by 30%.")]
    status, confidence, citations = classify_claim(
        "Our product increases revenue by 30%", evidence
    )
    assert status == "verified"
    assert confidence == 0.9
    assert citations == evidence


def test_conflicting_approved_values_are_not_silently_marked_verified():
    supporting = source("Approved report A", "Our product increases revenue by 30%.")
    conflicting = source("Approved report B", "Our product increases revenue by 20%.")
    status, confidence, citations = classify_claim(
        "Our product increases revenue by 30%", [supporting, conflicting]
    )
    assert status == "conflicting_evidence"
    assert confidence == 0.55
    assert supporting in citations
    assert conflicting in citations


def test_conflicting_evidence_has_explanation_and_both_citations():
    fields = verification_fields(
        "Our product increases revenue by 30%",
        [
            source("Approved report A", "Our product increases revenue by 30%"),
            source("Approved report B", "Our product increases revenue by 20%"),
        ],
    )
    assert fields["verification_status"] == "conflicting_evidence"
    assert "both matching and conflicting values" in fields["verification_explanation"]
    assert len(fields["citations"]) == 2


def test_external_search_result_alone_does_not_verify_claim():
    evidence = [
        source(
            "External result",
            "Our product increases revenue by 30%.",
            source_type="external_trusted_source",
        )
    ]
    status, _, citations = classify_claim(
        "Our product increases revenue by 30%", evidence
    )
    assert status == "unverified"
    assert citations == []
