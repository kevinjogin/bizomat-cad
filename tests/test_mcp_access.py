"""Who may use the CADOS MCP server. There is no server password: a person's own CADOS account is the only key.

- A public server with no account answers no MCP request (setup mode) until its owner creates the first account.
- Each MCP request is one signed-in person: an AI app's OAuth token (per person and app) or that person's own private
  address. Nothing else gets in.
- Suspending a person stops everything at once: sign-in, browser sessions, AI app tokens and refreshes, the private
  address and the add-in key. Resuming lets them back in without new setup for the address and key.
- Expired sessions and expired tokens are refused.
"""
import pytest
from fastapi.testclient import TestClient

from opensketch import accounts, auth, mcpauth, server, swbridge
from tests.test_mcp_oauth import ACCEPT, _connect, _mcp, _register

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSKETCH_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("OPENSKETCH_PUBLIC_URL", "http://testserver")  # a server others can reach (as on Fly)
    for k in ("OPENSKETCH_PASSWORD", "OPENSKETCH_MCP_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    auth._fails.clear()
    mcpauth._codes.clear()
    mcpauth._reg_hits.clear()
    return tmp_path


def _owner_with_open_signup():
    c = TestClient(server.app)
    r = c.post("/setup", data={"name": "Owner", "email": "owner@example.com", "new_password": "owner-pass-1",
                               "open_signup": "on", "next": "/"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


def _sign_up(email="ann@example.com", pw="anns-pass-1"):
    c = TestClient(server.app)
    r = c.post("/signup", data={"name": "Ann", "email": email, "new_password": pw}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


def _private(c) -> str:
    return "/mcp/" + c.get("/api/solidworks").json()["private_url"].split("/mcp/")[1]


def test_a_public_server_answers_no_mcp_until_it_has_an_owner():
    with TestClient(server.app) as app:
        assert app.post(f"/mcp/{auth.mcp_token()}", json=INIT, headers=ACCEPT).status_code == 404  # not even the server-wide key
        assert app.post("/mcp", json=INIT, headers=ACCEPT).status_code == 401
        assert app.get("/api/solidworks").status_code == 401
        ok, _ = swbridge.resolve(swbridge.key_for(None))
        assert ok  # (the add-in key exists, but every page that shows it needs sign-in, and none answers yet)
        assert app.get("/dashboard", follow_redirects=False).headers["location"] == "/setup"
    _owner_with_open_signup()
    with TestClient(server.app) as app:
        assert app.post("/mcp", json=INIT, headers=ACCEPT).status_code == 401  # still: sign in first


def test_each_mcp_request_is_one_signed_in_person():
    owner = _owner_with_open_signup()
    ann = _sign_up()
    with TestClient(server.app) as app:
        # an AI app (Claude, ChatGPT...) connects with OAuth: Ann signs in once, clicks Allow, and the app gets her token
        tok = _connect(ann, app, _register(app))
        r = _mcp(app, tok["access_token"], "tools/list")
        assert r.status_code == 200 and any(t["name"] == "sw_status" for t in r.json()["result"]["tools"])
        assert mcpauth.user_for_access(tok["access_token"])[1]["email"] == "ann@example.com"
        # no token, a made-up token, or a made-up private address: refused
        assert app.post("/mcp", json=INIT, headers=ACCEPT).status_code == 401
        assert _mcp(app, "osa_" + "x" * 40, "tools/list").status_code == 401
        assert app.post("/mcp/" + "0" * 32, json=INIT, headers=ACCEPT).status_code == 404
        # her private address (for apps that cannot sign in) is hers alone, and differs from the owner's
        assert app.post(_private(ann), json=INIT, headers=ACCEPT).status_code == 200
        assert _private(ann) != _private(owner)
        # a second connect is not a second password prompt: a signed-in person only clicks Allow
        again = _connect(ann, app, _register(app, client_name="ChatGPT", redirect="https://chatgpt.com/connector_platform_oauth_redirect"),
                         redirect="https://chatgpt.com/connector_platform_oauth_redirect")
        assert _mcp(app, again["access_token"], "tools/list").status_code == 200


def test_suspending_a_person_stops_every_way_in_at_once():
    owner = _owner_with_open_signup()
    ann = _sign_up()
    ann_id = ann.get("/api/account").json()["user"]["id"]
    with TestClient(server.app) as app:
        client = _register(app)
        tok = _connect(ann, app, client)
        private, key = _private(ann), ann.get("/api/solidworks").json()["key"]
        assert swbridge.resolve(key)[0]

        # only the owner suspends, and never the owner account
        assert ann.post(f"/api/account/users/{ann_id}/suspend", json={"suspended": True}).status_code == 403
        me = owner.get("/api/account").json()["user"]["id"]
        assert owner.post(f"/api/account/users/{me}/suspend", json={"suspended": True}).status_code == 400
        r = owner.post(f"/api/account/users/{ann_id}/suspend", json={"suspended": True})
        assert r.status_code == 200 and r.json()["user"]["suspended"] is True

        assert ann.get("/api/solidworks").status_code == 401                         # her browser session ended
        assert _mcp(app, tok["access_token"], "tools/list").status_code == 401       # her AI apps stop at once
        assert app.post(private, json=INIT, headers=ACCEPT).status_code == 404       # her private address too
        assert not swbridge.resolve(key)[0]                                           # and her add-in key
        refresh = app.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                                 "client_id": client["client_id"]})
        assert refresh.status_code == 400 and refresh.json()["error"] == "invalid_grant"
        back = TestClient(server.app)
        r = back.post("/login", data={"email": "ann@example.com", "password": "anns-pass-1", "next": "/"})
        assert r.status_code == 403 and "suspended" in r.text                      # the right password, still no
        assert back.post("/login", data={"email": "ann@example.com", "password": "wrong-pass-1", "next": "/"}).status_code == 401
        people = {p["email"]: p for p in owner.get("/api/admin/people").json()["people"]}
        assert people["ann@example.com"]["suspended"] is True

        # resumed: she signs in again; her private address and add-in key work again; an AI app reconnects with Allow
        assert owner.post(f"/api/account/users/{ann_id}/suspend", json={"suspended": False}).status_code == 200
        assert back.post("/login", data={"email": "ann@example.com", "password": "anns-pass-1", "next": "/"},
                         follow_redirects=False).status_code == 303
        assert app.post(private, json=INIT, headers=ACCEPT).status_code == 200 and swbridge.resolve(key)[0]
        assert _mcp(app, _connect(back, app, client)["access_token"], "tools/list").status_code == 200


def test_expired_sessions_and_tokens_are_refused(monkeypatch):
    _owner_with_open_signup()
    ann = _sign_up()
    with TestClient(server.app) as app:
        tok = _connect(ann, app, _register(app))
        assert _mcp(app, tok["access_token"], "tools/list").status_code == 200
        now = accounts.time.time()
        monkeypatch.setattr(mcpauth.time, "time", lambda: now + mcpauth.ACCESS_TTL + 5)
        assert _mcp(app, tok["access_token"], "tools/list").status_code == 401   # the app refreshes, or signs in again
        monkeypatch.setattr(accounts.time, "time", lambda: now + accounts.SESSION_DAYS * 86400 + 5)
        assert ann.get("/api/solidworks").status_code == 401
        assert ann.get("/dashboard", follow_redirects=False).headers["location"].startswith("/login")


def test_no_shared_server_password_anywhere():
    owner = _owner_with_open_signup()
    ann = _sign_up()
    pages = [TestClient(server.app).get(p).text for p in ("/login", "/signup", "/docs", "/")]
    pages += [owner.get(p).text for p in ("/dashboard", "/admin", "/settings", "/solidworks", "/assistant")]
    pages += [ann.get(p).text for p in ("/dashboard", "/settings")]
    for t in pages:
        assert "server password" not in t.lower() and "server_password" not in t and "OPENSKETCH_PASSWORD" not in t
    assert owner.get("/api/admin/server-password").status_code == 404
    assert "reset_with_server_password" not in owner.get("/api/account").json()
