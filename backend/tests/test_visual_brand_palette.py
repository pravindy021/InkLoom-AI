import pytest
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.database import Base, migrate_visual_brand
from app.models.user import User
from app.models.visual_brand import VisualBrandConfiguration, VisualBrandVersion
from app.schemas.guidelines import VisualBrandPaletteUpdate


def test_visual_brand_palette_validates_and_normalizes_colors():
    palette = VisualBrandPaletteUpdate(
        primary=["#123456"],
        secondary=["#456789", "#789ABC"],
        accent=["#F0A020"],
    )

    assert palette.model_dump() == {
        "primary": ["#123456"],
        "secondary": ["#456789", "#789ABC"],
        "accent": ["#F0A020"],
    }
    assert VisualBrandPaletteUpdate(primary=["#abcdef"]).primary == ["#ABCDEF"]


@pytest.mark.parametrize(
    "color",
    [
        "123456",
        "#12345",
        "#1234567",
        "#GGGGGG",
        " #123456",
        "#12345 ",
        "",
    ],
)
def test_visual_brand_palette_rejects_invalid_hex(color):
    with pytest.raises(ValidationError):
        VisualBrandPaletteUpdate(primary=[color])


def test_visual_brand_palette_rejects_duplicate_colors_in_and_across_groups():
    with pytest.raises(ValidationError):
        VisualBrandPaletteUpdate(primary=["#123456", "#123456"])
    with pytest.raises(ValidationError):
        VisualBrandPaletteUpdate(
            primary=["#abcdef"],
            secondary=["#ABCDEF"],
        )


def test_visual_brand_palette_enforces_group_and_total_limits():
    with pytest.raises(ValidationError):
        VisualBrandPaletteUpdate(primary=["#{:06X}".format(i) for i in range(11)])
    with pytest.raises(ValidationError):
        VisualBrandPaletteUpdate(
            primary=["#{:06X}".format(i) for i in range(10)],
            secondary=["#{:06X}".format(i + 10) for i in range(10)],
            accent=["#000014"],
        )


def test_visual_brand_palette_accepts_empty_groups_and_empty_palette():
    assert VisualBrandPaletteUpdate().model_dump() == {
        "primary": [],
        "secondary": [],
        "accent": [],
    }
    assert VisualBrandPaletteUpdate(
        primary=[], secondary=[], accent=[]
    ).primary == []


def test_visual_brand_palette_rejects_client_supplied_metadata():
    with pytest.raises(ValidationError):
        VisualBrandPaletteUpdate(primary=[], updated_by="Admin")
    with pytest.raises(ValidationError):
        VisualBrandPaletteUpdate(primary=[], version_number=2)


def test_visual_brand_models_persist_configuration_and_version_metadata(test_engine):
    Base.metadata.create_all(bind=test_engine)
    with Session(test_engine) as db:
        editor = User(
            email="palette-admin@example.test",
            display_name="Palette Admin",
            password_hash="not-a-real-password-hash",
            role="admin",
            is_active=True,
            must_change_password=False,
        )
        db.add(editor)
        db.flush()
        configuration = VisualBrandConfiguration(
            primary=["#123456"],
            secondary=["#456789"],
            accent=["#F0A020"],
            version_number=2,
            updated_by_id=editor.id,
        )
        version = VisualBrandVersion(
            version_number=2,
            snapshot={
                "primary": ["#123456"],
                "secondary": ["#456789"],
                "accent": ["#F0A020"],
            },
            editor_id=editor.id,
        )
        db.add_all([configuration, version])
        db.commit()
        db.refresh(configuration)
        db.refresh(version)

        assert configuration.id == 1
        assert configuration.updated_by.display_name == "Palette Admin"
        assert configuration.created_at is not None
        assert configuration.updated_at is not None
        assert version.editor.display_name == "Palette Admin"
        assert version.created_at is not None
        assert version.snapshot["accent"] == ["#F0A020"]


def test_visual_brand_initializer_adds_tables_without_altering_existing_schema(
    test_engine,
):
    palette_tables = {
        "visual_brand_configurations",
        "visual_brand_versions",
    }
    existing_tables = [
        table
        for table in Base.metadata.sorted_tables
        if table.name not in palette_tables
    ]
    Base.metadata.create_all(bind=test_engine, tables=existing_tables)
    inspector_before = inspect(test_engine)
    names_before = set(inspector_before.get_table_names())
    columns_before = {
        table_name: {
            column["name"] for column in inspector_before.get_columns(table_name)
        }
        for table_name in names_before
    }
    with Session(test_engine) as db:
        db.add(
            User(
                email="existing-user@example.test",
                display_name="Existing User",
                password_hash="not-a-real-password-hash",
                role="admin",
                is_active=True,
                must_change_password=False,
            )
        )
        db.commit()

    migrate_visual_brand(test_engine)

    inspector_after = inspect(test_engine)
    names_after = set(inspector_after.get_table_names())
    assert palette_tables <= names_after
    assert names_after - palette_tables == names_before
    for table_name, columns in columns_before.items():
        assert {
            column["name"]
            for column in inspector_after.get_columns(table_name)
        } == columns
    with Session(test_engine) as db:
        user = db.query(User).filter_by(email="existing-user@example.test").one()
        assert user.display_name == "Existing User"


def test_visual_brand_initializer_is_safe_when_project_schema_is_absent(test_engine):
    migrate_visual_brand(test_engine)
    assert inspect(test_engine).get_table_names() == []
