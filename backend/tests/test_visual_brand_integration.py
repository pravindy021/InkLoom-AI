from io import BytesIO

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject
import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import Base
from app.models.visual_brand import VisualBrandConfiguration
from app.services.visual_palette import resolve_visual_palette


def _image_bytes(color="white", image_format="PNG"):
    buffer = BytesIO()
    Image.new("RGB", (48, 32), color=color).save(buffer, format=image_format)
    return buffer.getvalue()


def _pdf_with_embedded_white_image():
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    image = DecodedStreamObject()
    image.set_data(bytes([255, 255, 255] * 64))
    for key, value in {
        "/Type": "/XObject",
        "/Subtype": "/Image",
        "/Width": 8,
        "/Height": 8,
        "/ColorSpace": "/DeviceRGB",
        "/BitsPerComponent": 8,
    }.items():
        image[NameObject(key)] = (
            NameObject(value) if isinstance(value, str) else NumberObject(value)
        )
    image_ref = writer._add_object(image)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/XObject"): DictionaryObject(
                {NameObject("/Im0"): image_ref}
            )
        }
    )
    content = DecodedStreamObject()
    content.set_data(b"q 8 0 0 8 0 0 cm /Im0 Do Q")
    page[NameObject("/Contents")] = writer._add_object(content)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _save_palette(client, palette):
    response = client.put(
        "/api/guidelines/visual-brand",
        json=palette,
    )
    assert response.status_code == 200
    return response.json()


def _create_schema(engine):
    Base.metadata.create_all(bind=engine)


def test_saved_palette_takes_precedence_over_environment_and_keeps_roles(
    test_engine, monkeypatch
):
    from app.services import image_analyzer

    _create_schema(test_engine)
    monkeypatch.setattr(image_analyzer, "BRAND_PALETTE", ["#000000"])
    with Session(test_engine) as db:
        db.add(
            VisualBrandConfiguration(
                id=1,
                primary=["#123456"],
                secondary=["#ABCDEF"],
                accent=["#F0A020"],
                version_number=1,
            )
        )
        db.commit()
        resolved = resolve_visual_palette(db, [])

    assert resolved["source"] == "saved"
    assert resolved["colors"] == [
        {"color": "#123456", "role": "primary"},
        {"color": "#ABCDEF", "role": "secondary"},
        {"color": "#F0A020", "role": "accent"},
    ]
    assert "#000000" not in [item["color"] for item in resolved["colors"]]


def test_environment_fallback_and_explicit_empty_saved_palette_are_distinct(
    test_engine, monkeypatch
):
    from app.services import image_analyzer

    _create_schema(test_engine)
    monkeypatch.setattr(image_analyzer, "BRAND_PALETTE", ["#000000"])
    with Session(test_engine) as db:
        fallback = resolve_visual_palette(db, [])
        assert fallback["source"] == "environment"
        assert fallback["colors"] == [
            {"color": "#000000", "role": "environment"}
        ]

        db.add(
            VisualBrandConfiguration(
                id=1,
                primary=[],
                secondary=[],
                accent=[],
                version_number=1,
            )
        )
        db.commit()
        explicit_empty = resolve_visual_palette(db, [])

    assert explicit_empty["source"] == "saved"
    assert explicit_empty["colors"] == []
    assert explicit_empty["configured"] is False


def test_guideline_colors_remain_additional_references_when_saved_palette_empty(
    test_engine, monkeypatch
):
    from types import SimpleNamespace
    from app.services import image_analyzer

    _create_schema(test_engine)
    monkeypatch.setattr(image_analyzer, "BRAND_PALETTE", ["#000000"])
    guideline = SimpleNamespace(
        category="visual_identity",
        name="Primary color",
        description="Use #ABCDEF.",
        examples=[],
        id=42,
    )
    with Session(test_engine) as db:
        db.add(
            VisualBrandConfiguration(
                id=1,
                primary=[],
                secondary=[],
                accent=[],
                version_number=1,
            )
        )
        db.commit()
        resolved = resolve_visual_palette(db, [guideline])

    assert resolved["source"] == "saved"
    assert resolved["colors"] == [
        {
            "color": "#ABCDEF",
            "role": "guideline",
            "guideline_id": 42,
            "guideline": "Primary color",
        }
    ]


