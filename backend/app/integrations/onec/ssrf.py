"""
SSRF Protection Validator for tenant-configured 1C base URLs.
Prevents attackers from specifying internal network endpoints (localhost,
internal container services, cloud metadata, private RFC 1918 subnets).
"""

import ipaddress
import socket
from urllib.parse import urlsplit


class SSRFValidationError(ValueError):
    """Raised when a provided URL targets forbidden internal or private network hosts."""
    pass


FORBIDDEN_HOSTNAMES = {
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
    "postgres",
    "redis",
    "backend",
    "frontend",
    "db",
    "celery",
    "rabbitmq",
    "minio",
    "metadata.google.internal",
    "169.254.169.254",  # AWS/GCP/Azure link-local metadata
}

FORBIDDEN_DOMAINS_SUFFIXES = (
    ".local",
    ".internal",
    ".lan",
    ".corp",
    ".home",
)


def validate_onec_base_url(url: str, allow_private: bool = False) -> str:
    """
    Validates a 1C OData base URL against SSRF attacks.
    Returns the normalized base URL (stripped of trailing slash).
    Raises SSRFValidationError on violation.
    """
    if not url or not isinstance(url, str):
        raise SSRFValidationError("1C base URL must be a non-empty string.")

    cleaned_url = url.strip()
    try:
        parsed = urlsplit(cleaned_url)
    except Exception as exc:
        raise SSRFValidationError(f"Invalid URL format: {exc}")

    if parsed.scheme.lower() not in ("http", "https"):
        raise SSRFValidationError(f"Invalid URL scheme '{parsed.scheme}'. Only http and https are allowed.")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFValidationError("URL must include a valid hostname.")

    hostname_lower = hostname.lower()

    if allow_private:
        return cleaned_url.rstrip("/")

    # 1. Denylisted hostnames check
    if hostname_lower in FORBIDDEN_HOSTNAMES:
        raise SSRFValidationError(f"Access to internal host '{hostname}' is strictly forbidden.")

    for suffix in FORBIDDEN_DOMAINS_SUFFIXES:
        if hostname_lower.endswith(suffix):
            raise SSRFValidationError(f"Access to private domain '{hostname}' is forbidden.")

    # 2. Check if hostname is directly an IP literal
    try:
        ip = ipaddress.ip_address(hostname_lower)
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise SSRFValidationError(f"Access to private/internal IP address '{ip}' is strictly forbidden.")
        return cleaned_url.rstrip("/")
    except ValueError:
        # Not a direct IP literal, proceed to DNS resolution check
        pass

    # 3. DNS resolution safety check: verify resolved IP addresses
    try:
        addr_infos = socket.getaddrinfo(hostname_lower, None)
        for addr_info in addr_infos:
            ip_str = addr_info[4][0]
            ip = ipaddress.ip_address(ip_str)
            if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                raise SSRFValidationError(
                    f"Host '{hostname}' resolves to private/internal IP address '{ip_str}' which is forbidden."
                )
    except socket.gaierror:
        # If host cannot be resolved at validation time (e.g. mock host in isolated test environment),
        # but did not match known private names/patterns, allow format if it looks like a public domain
        if "." not in hostname_lower:
            raise SSRFValidationError(f"Invalid hostname '{hostname}'. Must be a fully qualified domain name.")

    return cleaned_url.rstrip("/")
