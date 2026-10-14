"""Decide whether a page allows other sites to show it in an iframe."""

import httpx


def _frame_ancestors(csp_headers: list[str]) -> list[list[str]]:
    """The sources of every frame-ancestors directive in the CSP headers."""
    found = []
    for header in csp_headers:
        # One header can hold several policies separated by commas,
        # and each policy holds directives separated by semicolons
        for policy in header.split(","):
            for directive in policy.split(";"):
                parts = directive.strip().split()
                if parts and parts[0].lower() == "frame-ancestors":
                    found.append([source.lower() for source in parts[1:]])
    return found


def allows_framing(headers: httpx.Headers) -> bool:
    """True if a browser would let any other site show this page in an iframe."""
    directives = _frame_ancestors(headers.get_list("content-security-policy"))
    if directives:
        # Browsers ignore X-Frame-Options when CSP frame-ancestors is present.
        # Every policy must allow us, and only "*" allows an unknown site.
        return all("*" in sources for sources in directives)

    # X-Frame-Options: DENY or SAMEORIGIN (or the obsolete ALLOW-FROM)
    # all block other sites
    return not headers.get("x-frame-options", "").strip()


async def check_embeddable(client: httpx.AsyncClient, url: str) -> bool | None:
    """Fetch the page and check its headers. None if the page couldn't be loaded."""
    try:
        response = await client.get(url)
    except httpx.HTTPError:
        return None
    if response.status_code >= 400:
        return None
    return allows_framing(response.headers)
