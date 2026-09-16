from fastapi.testclient import TestClient

from ra_agent_studio.api import app


def test_health_and_module_flow() -> None:
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    response = client.post(
        "/modules",
        json={"module_id":"api-m1","revision_id":"api-r1","name":"API Module","content":"hello"},
    )
    assert response.status_code == 200
    listed = client.get("/modules")
    assert listed.status_code == 200
    assert any(item["revision_id"]["value"] == "api-r1" for item in listed.json())
