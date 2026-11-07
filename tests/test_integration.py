import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse
import pytest

pytestmark = pytest.mark.asyncio
REDIRECT = "http://127.0.0.1:8000/docs/oauth2-redirect"


async def signup_and_login(client, email):
    result = await client.post("/auth/register", json={"email": email, "password": "TestPass123!"})
    assert result.status_code == 201, result.text
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = dict(response_type="code", client_id="swagger-ui", redirect_uri=REDIRECT,
                  code_challenge=challenge, code_challenge_method="S256", state="test")
    page = await client.get("/oauth/authorize", params=params)
    assert page.status_code == 200
    response = await client.post("/oauth/authorize", data={**params, "email": email, "password": "TestPass123!"})
    assert response.status_code == 303
    code = parse_qs(urlparse(response.headers["location"]).query)["code"][0]
    token_response = await client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code,
                            "client_id": "swagger-ui", "redirect_uri": REDIRECT, "code_verifier": verifier})
    assert token_response.status_code == 200, token_response.text
    replay = await client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code,
                            "client_id": "swagger-ui", "redirect_uri": REDIRECT, "code_verifier": verifier})
    assert replay.status_code == 400
    return {"Authorization": "Bearer " + token_response.json()["access_token"]}


async def test_links_redirect_click_limit_and_soft_delete(client):
    headers = await signup_and_login(client, "a@example.com")
    response = await client.post("/links", headers=headers,
        json={"original_url": "https://example.com/a", "max_clicks": 2})
    assert response.status_code == 201, response.text
    link = response.json()
    duplicate = await client.post("/links", headers=headers,
        json={"original_url": "https://example.com/a"})
    assert duplicate.status_code == 200
    assert duplicate.json()["code"] == link["code"]
    for _ in range(2):
        r = await client.get("/" + link["code"])
        assert r.status_code == 302
        assert r.headers["location"] == "https://example.com/a"
    assert (await client.get("/" + link["code"])).status_code == 419
    listing = (await client.get("/links", headers=headers)).json()
    assert listing[0]["clicks"] == 2
    assert (await client.delete("/links/" + str(link["id"]), headers=headers)).status_code == 204
    assert (await client.get("/" + link["code"])).status_code == 404


async def test_limit_ownership_and_reuse_slot(client):
    a = await signup_and_login(client, "first@example.com")
    b = await signup_and_login(client, "second@example.com")
    ids = []
    for n in range(3):
        r = await client.post("/links", headers=a, json={"original_url": f"https://example.com/{n}"})
        assert r.status_code == 201
        ids.append(r.json()["id"])
    assert (await client.post("/links", headers=a, json={"original_url": "https://example.com/extra"})).status_code == 409
    assert (await client.delete(f"/links/{ids[0]}", headers=b)).status_code == 404
    assert (await client.get("/links", headers=b)).json() == []
    assert (await client.delete(f"/links/{ids[0]}", headers=a)).status_code == 204
    assert (await client.post("/links", headers=a, json={"original_url": "https://example.com/extra"})).status_code == 201


async def test_expired_link_and_auth_required(client):
    assert (await client.get("/links")).status_code == 401
    headers = await signup_and_login(client, "expire@example.com")
    r = await client.post("/links", headers=headers,
                          json={"original_url": "https://example.com", "expires_at": "2020-01-01T00:00:00Z"})
    assert r.status_code == 422
