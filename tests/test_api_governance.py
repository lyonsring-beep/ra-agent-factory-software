from fastapi.testclient import TestClient

from ra_agent_studio.api import app, studio


def test_api_rejects_self_review() -> None:
    client = TestClient(app)
    response = client.post('/reviews', json={'subject_id':'x','author_id':'same','reviewer_id':'same','passed':True})
    assert response.status_code == 400


def test_snapshot_endpoint_exposes_backend_projection() -> None:
    client = TestClient(app)
    response = client.get('/snapshot')
    assert response.status_code == 200
    assert set(response.json()) == {'modules','compositions','evidence','reviews','freezes','baselines','deployments'}
