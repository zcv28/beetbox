"""Login: a single shared password, LDAP search-then-bind, or a trusted proxy's headers.

LDAP and proxy sign-ins also need membership of one of ``BEETBOX_ADMIN_GROUPS``.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import socket
import threading
import time
from collections.abc import Iterable

from .settings import Settings

log = logging.getLogger("beetbox.auth")


class AuthError(Exception):
    pass


NOT_IN_GROUP = "Your account isn't in a group allowed to use beetbox."


def allowed(settings: Settings, groups: Iterable[str]) -> bool:
    """Whether someone in ``groups`` may use beetbox (any group when none are set)."""
    if not settings.admin_groups:
        return True
    wanted = {g.casefold() for g in settings.admin_groups}
    return any(g.strip().casefold() in wanted for g in groups)


def group_names(dns: Iterable[str]) -> list[str]:
    """``cn=media_admins,ou=groups,...`` -> ``media_admins``."""
    from ldap3.utils.dn import parse_dn

    names = []
    for dn in dns:
        try:
            names.append(parse_dn(str(dn))[0][1])
        except Exception:  # noqa: BLE001 - not a DN: take it as a group name
            names.append(str(dn))
    return names


class TrustedProxies:
    """Hostnames, IPs and networks whose sign-in headers are believed.

    Hostnames (a compose service such as ``caddy``) are looked up again every minute,
    since a container's address changes when it is recreated.
    """

    TTL = 60.0

    def __init__(self, entries: Iterable[str]):
        self.networks = []
        self.hosts = []
        for e in entries:
            try:
                self.networks.append(ipaddress.ip_network(e, strict=False))
            except ValueError:
                self.hosts.append(e)
        self._resolved: set[ipaddress._BaseAddress] = set()
        self._at = 0.0
        self._lock = threading.Lock()

    def __bool__(self) -> bool:
        return bool(self.networks or self.hosts)

    def _host_ips(self) -> set:
        with self._lock:
            if time.monotonic() - self._at > self.TTL:
                ips = set()
                for h in self.hosts:
                    try:
                        for *_, addr in socket.getaddrinfo(h, None):
                            ips.add(ipaddress.ip_address(addr[0]))
                    except OSError:
                        log.warning("trusted proxy %s doesn't resolve", h)
                self._resolved, self._at = ips, time.monotonic()
            return self._resolved

    def trusts(self, peer: str | None) -> bool:
        try:
            ip = ipaddress.ip_address(peer or "")
        except ValueError:
            return False
        return any(ip in n for n in self.networks) or (bool(self.hosts) and ip in self._host_ips())


def proxy_user(settings: Settings, proxies: TrustedProxies, peer: str | None, headers):
    """The user a trusted proxy signed in, as ``(name, allowed)``, or None.

    None when the request didn't come from a trusted proxy or carries no user header.
    """
    if not proxies or not proxies.trusts(peer):
        return None
    name = (headers.get(settings.trusted_user_header) or "").strip()
    if not name:
        return None
    groups = (headers.get(settings.trusted_groups_header) or "").split("|")
    return name, allowed(settings, groups)


class RateLimiter:
    """Slow down brute force: max `limit` failures per key per window."""

    def __init__(self, limit: int = 10, window: float = 300.0):
        self.limit = limit
        self.window = window
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            fails = [t for t in self._fails.get(key, []) if now - t < self.window]
            self._fails[key] = fails
            return len(fails) >= self.limit

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails.setdefault(key, []).append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


def check_password(settings: Settings, password: str) -> bool:
    return bool(settings.password) and hmac.compare_digest(
        password.encode(), settings.password.encode()
    )


def ldap_authenticate(settings: Settings, username: str, password: str, server_factory=None):
    """Return the user's display name if the credentials are valid, else None.

    Search for the user with the service account (or anonymously when no bind
    DN is configured), then bind as the user's DN with their password.
    """
    import ldap3
    from ldap3.utils.conv import escape_filter_chars

    if not username or not password:
        return None
    make_server = server_factory or (lambda: ldap3.Server(settings.ldap_url, get_info=ldap3.NONE))
    server = make_server()
    filt = settings.ldap_user_filter.replace("{username}", escape_filter_chars(username))
    try:
        svc = ldap3.Connection(
            server,
            user=settings.ldap_bind_dn or None,
            password=settings.ldap_bind_password or None,
            auto_bind=False,
            raise_exceptions=False,
            **_strategy_kwargs(server_factory),
        )
        if settings.ldap_start_tls and server_factory is None:
            svc.open()
            svc.start_tls()
        if not svc.bind():
            log.error("LDAP service bind failed: %s", svc.result)
            raise AuthError("LDAP service bind failed")
        svc.search(
            settings.ldap_base_dn, filt, attributes=["cn", "displayName", "memberOf"], size_limit=2
        )
        entries = list(svc.entries)
        svc.unbind()
    except AuthError:
        raise
    except Exception as e:  # noqa: BLE001
        log.error("LDAP error: %s", e)
        raise AuthError(f"LDAP error: {e}") from e
    if len(entries) != 1:
        return None
    entry = entries[0]
    user_dn = entry.entry_dn
    conn = ldap3.Connection(
        server,
        user=user_dn,
        password=password,
        raise_exceptions=False,
        **_strategy_kwargs(server_factory),
    )
    if settings.ldap_start_tls and server_factory is None:
        conn.open()
        conn.start_tls()
    ok = conn.bind()
    conn.unbind()
    if not ok:
        return None
    member_of = entry["memberOf"].values if "memberOf" in entry else []
    if not allowed(settings, group_names(member_of)):
        log.warning("LDAP user %s signed in but isn't in %s", username, settings.admin_groups)
        raise AuthError(NOT_IN_GROUP)
    for attr in ("displayName", "cn"):
        if attr in entry and entry[attr].value:
            return str(entry[attr].value)
    return username


def _strategy_kwargs(server_factory) -> dict:
    if server_factory is None:
        return {}
    import ldap3

    return {"client_strategy": ldap3.MOCK_SYNC}


def authenticate(settings: Settings, username: str, password: str, server_factory=None):
    """Return the session user name, or None on bad credentials."""
    if settings.ldap_enabled:
        return ldap_authenticate(settings, username.strip(), password, server_factory)
    if check_password(settings, password):
        return username.strip() or "admin"
    return None
