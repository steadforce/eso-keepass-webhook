from pathlib import Path

import pytest
from starlette.testclient import TestClient

from eso_keepass_webhook.app import create_app
from eso_keepass_webhook.store import Store

from .conftest import CERT, PASSWORD

TOKEN = "test-token"


@pytest.fixture
def client(database: Path) -> TestClient:
    app = create_app(Store(database, password=PASSWORD), lambda: TOKEN)
    return TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})


def test_property_returns_raw_value(client: TestClient) -> None:
    r = client.get("/v1/secret", params={"path": "apps/postgres/admin", "property": "password"})
    assert r.status_code == 200
    assert r.text == "pg-pass"


def test_custom_property_with_space(client: TestClient) -> None:
    # ESO encodes query values with Go's url.QueryEscape, which turns spaces into "+".
    r = client.get("/v1/secret?path=apps%2Fpostgres%2Fadmin&property=API+KEY")
    assert r.status_code == 200
    assert r.text == "abc 123"


def test_attachment_returns_raw_bytes(client: TestClient) -> None:
    r = client.get("/v1/secret", params={"path": "apps/postgres/admin", "property": "tls.crt"})
    assert r.status_code == 200
    assert r.content == CERT
    assert r.headers["content-type"] == "application/octet-stream"


def test_without_property_returns_all_fields(client: TestClient) -> None:
    r = client.get("/v1/secret", params={"path": "apps/postgres/admin", "property": ""})
    assert r.status_code == 200
    assert r.json()["username"] == "pgadmin"
    assert r.json()["API KEY"] == "abc 123"


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({}, 400),
        ({"path": "/"}, 400),
        ({"path": "missing"}, 404),
        ({"path": "top", "property": "missing"}, 404),
        ({"path": "apps/twice"}, 409),
        ({"path": "apps/clash", "property": "config"}, 409),
        ({"path": "apps/postgres/broken", "property": "password"}, 500),
    ],
)
def test_errors(client: TestClient, params: dict[str, str], status: int) -> None:
    assert client.get("/v1/secret", params=params).status_code == status


@pytest.mark.parametrize("header", ["", "Bearer wrong", f"Basic {TOKEN}", TOKEN])
def test_rejects_bad_token(client: TestClient, header: str) -> None:
    r = client.get("/v1/secret", params={"path": "top"}, headers={"Authorization": header})
    assert r.status_code == 401


def test_rejects_everything_without_token(database: Path) -> None:
    client = TestClient(create_app(Store(database, password=PASSWORD), lambda: ""))
    r = client.get("/v1/secret", params={"path": "top"}, headers={"Authorization": "Bearer "})
    assert r.status_code == 401


def test_healthz_needs_no_token(database: Path) -> None:
    client = TestClient(create_app(Store(database, password=PASSWORD), lambda: TOKEN))
    assert client.get("/healthz").status_code == 200
