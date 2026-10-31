import pytest
from web.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_index_route_status(client):
    response = client.get("/")
    assert response.status_code == 200


def test_index_contains_required_panels(client):
    response = client.get("/")
    html = response.get_data(as_text=True)

    # Core brand and headings
    assert "AGENTGATE" in html
    assert "Agent activity overview" in html
    assert "Protected tools" in html
    assert "Authorization requests" in html
    assert "Workflow runs" in html
    assert "Audit trail" in html
    assert "Settings" in html
