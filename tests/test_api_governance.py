from fastapi.testclient import TestClient

from ra_agent_studio.api import app, studio
from tests.support import authority_registry


def test_api_does_not_accept_caller_supplied_reviewer_identity() -> None:
    studio.authority = authority_registry()
    client = TestClient(app)
    response = client.post(
        "/reviews",
        json={"candidate_id": "x", "review_method": "external_ai", "passed": True},
    )
    assert response.status_code == 401


def test_snapshot_endpoint_exposes_authoritative_projection_and_audit() -> None:
    client = TestClient(app)
    response = client.get("/snapshot")
    assert response.status_code == 200
    assert set(response.json()) == {
        "modules",
        "compositions",
        "evidence",
        "candidates",
        "reviews",
        "freezes",
        "baselines",
        "deployments",
        "production_runs",
        "audit",
    }
