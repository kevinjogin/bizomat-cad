"""One public address, and the other host names the same app answers on.

- OPENSKETCH_PUBLIC_URL: the canonical address (e.g. "https://cados.kevos.com", later "https://cad.bizomat.ai"):
  links, canonical tags, OAuth metadata for new connections.
- OPENSKETCH_REDIRECT_HOSTS: old host names, comma separated. A browser asking one of them for a page gets a
  permanent redirect (301) to the same path and query on the canonical address; the browser keeps the #fragment.
- OPENSKETCH_ALIAS_HOSTS: host names served as they are (no redirect), e.g. a new address whose DNS is being set up
  before it becomes the canonical one.

The canonical host is ignored in both lists, so the lists can name every address the app has had or will have, and
moving the canonical address is a change of OPENSKETCH_PUBLIC_URL alone, in any order: the host it leaves joins the
old ones at once (when listed in OPENSKETCH_REDIRECT_HOSTS), the host it takes stops being redirected.

Only the Host header is read (the proxy sets it from the address the visitor used); X-Forwarded-Host is never trusted.

Not redirected, on purpose:
- anything but GET and HEAD (a 301 makes a browser drop a POST's body);
- /healthz (the deploy check and the supervisor);
- the paths programs call with their own credentials: the MCP endpoints and their uploads and downloads, OAuth
  metadata, registration, token and revoke, the add-in's link (/mcp/sw/), the KEVOS Companion's API (/v2/), and the
  page API (/api/). A connector, add-in or computer set up with an old address keeps working until it is moved.

On an old or alias host those paths keep that host as their own address (machine_base): the OAuth metadata names it
as the resource and the issuer, and upload and download links use it, because an AI app checks that the metadata
names the address it connected to. Any other host name gets the canonical address (a Host header is never echoed).
"""

from __future__ import annotations

import contextvars
import os
from urllib.parse import urlsplit

KEEP_PREFIXES = ("/mcp", "/solidworks/mcp", "/oauth/register", "/oauth/token", "/oauth/revoke", "/.well-known/",
                 "/v2/", "/api/")
KEEP_PATHS = ("/healthz",)

# The old or alias host's base URL ("https://cados.fly.dev") while a request that came in on it is served, else "".
_machine_base: contextvars.ContextVar = contextvars.ContextVar("opensketch_machine_base", default="")


def _host_only(value: str) -> str:
    """'Cados.Fly.Dev:443' -> 'cados.fly.dev' (IPv6 literals keep their brackets)."""
    v = (value or "").strip().lower().rstrip(".")
    if v.startswith("["):
        return v.split("]")[0] + "]"
    return v.split(":")[0].rstrip(".")


def _hosts(name: str) -> frozenset[str]:
    return frozenset(h for h in (_host_only(x) for x in os.environ.get(name, "").split(",")) if h)


def canonical() -> tuple[str, str]:
    """(canonical host, canonical base URL), or ("", "") when OPENSKETCH_PUBLIC_URL is unset or not a bare origin."""
    target = os.environ.get("OPENSKETCH_PUBLIC_URL", "").strip().rstrip("/")
    parts = urlsplit(target)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.path not in ("", "/"):
        return "", ""
    return _host_only(parts.netloc), f"{parts.scheme}://{parts.netloc}"


def settings() -> tuple[frozenset[str], str]:
    """(old hosts to redirect, canonical base URL), or (empty, "") when off. The canonical host is never redirected."""
    host, base = canonical()
    if not base:
        return frozenset(), ""
    hosts = _hosts("OPENSKETCH_REDIRECT_HOSTS") - {host}
    return (hosts, base) if hosts else (frozenset(), "")


def alias_hosts() -> frozenset[str]:
    """Host names served as they are that keep their own address for programs (not the canonical one, not an old one)."""
    host, base = canonical()
    if not base:
        return frozenset()
    return _hosts("OPENSKETCH_ALIAS_HOSTS") - {host} - _hosts("OPENSKETCH_REDIRECT_HOSTS")


def _known_hosts() -> frozenset[str]:
    return settings()[0] | alias_hosts()


def legacy_bases() -> list[str]:
    """Base URLs of the old and alias host names ("https://cados.fly.dev", ...), or []."""
    _, base = canonical()
    scheme = urlsplit(base).scheme if base else ""
    return [f"{scheme}://{h}" for h in sorted(_known_hosts())]


def _legacy_base(host_header: str) -> str:
    h = _host_only(host_header)
    if not h or h not in _known_hosts():
        return ""
    return f"{urlsplit(canonical()[1]).scheme}://{h}"


def machine_base(headers: dict | None = None) -> str:
    """The old or alias host's base URL when the request came in on one of them, else "" (use the canonical address).
    With headers, from their Host header; without, for the request being served (set by CanonicalHost)."""
    if headers is not None:
        return _legacy_base(headers.get("host", ""))
    return _machine_base.get()


def _kept(path: str) -> bool:
    return path in KEEP_PATHS or path.startswith(KEEP_PREFIXES)


def _host(scope) -> str:
    for k, v in scope.get("headers") or []:
        if k == b"host":
            return v.decode("latin-1")
    return ""


def location(scope) -> str | None:
    """The redirect target for this request, or None to serve it here."""
    if scope.get("type") != "http" or scope.get("method") not in ("GET", "HEAD"):
        return None
    hosts, base = settings()
    if not hosts:
        return None
    if _host_only(_host(scope)) not in hosts:
        return None
    path = scope.get("path") or "/"
    if _kept(path):
        return None
    raw = scope.get("raw_path")
    target_path = raw.decode("latin-1") if raw else path
    if not target_path.startswith("/") or target_path.startswith("//"):
        target_path = "/" + target_path.lstrip("/")
    q = scope.get("query_string") or b""
    return base + target_path + ("?" + q.decode("latin-1") if q else "")


class CanonicalHost:
    """ASGI middleware, outermost: answers 301 before anything else runs."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        to = location(scope)
        if to is None:
            if scope.get("type") != "http":
                return await self.app(scope, receive, send)
            tok = _machine_base.set(_legacy_base(_host(scope)))
            try:
                return await self.app(scope, receive, send)
            finally:
                _machine_base.reset(tok)
        await send({"type": "http.response.start", "status": 301, "headers": [
            (b"location", to.encode("latin-1")), (b"content-type", b"text/plain; charset=utf-8"),
            (b"cache-control", b"public, max-age=86400"), (b"content-length", str(len(b"Moved to " + to.encode("latin-1"))).encode())]})
        await send({"type": "http.response.body", "body": b"" if scope.get("method") == "HEAD" else b"Moved to " + to.encode("latin-1")})
