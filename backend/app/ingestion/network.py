"""Protection against server-side request forgery (SSRF).

The crawler fetches URLs that come from outside. Without a check, a URL like
http://169.254.169.254/ (the cloud metadata service) or http://localhost:6379/
would make our server send requests into our own private network.

DNS rebinding: if the check resolved the host and the HTTP client resolved
it again to connect, a hostile DNS server could answer with a public address
the first time and a private one the second. So ensure_public_host() returns
the address it checked, and SafeFetcher connects to exactly that address
(see fetch.py). The host is resolved once per request, and that answer is
both checked and used.
"""

import asyncio
import ipaddress
import socket


class UnsafeUrlError(Exception):
    """The URL points to an address inside a private network."""


class HostNotFoundError(Exception):
    """The host name doesn't resolve to any address."""


def is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])  # drop an IPv6 zone id
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 is really 127.0.0.1
    # is_global is False for private, loopback, link-local (incl. cloud
    # metadata), shared, and reserved ranges
    return ip.is_global and not ip.is_multicast


async def ensure_public_host(host: str, port: int) -> str:
    """The address to connect to, after checking that every address the host
    resolves to is public. Raises UnsafeUrlError otherwise."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )
    except socket.gaierror as error:
        raise HostNotFoundError(host) from error

    addresses = [sockaddr[0] for *_, sockaddr in infos]
    if not addresses:
        raise HostNotFoundError(host)
    for address in addresses:
        if not is_public_address(address):
            raise UnsafeUrlError(f"{host} resolves to a non-public address")
    # Every answer is public; connect to the first, as the OS would
    return addresses[0].split("%", 1)[0]
