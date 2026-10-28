from types import SimpleNamespace

from app.services.text_analyzer import analyze_text


def test_claim_and_accessibility_rules_are_advisory():
    findings = analyze_text(
        "This product guarantees 100% success. Click here.",
        [],
    )
    assert {item["category"] for item in findings} == {
        "unsupported_claim",
        "accessibility",
    }
    assert all(item["confidence"] is not None for item in findings)


def test_configured_term_and_expired_source_are_detected():
    guideline = SimpleNamespace(
        id=15,
        name="Factual evidence",
        category="factual_claim",
        severity="high",
        prohibited_terms=["amazing"],
        preferred_terms=["considered"],
        approved_sources=[
            {"name": "Old report", "expiry_date": "2000-01-01"}
        ],
    )
    findings = analyze_text("An amazing product grew by 40%.", [guideline])
    terminology = next(item for item in findings if item["category"] == "terminology")
    factual = next(item for item in findings if item["category"] == "factual_claim")
    assert "considered" in terminology["suggestion"]
    assert "expired" in factual["explanation"]


def test_current_retrieved_source_is_not_reported_as_missing():
    guideline = SimpleNamespace(
        id=10,
        name="Current facts",
        category="factual_claim",
        severity="medium",
        prohibited_terms=[],
        preferred_terms=[],
        approved_sources=[],
    )
    findings = analyze_text(
        "The annual subscription price is $240.",
        [guideline],
        evidence_matches=[
            {
                "id": 4,
                "name": "Current price sheet",
                "guideline_id": guideline.id,
                "freshness": "current",
            }
        ],
    )
    factual = next(item for item in findings if item["category"] == "factual_claim")
    assert "current approved source excerpt matched" in factual["explanation"]
    assert "not verification" in factual["explanation"]


def test_quoted_promotional_claim_excludes_closing_quote():
    from app.services.claim_checker import check_promotional_claims

    text = (
        "Our product is "
        "“100% guaranteed to double your productivity in just 24 hours”."
    )

    findings = check_promotional_claims(text)
    finding = next(
        item for item in findings
        if item["category"] == "unsupported_claim"
    )

    assert finding["matched_text"].endswith("24 hours")
    assert not finding["matched_text"].endswith("”")


def test_claim_suggestion_does_not_contaminate_matched_text():
    findings = analyze_text(
        "Our product is 100% guaranteed to double your productivity in just 24 hours.",
        [],
    )

    finding = next(
        item for item in findings
        if item["category"] == "unsupported_claim"
    )

    assert finding["matched_text"].endswith("24 hours")
    assert "Revise" not in finding["matched_text"]
    assert "Revise" in finding["suggestion"]
