from fastapi.testclient import TestClient

from sim.api.app import app
from tests.conftest import requires_postgres


client = TestClient(app)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_estimate():
    res = client.post(
        "/estimate",
        json={"n_agents": 20, "horizon_sweeps": 4, "seeds": 1, "workers": 2},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total_seconds"] > 0


@requires_postgres
def test_places_and_why_shape(db_session):
    # Ensure maplewood exists via API dependency's session — use engine path through places
    res = client.get("/places")
    assert res.status_code == 200
    places = res.json()
    assert any(p["slug"] == "maplewood" for p in places)
