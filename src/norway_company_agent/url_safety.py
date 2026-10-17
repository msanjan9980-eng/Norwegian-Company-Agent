"""SSRF and redirect safety for outbound HTTP fetches.

Implements the safety policy documented in LIMITATIONS.md.
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse


_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _ip_is_private(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        return True
    for net in _PRIVATE_NETWORKS:
        if ip in net:
            return True
    return False


def is_safe_url(url: str) -> tuple[bool, str]:
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, "unparseable URL: " + str(e)
    if parsed.scheme not in ("http", "https"):
        return False, "scheme not allowed: " + str(parsed.scheme)
    host = parsed.hostname
    if not host:
        return False, "missing hostname"
    try:
        addr_info = socket.getaddrinfo(host, None)
    except Exception as e:
        return False, "DNS resolution failed: " + str(e)
    for family, _, _, _, sockaddr in addr_info:
        ip_str = sockaddr[0]
        if _ip_is_private(ip_str):
            return False, "resolves to private IP: " + ip_str
    return True, ""


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe, reason = is_safe_url(newurl)
        if not safe:
            raise urllib.error.URLError("redirect blocked: " + reason)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_urlopen(req, timeout=None, context=None):
    """Drop-in replacement for urllib.request.urlopen that enforces SSRF safety."""
    url = req.full_url if hasattr(req, "full_url") else str(req)
    safe, reason = is_safe_url(url)
    if not safe:
        raise urllib.error.URLError("blocked: " + reason)
    handlers = [_SafeRedirectHandler()]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    return opener.open(req, timeout=timeout)
