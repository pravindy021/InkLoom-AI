from sqlalchemy.orm import Session

from app.models.content_review import ReviewAnalysisRun


CLAIM = "Our product guarantees 100% success for every customer."


def test_initial_analysis_requires_consent_for_remote_providers(
    client, test_engine, monkeypatch
):
    from app.routes import analysis

    embedding_calls = []
    llm_calls = []

    async def retrieve_with_embedding(claim, sources, db):
        embedding_calls.append(claim)
        return [], "embedding_cosine"

    async def analyze_with_llm(content, guidelines, evidence):
        llm_calls.append(content)
        return []

    monkeypatch.setattr(analysis, "EMBEDDINGS_ENABLED", True)
    monkeypatch.setattr(analysis, "llm_enabled", lambda: True)
    monkeypatch.setattr(analysis, "retrieve_evidence", retrieve_with_embedding)
    monkeypatch.setattr(analysis, "analyze_with_llm", analyze_with_llm)

    local_response = client.post(
        "/api/analyze",
        json={"content": CLAIM},
    )
    assert local_response.status_code == 200
    local_result = local_response.json()
    assert local_result["evidence_retrieval_method"] == "bm25_lexical"
    assert embedding_calls == []
    assert llm_calls == []
    assert any("was not opted in" in warning for warning in local_result["provider_warnings"])

    opted_in_response = client.post(
        "/api/analyze",
        json={
            "content": CLAIM,
            "allow_external_ai_processing": True,
        },
    )
    assert opted_in_response.status_code == 200
    opted_in_result = opted_in_response.json()
    assert opted_in_result["evidence_retrieval_method"] == "embedding_cosine"
    assert embedding_calls
    assert llm_calls == [CLAIM]

    with Session(test_engine) as db:
        saved_runs = (
            db.query(ReviewAnalysisRun)
            .filter(
                ReviewAnalysisRun.review_id.in_(
                    [local_result["id"], opted_in_result["id"]]
                )
            )
            .order_by(ReviewAnalysisRun.id)
            .all()
        )
    assert len(saved_runs) == 2
    assert any("was not opted in" in warning for warning in saved_runs[0].warnings)
    assert any("consent was granted" in warning for warning in saved_runs[1].warnings)


def test_revision_reanalysis_requires_consent_for_embeddings(
    client, test_engine, monkeypatch
):
    from app.routes import reviews

    calls = []

    async def retrieve_with_embedding(claim, sources, db):
        calls.append(claim)
        return [], "embedding_cosine"

    monkeypatch.setattr(reviews, "EMBEDDINGS_ENABLED", True)
    monkeypatch.setattr(reviews, "retrieve_evidence", retrieve_with_embedding)
    created = client.post(
        "/api/analyze",
        json={"content": "A simple draft for a product update."},
    )
    assert created.status_code == 200
    review_id = created.json()["id"]

    local_response = client.post(
        f"/api/reviews/{review_id}/reanalyze",
        json={"content": CLAIM},
    )
    assert local_response.status_code == 200
    assert calls == []

    opted_in_response = client.post(
        f"/api/reviews/{review_id}/reanalyze",
        json={
            "content": CLAIM + " We also guarantee satisfaction.",
            "allow_external_ai_processing": True,
        },
    )
    assert opted_in_response.status_code == 200
    assert calls

    with Session(test_engine) as db:
        saved_runs = (
            db.query(ReviewAnalysisRun)
            .filter(ReviewAnalysisRun.review_id == review_id)
            .order_by(ReviewAnalysisRun.id)
            .all()
        )
    assert saved_runs[-2].evidence_retrieval_method == "bm25_lexical"
    assert any("was not opted in" in warning for warning in saved_runs[-2].warnings)
    assert saved_runs[-1].evidence_retrieval_method == "embedding_cosine"
    assert any("consent was granted" in warning for warning in saved_runs[-1].warnings)