@pytest.mark.parametrize(
    ("actual_color", "expected_color", "expected_role"),
    [
        ("black", "#000000", "primary"),
        ("white", "#FDFDFD", "secondary"),
        ("#F0A020", "#F0A020", "accent"),
    ],
)
def test_color_comparison_reports_nearest_role_and_distance(
    monkeypatch, actual_color, expected_color, expected_role
):
    from app.services import image_analyzer

    monkeypatch.setattr(image_analyzer, "BRAND_PALETTE", [])
    monkeypatch.setattr(image_analyzer, "PALETTE_TOLERANCE", 36)
    result = image_analyzer.inspect_image(
        _image_bytes(actual_color),
        resolved_palette={
            "source": "saved",
            "tolerance": 36,
            "method": "Euclidean RGB distance approximation; not perceptually uniform",
            "colors": [
                {"color": "#000000", "role": "primary"},
                {"color": "#FDFDFD", "role": "secondary"},
                {"color": "#F0A020", "role": "accent"},
            ],
        },
    )
    comparison = result["palette_comparison"]
    nearest = comparison["colors"][0]
    detected_color = (
        actual_color.upper()
        if actual_color.startswith("#")
        else {"black": "#000000", "white": "#FFFFFF"}[actual_color]
    )

    assert comparison["source"] == "saved"
    assert nearest["image_color"] == detected_color
    assert nearest["nearest_detected_color"] == detected_color
    assert nearest["expected_brand_color"] == expected_color
    assert nearest["palette_role"] == expected_role
    assert nearest["nearest_brand_color_distance"] < 36
    assert nearest["within_tolerance"] is True
    assert comparison["expected_color_details"][2]["role"] == "accent"


def test_far_color_comparison_is_advisory_and_includes_actionable_details(
    monkeypatch,
):
    from app.services import image_analyzer
    from app.services.visual_analysis import analyze_visual_file

    monkeypatch.setattr(image_analyzer, "BRAND_PALETTE", [])
    monkeypatch.setattr(image_analyzer, "PALETTE_TOLERANCE", 0)
    resolved = {
        "source": "saved",
        "tolerance": 0,
        "method": "Euclidean RGB distance approximation; not perceptually uniform",
        "colors": [{"color": "#000000", "role": "primary"}],
    }
    info, findings = analyze_visual_file(
        "sample.png",
        "image/png",
        _image_bytes("white"),
        [],
        [],
        resolved_palette=resolved,
    )
    finding = next(item for item in findings if item["category"] == "visual_brand")
    palette = info["palette_comparison"]
    assert palette["potential_mismatch"] is True
    assert palette["colors"][0]["nearest_brand_color_distance"] > 400
    assert finding["visual_data"]["expected_brand_color"] == "#000000"
    assert finding["visual_data"]["nearest_detected_color"] == "#FFFFFF"
    assert finding["visual_data"]["palette_role"] == "primary"
    assert finding["visual_data"]["approximate_color_distance"] > 400
    assert "primary brand colour" in finding["suggestion"]
    assert "heuristic" in finding["explanation"]


def test_uploaded_image_analysis_uses_saved_palette_not_environment(
    client, monkeypatch
):
    from app.services import image_analyzer

    monkeypatch.setattr(image_analyzer, "BRAND_PALETTE", ["#000000"])
    _save_palette(
        client,
        {"primary": ["#FFFFFF"], "secondary": [], "accent": []},
    )
    response = client.post(
        "/api/analyze",
        data={"content": "Review the image."},
        files={"file": ("white.png", _image_bytes(), "image/png")},
    )

    assert response.status_code == 200
    comparison = response.json()["image_analysis"]["palette_comparison"]
    assert comparison["source"] == "saved"
    assert comparison["expected_colors"] == ["#FFFFFF"]
    assert comparison["colors"][0]["palette_role"] == "primary"
    assert comparison["potential_mismatch"] is False


def test_explicit_empty_saved_palette_disables_environment_fallback(
    client, monkeypatch
):
    from app.services import image_analyzer

    monkeypatch.setattr(image_analyzer, "BRAND_PALETTE", ["#000000"])
    _save_palette(client, {"primary": [], "secondary": [], "accent": []})
    response = client.post(
        "/api/analyze",
        data={"content": "Review the image."},
        files={"file": ("white.png", _image_bytes(), "image/png")},
    )

    assert response.status_code == 200
    image_info = response.json()["image_analysis"]
    assert image_info["palette_comparison"] is None
    assert any("No approved brand palette is configured" in item
               for item in image_info["limitations"])
    assert not any(
        item.get("visual_data", {}).get("palette_comparison")
        for item in response.json()["findings"]
    )


