"""Normalize URLs so the same page always gets the same key."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULT_PORTS = {"http": 80, "https": 443}

# Query parameters that only track where a click came from
TRACKING_PARAMS = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid"}
TRACKING_PREFIXES = ("utm_",)


class InvalidUrlError(ValueError):
    pass


def _is_tracking(name: str) -> bool:
    name = name.lower()
    return name in TRACKING_PARAMS or name.startswith(TRACKING_PREFIXES)


def canonicalize_url(url: str) -> str:
    """Return the URL in one standard form.

    Lowercases the scheme and host, drops the default port, the #fragment, and
    tracking parameters, and sorts the remaining query parameters. Two URLs
    that differ only in those ways point to the same page.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS:
        raise InvalidUrlError(f"Only http and https URLs are supported: {url!r}")
    if parts.username or parts.password:
        raise InvalidUrlError(
            f"URLs with a username or password aren't allowed: {url!r}"
        )

    host = parts.hostname  # already lowercase, without brackets or credentials
    if not host:
        raise InvalidUrlError(f"URL has no host: {url!r}")
    try:
        port = parts.port
        host = host.encode("idna").decode("ascii")  # unicode domains -> xn--...
    except (ValueError, UnicodeError) as error:
        raise InvalidUrlError(f"Invalid URL: {url!r}") from error

    netloc = f"[{host}]" if ":" in host else host  # IPv6 needs brackets back
    if port is not None and port != DEFAULT_PORTS[scheme]:
        netloc += f":{port}"

    query = urlencode(
        sorted(
            (name, value)
            for name, value in parse_qsl(parts.query, keep_blank_values=True)
            if not _is_tracking(name)
        )
    )
    return urlunsplit((scheme, netloc, parts.path or "/", query, ""))
