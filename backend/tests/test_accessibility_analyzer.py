from io import BytesIO

from docx import Document
from docx.oxml import OxmlElement
from PIL import Image

from app.services.accessibility_analyzer import (
    analyze_docx_accessibility,
    analyze_text_accessibility,
)


def _docx_bytes(include_image_description=False):
    document = Document()
    document.add_heading("Section", level=1)
    document.add_heading("Nested section", level=3)

    paragraph = document.add_paragraph()
    hyperlink = OxmlElement("w:hyperlink")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "Click here"
    run.append(text)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)

    image = BytesIO()
    Image.new("RGB", (4, 4), color="blue").save(image, format="PNG")
    shape = document.add_paragraph().add_run().add_picture(
        BytesIO(image.getvalue())
    )
    if include_image_description:
        shape._inline.docPr.set("descr", "Blue product illustration")

    output = BytesIO()
    document.save(output)
    return output.getvalue()


def test_text_checks_headings_and_link_labels_only_when_markup_is_present():
    findings = analyze_text_accessibility(
        "# Heading one\n\n### Heading three\n\n[click here](https://example.test)"
    )

    assert [item["title"] for item in findings] == [
        "Heading hierarchy skips a level",
        "Link text is missing or unclear",
    ]
    assert all(item["detection_method"].startswith("Deterministic") for item in findings)
    assert analyze_text_accessibility("Plain text without structure.") == []


def test_html_empty_link_and_long_copy_produce_actionable_advisories():
    long_copy = " ".join(
        [
            "This is an unusually long sentence intended to make the prose "
            "lengthy enough that readers may find it difficult to follow "
            "without a pause or clearer division of ideas."
        ]
        * 12
    )
    findings = analyze_text_accessibility(
        "<h1>Title</h1><h3>Skipped</h3><a href='/next'></a> " + long_copy
    )

    titles = [item["title"] for item in findings]
    assert "Heading hierarchy skips a level" in titles
    assert "Link text is missing or unclear" in titles
    readability = next(
        item
        for item in findings
        if item["title"] == "Long sentences may reduce readability"
    )
    assert readability["severity"] == "low"
    assert readability["confidence"] is None
    assert "Consider splitting" in readability["suggestion"]


def test_docx_checks_heading_levels_hyperlinks_and_image_alt_metadata():
    findings = analyze_docx_accessibility(_docx_bytes())
    titles = [item["title"] for item in findings]

    assert titles.count("Heading hierarchy skips a level") == 1
    assert titles.count("Link text is missing or unclear") == 1
    assert titles.count("Document image alternative text not provided") == 1
    assert all(item["matched_text"] for item in findings)


def test_docx_image_description_satisfies_metadata_check():
    findings = analyze_docx_accessibility(
        _docx_bytes(include_image_description=True)
    )
    assert not any(
        item["title"] == "Document image alternative text not provided"
        for item in findings
    )


def test_docx_accessibility_inspection_rejects_malformed_input():
    import pytest

    with pytest.raises(ValueError, match="could not be inspected"):
        analyze_docx_accessibility(b"not a DOCX")


def test_docx_accessibility_findings_are_included_in_review_analysis(client):
    response = client.post(
        "/api/analyze",
        data={"content": "Document review", "content_type": "Document"},
        files={
            "file": (
                "accessibility.docx",
                _docx_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 200
    findings = response.json()["findings"]
    assert any(
        item["title"] == "Document image alternative text not provided"
        for item in findings
    )


def test_image_alt_text_check_uses_available_upload_metadata():
    from app.services.text_analyzer import analyze_text

    missing = analyze_text("Image review", [], image_attached=True)
    supplied = analyze_text(
        "Image review",
        [],
        image_attached=True,
        alt_text="A blue product package on a table",
    )

    assert any(
        item["title"] == "Image alternative text not provided"
        for item in missing
    )
    assert not any(
        item["title"] == "Image alternative text not provided"
        for item in supplied
    )


def test_contrast_findings_are_advisory_and_absent_without_measurements():
    from app.services.visual_analysis import _image_findings

    measured = _image_findings(
        {
            "text_contrast": [
                {
                    "text": "Important copy",
                    "contrast_ratio": 2.4,
                    "threshold": 4.5,
                    "meets_wcag_aa_estimate": False,
                    "confidence": 0.88,
                    "foreground_background_estimate": ["#777777", "#FFFFFF"],
                    "region": {"x": 1, "y": 2, "width": 20, "height": 12},
                    "method": "OCR and dominant-colour clustering estimates.",
                }
            ]
        },
        None,
        None,
        [],
    )

    assert len(measured) == 1
    assert measured[0]["severity"] == "medium"
    assert "not a complete accessibility audit" in measured[0]["explanation"]
    assert measured[0]["visual_data"]["actual_value"]["text"] == "Important copy"
    assert _image_findings({}, None, None, []) == []