def test_environment_palette_is_used_when_no_saved_configuration(
    client, monkeypatch
):
    from app.services import image_analyzer

    monkeypatch.setattr(image_analyzer, "BRAND_PALETTE", ["#000000"])
    response = client.post(
        "/api/analyze",
        data={"content": "Review the image."},
        files={"file": ("white.png", _image_bytes(), "image/png")},
    )

    assert response.status_code == 200
    comparison = response.json()["image_analysis"]["palette_comparison"]
    assert comparison["source"] == "environment"
    assert comparison["expected_colors"] == ["#000000"]


def test_pdf_embedded_image_uses_resolved_saved_palette(client, monkeypatch):
    from app.services import image_analyzer

    monkeypatch.setattr(image_analyzer, "BRAND_PALETTE", ["#000000"])
    _save_palette(
        client,
        {"primary": ["#FFFFFF"], "secondary": [], "accent": []},
    )
    response = client.post(
        "/api/analyze",
        data={"content": "Review this PDF design."},
        files={
            "file": (
                "design.pdf",
                _pdf_with_embedded_white_image(),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 200
    image = response.json()["image_analysis"]["pages"][0]["images"][0]
    assert image["palette_comparison"]["source"] == "saved"
    assert image["palette_comparison"]["expected_color_details"][0] == {
        "color": "#FFFFFF",
        "role": "primary",
        "guideline_id": None,
        "guideline": None,
    }
    assert image["palette_comparison"]["potential_mismatch"] is False


def test_video_frame_uses_the_same_resolved_saved_palette(
    client, monkeypatch
):
    from app.routes import analysis
    from app.services import image_analyzer

    monkeypatch.setattr(image_analyzer, "BRAND_PALETTE", ["#000000"])
    _save_palette(
        client,
        {"primary": ["#FFFFFF"], "secondary": [], "accent": []},
    )
    frame_bytes = _image_bytes("white", "JPEG")

    async def process_video(_upload, _allow_transcription):
        return (
            b"video-data",
            {
                "duration_seconds": 1.0,
                "frame_interval_seconds": 1,
                "metadata": {"width": 48, "height": 32, "video_codec": "h264"},
                "frames": [
                    {
                        "frame_index": 0,
                        "timestamp_seconds": 0.0,
                        "file_data": frame_bytes,
                        "media_type": "image/jpeg",
                    }
                ],
                "transcript": {"text": "", "segments": [], "configured": False},
                "warnings": [],
            },
        )

    monkeypatch.setattr(analysis, "process_video_upload", process_video)
    response = client.post(
        "/api/analyze",
        data={"title": "Visual review", "content": "", "content_type": "Video"},
        files={"file": ("clip.mp4", b"upload", "video/mp4")},
    )

    assert response.status_code == 200
    attachment = client.get(
        "/api/reviews/{}".format(response.json()["id"])
    ).json()["visual_attachment"]
    comparison = attachment["analysis"]["video"]["frames"][0]["analysis"][
        "palette_comparison"
    ]
    assert comparison["source"] == "saved"
    assert comparison["expected_colors"] == ["#FFFFFF"]
    assert comparison["colors"][0]["palette_role"] == "primary"
    assert comparison["potential_mismatch"] is False


def test_palette_database_error_returns_service_unavailable_without_fallback(
    client, monkeypatch
):
    from app.routes import analysis

    def fail_resolution(*_args, **_kwargs):
        raise SQLAlchemyError("private database detail")

    monkeypatch.setattr(analysis, "resolve_visual_palette", fail_resolution)
    response = client.post(
        "/api/analyze",
        data={"content": "Review the image."},
        files={"file": ("white.png", _image_bytes(), "image/png")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Visual brand palette settings are temporarily unavailable."
    )
    assert "private database detail" not in response.text


def test_unconfigured_analysis_retains_legacy_no_palette_behavior(
    client, monkeypatch
):
    from app.services import image_analyzer

    monkeypatch.setattr(image_analyzer, "BRAND_PALETTE", [])
    response = client.post(
        "/api/analyze",
        data={"content": "Review the image."},
        files={"file": ("white.png", _image_bytes(), "image/png")},
    )

    assert response.status_code == 200
    image_info = response.json()["image_analysis"]
    assert image_info["palette_comparison"] is None
    assert image_info["dominant_colors"][0]["hex"] == "#FFFFFF"
    assert any("No approved brand palette is configured" in item
               for item in image_info["limitations"])
