from fastapi.testclient import TestClient

from ra_agent_studio.api import app, studio
from tests.support import authority_registry


def test_health_and_authenticated_module_flow() -> None:
    studio.authority = authority_registry()
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}

    unauthorized = client.post(
        "/modules",
        json={"module_id": "api-m0", "revision_id": "api-r0", "name": "Denied", "content": "print('x')"},
    )
    assert unauthorized.status_code == 401

    response = client.post(
        "/modules",
        headers={"Authorization": "Bearer builder-token"},
        json={
            "module_id": "api-m1",
            "revision_id": "api-r1",
            "name": "API Module",
            "content": "import sys\nprint(sys.stdin.read())\n",
        },
    )
    assert response.status_code == 200
    listed = client.get("/modules")
    assert listed.status_code == 200
    assert any(item["revision_id"]["value"] == "api-r1" for item in listed.json())
