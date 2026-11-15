from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from beetbox.auth import TrustedProxies
from beetbox.settings import Settings

PROXY = ("10.0.0.2", 40000)  # inside BEETBOX_TRUSTED_PROXIES
OTHER = ("172.20.0.9", 40000)  # another container on the same network
SIGNED = {"X-authentik-username": "niki", "X-authentik-groups": "music|media_admins"}


@pytest.fixture
def app(env, fake_source, monkeypatch):
    from beetbox.main import create_app

    monkeypatch.setenv("BEETBOX_TRUSTED_PROXIES", "10.0.0.0/24")
    monkeypatch.setenv("BEETBOX_ADMIN_GROUPS", "media_admins,lldap_admin")
    monkeypatch.setenv("BEETBOX_LOGOUT_URL", "/outpost.goauthentik.io/sign_out")
    return create_app(Settings.from_env(), background=False)


def test_trusted_proxy_signs_in(app):
    c = TestClient(app, client=PROXY)
    r = c.get("/", headers=SIGNED, follow_redirects=False)
    assert r.status_code == 200
    assert "niki" in r.text


def test_not_in_an_admin_group(app):
    c = TestClient(app, client=PROXY)
    headers = {**SIGNED, "X-authentik-groups": "music"}
    r = c.get("/", headers=headers, follow_redirects=False)
    assert r.status_code == 403 and "isn't in a group" in r.text


def test_headers_from_anyone_else_are_ignored(app):
    c = TestClient(app, client=OTHER)
    r = c.get("/", headers=SIGNED, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_forwarded_for_cannot_fake_the_proxy(app):
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    from beetbox.main import RecordPeer

    served = RecordPeer(ProxyHeadersMiddleware(app, trusted_hosts="*"))
    c = TestClient(served, client=OTHER)
    r = c.get("/", headers={**SIGNED, "X-Forwarded-For": PROXY[0]}, follow_redirects=False)
    assert r.status_code == 303
    # ...while the real proxy still gets through the same stack.
    c = TestClient(served, client=PROXY)
    r = c.get("/", headers={**SIGNED, "X-Forwarded-For": "203.0.113.7"}, follow_redirects=False)
    assert r.status_code == 200


def test_password_login_still_works_next_to_the_proxy(app):
    c = TestClient(app, client=OTHER)
    c.post("/login", data={"password": "secret"})
    assert c.get("/", follow_redirects=False).status_code == 200


def test_logout_goes_to_the_proxy_sign_out(app):
    c = TestClient(app, client=PROXY)
    c.get("/", headers=SIGNED)
    r = c.post("/logout", headers=SIGNED, follow_redirects=False)
    assert r.headers["location"] == "/outpost.goauthentik.io/sign_out"
    c = TestClient(app, client=OTHER)
    c.post("/login", data={"password": "secret"})
    r = c.post("/logout", follow_redirects=False)
    assert r.headers["location"] == "/login"


def test_hostnames_are_resolved(monkeypatch):
    import socket

    from beetbox import auth

    ips = {"caddy": "172.18.0.4"}

    def lookup(host, port):
        if host not in ips:
            raise socket.gaierror(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ips[host], 0))]

    clock = [5.0]  # seconds since boot: under the TTL, as on a fresh machine
    monkeypatch.setattr(auth.socket, "getaddrinfo", lookup)
    monkeypatch.setattr(auth.time, "monotonic", lambda: clock[0])
    proxies = TrustedProxies(["caddy", "gone"])
    assert proxies.trusts("172.18.0.4")
    assert not proxies.trusts("10.1.2.3")
    assert not proxies.trusts("not-an-ip")
    # Recreated containers get new addresses: looked up again after the TTL.
    ips["caddy"] = "172.18.0.9"
    assert not proxies.trusts("172.18.0.9")  # still cached
    clock[0] += TrustedProxies.TTL + 1
    assert proxies.trusts("172.18.0.9")
    assert not TrustedProxies([])
