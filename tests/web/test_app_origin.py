"""The viewer answers its own pages and nobody else's.

It reads any PDF on disk by path, lists directories, writes uploads and spends
model tokens. Bound to 127.0.0.1 that is safe from the network, but not from
the browser: any site the reader has open can send requests to 127.0.0.1, and
one that rebinds its own name to 127.0.0.1 can read the answers too.
"""

import pytest
from fastapi.testclient import TestClient

from sextant.web.app import create_app

LOCAL = "http://127.0.0.1:8765"


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(db_path=tmp_path / "p.db"), base_url=LOCAL)


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost:8765", "[::1]:8765"])
def test_it_answers_when_addressed_as_this_machine(client, host):
    assert client.get("/api/health", headers={"host": host}).status_code == 200


def test_it_refuses_a_request_addressed_to_another_name(client):
    """DNS rebinding: the page's own name now resolves to 127.0.0.1, so the
    browser treats our answers as same-origin and lets the page read them."""
    response = client.get("/api/browse", params={"dir": "/"},
                          headers={"host": "attacker.example:8765"})
    assert response.status_code == 403


def test_it_refuses_a_post_from_another_site(client, tmp_path):
    response = client.post(
        "/api/upload",
        headers={"origin": "https://attacker.example"},
        files={"file": ("x.pdf", b"%PDF-1.7 attacker", "application/pdf")},
    )
    assert response.status_code == 403
    assert not any(tmp_path.rglob("paper.pdf"))


def test_it_refuses_a_post_from_another_local_server(client):
    """Same host, different port: still a different origin."""
    response = client.post("/api/workspace/library", json={},
                           headers={"origin": "http://127.0.0.1:3000"})
    assert response.status_code == 403


def test_it_refuses_a_post_from_an_opaque_origin(client):
    """Sandboxed frames and file:// pages send Origin: null."""
    response = client.post("/api/workspace/library", json={},
                           headers={"origin": "null"})
    assert response.status_code == 403


def test_it_accepts_a_post_from_its_own_page(client):
    response = client.post("/api/workspace/library", json={},
                           headers={"origin": LOCAL})
    assert response.status_code != 403


def test_it_accepts_a_post_with_no_origin_at_all(client):
    """curl and scripts send none, and a browser always does cross-site."""
    assert client.post("/api/workspace/library", json={}).status_code != 403


def test_it_refuses_an_api_read_a_browser_marks_as_cross_site(client):
    """An <img> on another site can still make the request, even though it
    cannot read the answer. No API route has any business serving one."""
    response = client.get("/api/health", headers={"sec-fetch-site": "cross-site"})
    assert response.status_code == 403


def test_following_a_link_to_the_viewer_still_opens_it(client):
    response = client.get("/", headers={"sec-fetch-site": "cross-site"})
    assert response.status_code == 200


def test_an_explicit_bind_address_is_a_name_it_answers_to(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "p.db", host="192.168.1.5"),
                        base_url="http://192.168.1.5:8765")
    assert client.get("/api/health").status_code == 200


def test_a_bare_ipv6_bind_address_is_a_name_it_answers_to(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "p.db", host="::"),
                        base_url=LOCAL)
    response = client.get("/api/health", headers={"host": "[::]:8765"})
    assert response.status_code == 200


def test_a_request_with_an_empty_host_is_refused_whatever_the_bind_address(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "p.db", host="::1"),
                        base_url=LOCAL)
    assert client.get("/api/health", headers={"host": ""}).status_code == 403


def test_the_viewer_cannot_be_framed_by_another_site(client):
    """Framed, its own requests are same-origin, so a page could trick clicks
    on Assess -- which spends -- through it."""
    response = client.get("/")

    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_the_cross_site_mark_is_read_whatever_its_case(client):
    response = client.get("/api/health", headers={"sec-fetch-site": "Cross-Site"})
    assert response.status_code == 403


@pytest.mark.parametrize("host", ["evil.example@127.0.0.1:8765", "127.0.0.1:8765/x",
                                  "127.0.0.1:notaport", "127.0.0.1 :8765"])
def test_a_host_header_that_is_not_a_plain_name_and_port_is_refused(client, host):
    assert client.get("/api/health", headers={"host": host}).status_code == 403


def test_it_refuses_an_api_read_a_browser_marks_as_same_site(client):
    """Another server on this machine is the same site, on another port."""
    assert client.get("/api/health", headers={"sec-fetch-site": "same-site"}).status_code == 403


def test_a_host_in_capitals_is_still_this_machine(client):
    assert client.get("/api/health", headers={"host": "LOCALHOST:8765"}).status_code == 200
