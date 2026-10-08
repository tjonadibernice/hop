from fastapi.testclient import TestClient

from app.main import app


def test_live_returns_ok():
    client = TestClient(app)

    response = client.get("/health/live")

    # TODO: assert the status code is 200
    # TODO: assert the JSON body is {"status": "ok"}
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
