"""SSRF protection: validate URLs before fetching.

Blocks requests to private/reserved IP ranges, cloud metadata endpoints,
and internal Docker service hostnames.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Internal Docker service hostnames that should never be accessed via user input
_BLOCKED_HOSTNAMES = frozenset({
    "postgres",
    "minio",
    "valkey",
    "nats",
    "litellm",
    "qdrant",
    "backend",
    "notifications",
    "grafana",
    "prometheus",
    "loki",
    "localhost",
    "metadata.google.internal",
})

# Cloud metadata IP
_METADATA_IPS = frozenset({
    "169.254.169.254",
})


def validate_url(url: str) -> str:
    """Validate that a URL does not point to internal/private resources.

    Raises ValueError if the URL targets a blocked destination.
    Returns the original URL if valid.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname

    if not hostname:
        raise ValueError(f"Invalid URL (no hostname): {url}")

    # Block known internal hostnames
    hostname_lower = hostname.lower()
    if hostname_lower in _BLOCKED_HOSTNAMES:
        raise ValueError(f"Blocked internal hostname: {hostname}")

    # Resolve hostname to IP and check
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        # Cannot resolve — allow the request to fail naturally downstream
        return url

    for family, _, _, _, sockaddr in addr_infos:
        ip_str = sockaddr[0]

        if ip_str in _METADATA_IPS:
            raise ValueError(f"Blocked metadata endpoint: {ip_str}")

        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        if ip.is_private or ip.is_reserved or ip.is_loopback or ip.is_link_local:
            raise ValueError(
                f"Blocked private/reserved IP {ip_str} for hostname {hostname}"
            )

    return url
