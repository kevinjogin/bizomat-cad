"""Host names: the canonical address (OPENSKETCH_PUBLIC_URL), old hosts that send browsers there with a 301 keeping the
path and the query (OPENSKETCH_REDIRECT_HOSTS), and alias hosts served as they are (OPENSKETCH_ALIAS_HOSTS). Programs on
an old or alias host (health checks, MCP, OAuth, the device and add-in links, the page API) are served as before and
their OAuth metadata and links keep naming that host. The canonical host is ignored in both lists, so moving it is a
change of OPENSKETCH_PUBLIC_URL alone.

Phase A (now): canonical cados.kevos.com, old cados.fly.dev, alias cad.bizomat.ai (its DNS is still to be made).
Phase B (after DNS): canonical cad.bizomat.ai; cados.kevos.com and cados.fly.dev old. bizomat.ai is the BIZOMAT
website's address: the CAD app never names it."""
import base64
import contextvars
import hashlib
import re
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from opensketch import canonical, mcpauth, server, uploads

KEVOS, FLYDEV, CAD = "cados.kevos.com", "cados.fly.dev", "cad.bizomat.ai"
ACCEPT = {"Accept": "application/json, text/event-stream"}


def phase(monkeypatch, public):
    monkeypatch.setenv("OPENSKETCH_PUBLIC_URL", "https://" + public)
    monkeypatch.setenv("OPENSKETCH_REDIRECT_HOSTS", f"{FLYDEV},{KEVOS}")
    monkeypatch.setenv("OPENSKETCH_ALIAS_HOSTS", CAD)


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSKETCH_DATA", str(tmp_path / "data"))
    for k in ("OPENSKETCH_PASSWORD", "OPENSKETCH_MCP_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    phase(monkeypatch, KEVOS)
    mcpauth._codes.clear()
    mcpauth._reg_hits.clear()


def _get(path, host=FLYDEV, method="GET", **kw):
    c = TestClient(server.app, base_url="https://" + host)
    return c.request(method, path, headers={"host": host, **kw.pop("headers", {})}, follow_redirects=False, **kw)


PAGES = ["/", "/docs", "/overview", "/login?next=dashboard", "/login?next=%2Fdashboard&x=a%20b&x=2", "/dashboard",
         "/privacy", "/download/solidworks", "/oauth/authorize?client_id=c&state=s", "/devices/pair?code=ABCD-EFGH",
         "/ui/cados.css", "/a%2Fb"]
PROGRAMS = ["/healthz", "/mcp", "/mcp/", "/mcp/some-private-key", "/solidworks/mcp",
            "/.well-known/oauth-protected-resource", "/.well-known/oauth-authorization-server/mcp", "/v2/keys",
            "/v2/bridge/update.json", "/v2/device/next", "/mcp/sw/next", "/mcp/artifacts/x/y", "/mcp/uploads/x",
            "/api/solidworks", "/oauth/token", "/oauth/register", "/oauth/revoke"]


# ----------------------------------------------------------------------------- phase A: now

@pytest.mark.parametrize("path", PAGES)
def test_phase_a_the_fly_origin_redirects_pages_keeping_path_and_query(path):
    r = _get(path)
    assert r.status_code == 301 and r.headers["location"] == "https://" + KEVOS + path
    h = _get(path, method="HEAD")
    assert h.status_code == 301 and h.headers["location"] == "https://" + KEVOS + path and h.content == b""


@pytest.mark.parametrize("host", [KEVOS, CAD, "bizomat.ai", "evil.cados.fly.dev", "127.0.0.1:8080"])
def test_phase_a_the_canonical_alias_and_other_hosts_are_served(host):
    assert _get("/docs", host).status_code == 200
    assert _get("/", host).status_code in (200, 303)  # 303: setup first, on a server with no account yet


def test_host_header_case_port_and_trailing_dot():
    for host in ("CADOS.FLY.DEV", "cados.fly.dev:443", "cados.fly.dev."):
        assert _get("/docs", host).headers["location"] == "https://" + KEVOS + "/docs", host


@pytest.mark.parametrize("host", [FLYDEV, KEVOS, CAD])
@pytest.mark.parametrize("path", PROGRAMS)
def test_programs_are_never_redirected(host, path):
    scope = {"type": "http", "method": "GET", "path": path, "raw_path": path.encode(), "query_string": b"x=1",
             "headers": [(b"host", host.encode())]}
    assert canonical.location(scope) is None, path
    if not path.startswith(("/mcp", "/solidworks/mcp")):  # the MCP endpoints need the app's lifespan to answer
        assert _get(path, host).status_code != 301, path


def test_only_get_and_head_are_redirected():
    for method in ("POST", "PUT", "DELETE", "OPTIONS"):
        assert _get("/login", method=method).status_code != 301, method


def test_forwarded_host_is_not_trusted():
    assert _get("/docs", KEVOS, headers={"x-forwarded-host": FLYDEV}).status_code == 200
    r = _get("/docs", FLYDEV, headers={"x-forwarded-host": KEVOS})
    assert r.status_code == 301 and r.headers["location"] == "https://" + KEVOS + "/docs"


def test_the_canonical_host_is_ignored_in_both_lists_and_off_unless_set(monkeypatch):
    assert canonical.settings() == (frozenset({FLYDEV}), "https://" + KEVOS)
    assert canonical.alias_hosts() == frozenset({CAD})
    monkeypatch.setenv("OPENSKETCH_ALIAS_HOSTS", f"{CAD},{KEVOS},{FLYDEV}")  # canonical and old hosts are not aliases
    assert canonical.alias_hosts() == frozenset({CAD})
    monkeypatch.setenv("OPENSKETCH_REDIRECT_HOSTS", KEVOS)  # only the canonical host: nothing to redirect
    assert canonical.settings() == (frozenset(), "") and _get("/docs", KEVOS).status_code == 200
    monkeypatch.setenv("OPENSKETCH_REDIRECT_HOSTS", FLYDEV)
    monkeypatch.setenv("OPENSKETCH_PUBLIC_URL", "https://cados.kevos.com/sub")  # not a bare origin
    assert _get("/docs").status_code == 200 and canonical.legacy_bases() == []
    monkeypatch.delenv("OPENSKETCH_PUBLIC_URL")
    assert _get("/docs").status_code == 200 and canonical.machine_base({"host": CAD}) == ""


def test_canonical_tags_name_the_public_address_on_every_host():
    for host in (KEVOS, CAD, "bizomat.ai"):
        html = _get("/docs", host).text
        assert '<link rel="canonical" href="https://cados.kevos.com/docs">' in html, host
        assert "GATEWAY_URL=https://cados.kevos.com" in html, host  # the docs give this server's own address


# ----------------------------------------------------------------------------- phase B: after cad.bizomat.ai's DNS

@pytest.mark.parametrize("old", [KEVOS, FLYDEV])
@pytest.mark.parametrize("path", PAGES)
def test_phase_b_old_hosts_redirect_pages_to_cad_bizomat_ai(monkeypatch, old, path):
    phase(monkeypatch, CAD)  # the only change: OPENSKETCH_PUBLIC_URL
    r = _get(path, old)
    assert r.status_code == 301 and r.headers["location"] == "https://" + CAD + path


def test_phase_b_serves_cad_bizomat_ai_and_names_it_everywhere(monkeypatch):
    phase(monkeypatch, CAD)
    assert canonical.settings() == (frozenset({FLYDEV, KEVOS}), "https://" + CAD) and canonical.alias_hosts() == frozenset()
    r = _get("/docs", CAD)
    assert r.status_code == 200
    assert '<link rel="canonical" href="https://cad.bizomat.ai/docs">' in r.text and "GATEWAY_URL=https://cad.bizomat.ai" in r.text
    assert "//bizomat.ai" not in r.text  # never the website's address
    assert _get("/docs", "bizomat.ai").status_code == 200  # not an old host: served until its DNS moves to the website


# ----------------------------------------------------------------------------- programs set up with each address

def _browser(host):
    return TestClient(server.app, base_url="https://" + host)


def _setup_owner(host):
    b = _browser(host)
    r = b.post("/setup", data={"name": "Owner", "email": "owner@example.com", "new_password": "correct horse",
                               "next": "/"}, headers={"host": host}, follow_redirects=False)
    assert r.status_code in (302, 303), r.text[:300]
    return b


def _signed_in(host):
    b = _browser(host)
    r = b.post("/login", data={"email": "owner@example.com", "password": "correct horse", "next": "/"},
               headers={"host": host}, follow_redirects=False)
    assert r.status_code in (302, 303), r.text[:300]
    return b


@pytest.mark.parametrize("public", [KEVOS, CAD])
def test_oauth_metadata_names_the_address_the_app_connected_to(monkeypatch, public):
    phase(monkeypatch, public)
    _setup_owner(public)
    for host in (KEVOS, FLYDEV, CAD, "bizomat.ai"):
        base = "https://" + (host if host != "bizomat.ai" else public)  # an unlisted host gets the canonical address
        for path in ("/mcp", "/solidworks/mcp"):
            pr = _get("/.well-known/oauth-protected-resource" + path, host)
            assert pr.status_code == 200, pr.text
            assert pr.json()["resource"] == base + path and pr.json()["authorization_servers"] == [base], (host, path)
        md = _get("/.well-known/oauth-authorization-server", host).json()
        assert md["issuer"] == base
        for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint"):
            assert md[k].startswith(base + "/oauth/"), (host, k, md[k])
        r = _get("/mcp", host, method="POST", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                 headers=ACCEPT)
        assert r.status_code == 401
        assert f'resource_metadata="{base}/.well-known/oauth-protected-resource/mcp"' in r.headers["www-authenticate"]


def _pkce():
    v = secrets.token_urlsafe(48)
    return v, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")


CALLBACK = "https://claude.ai/api/mcp/auth_callback"


def _sign_in(app, browsers, host, public):
    """An AI app set up with https://<host>/mcp signs in: discovery, registration and the token on that host; on an
    old host the person's browser is sent on to the canonical address for sign-in and consent."""
    base, canon = "https://" + host, "https://" + public
    hdr = {"host": host}
    reg = app.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": [CALLBACK]}, headers=hdr)
    assert reg.status_code == 201, reg.text
    cid = reg.json()["client_id"]
    verifier, chal = _pkce()
    q = {"response_type": "code", "client_id": cid, "redirect_uri": CALLBACK, "state": "s1", "code_challenge": chal,
         "code_challenge_method": "S256", "scope": "opensketch", "resource": base + "/mcp"}
    page_host = host
    r = browsers[host].get(base + "/oauth/authorize", params=q, headers=hdr, follow_redirects=False)
    if r.status_code == 301:  # an old host: the same request on the canonical address
        assert r.headers["location"].startswith(canon + "/oauth/authorize?")
        page_host = public
        r = browsers[public].get(r.headers["location"], headers={"host": public}, follow_redirects=False)
    assert r.status_code == 200 and b"Allow" in r.content, r.text[:300]
    req = re.search(r'name="req" value="([^"]+)"', r.text).group(1)
    r = browsers[page_host].post(f"https://{page_host}/oauth/authorize", data={"req": req}, headers={"host": page_host},
                                 follow_redirects=False)
    assert r.status_code == 303
    back = parse_qs(urlparse(r.headers["location"]).query)
    assert back["state"] == ["s1"]
    tok = app.post("/oauth/token", headers=hdr, data={
        "grant_type": "authorization_code", "code": back["code"][0], "redirect_uri": CALLBACK, "client_id": cid,
        "code_verifier": verifier, "resource": base + "/mcp"})
    assert tok.status_code == 200, tok.text
    return tok.json(), back["iss"][0], cid


def _initialize(app, host, access):
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
    return app.post("/mcp", json=body, headers={**ACCEPT, "host": host, "Authorization": f"Bearer {access}"})


@pytest.mark.parametrize("public", [KEVOS, CAD])
def test_apps_set_up_with_any_address_sign_in_and_keep_working(monkeypatch, public):
    phase(monkeypatch, public)
    _setup_owner(public)
    # sessions are per host: the person is signed in wherever the consent page is shown (canonical and alias hosts)
    browsers = {h: _signed_in(h) for h in (KEVOS, CAD)}
    browsers[FLYDEV] = _browser(FLYDEV)
    with TestClient(server.app, base_url="https://" + public) as app:
        for host in (KEVOS, FLYDEV, CAD):
            tok, iss, cid = _sign_in(app, browsers, host, public)
            assert iss == "https://" + host, (public, host)  # RFC 9207: the issuer whose metadata it read
            assert _initialize(app, host, tok["access_token"]).status_code == 200, (public, host)
            assert _initialize(app, public, tok["access_token"]).status_code == 200, (public, host)  # not tied to a host
            refreshed = app.post("/oauth/token", headers={"host": host}, data={
                "grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": cid,
                "resource": "https://" + host + "/mcp"})
            assert refreshed.status_code == 200, refreshed.text
            assert _initialize(app, host, refreshed.json()["access_token"]).status_code == 200


def test_sign_in_to_another_server_is_refused():
    browser = _setup_owner(KEVOS)
    reg = browser.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": [CALLBACK]},
                       headers={"host": KEVOS}).json()
    _, chal = _pkce()
    for res in ("https://evil.example/mcp", "https://cados.kevos.com.evil.example/mcp", "https://bizomat.ai/mcp",
                "https://kevos.com/mcp"):
        q = {"response_type": "code", "client_id": reg["client_id"], "redirect_uri": CALLBACK, "state": "s",
             "code_challenge": chal, "code_challenge_method": "S256", "resource": res}
        r = browser.get("/oauth/authorize", params=q, headers={"host": KEVOS}, follow_redirects=False)
        assert r.status_code == 400 and "location" not in r.headers, res


def test_links_for_programs_use_the_address_of_the_request():
    seen = []

    async def app(scope, receive, send):
        seen.append(canonical.machine_base())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    c = TestClient(canonical.CanonicalHost(app))
    for host in (FLYDEV, CAD, KEVOS, "bizomat.ai", "evil.example"):
        c.post("/mcp", headers={"host": host})
    assert seen == ["https://cados.fly.dev", "https://cad.bizomat.ai", "", "", ""] and canonical.machine_base() == ""
    ctx = contextvars.copy_context()
    ctx.run(canonical._machine_base.set, "https://cad.bizomat.ai")
    assert ctx.run(uploads.create, None, "plate.step", 2**20)["upload_url"].startswith("https://cad.bizomat.ai/mcp/uploads/")
    assert uploads.create(None, "plate.step", 2**20)["upload_url"].startswith("https://cados.kevos.com/mcp/uploads/")
    assert canonical.legacy_bases() == ["https://cad.bizomat.ai", "https://cados.fly.dev"]
