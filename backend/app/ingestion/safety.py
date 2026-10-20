"""Safety screen: a domain blocklist plus Google Safe Browsing."""

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

# The v4 Lookup API speaks JSON. (v5's urls:search only answers in protobuf.)
SAFE_BROWSING_URL = "https://safebrowsing.googleapis.com/v4/threatMatches:find"
THREAT_TYPES = [
    "MALWARE",
    "SOCIAL_ENGINEERING",
    "UNWANTED_SOFTWARE",
    "POTENTIALLY_HARMFUL_APPLICATION",
]
BLOCKLIST_FILE = Path(__file__).with_name("blocked_domains.txt")


@dataclass(frozen=True)
class SafetyResult:
    safe: bool
    checked: bool  # False when Safe Browsing isn't configured
    reason: str | None = None


class SafetyCheckError(Exception):
    """Safe Browsing couldn't be reached. Worth retrying later."""


def load_blocklist(path: Path = BLOCKLIST_FILE) -> frozenset[str]:
    lines = (line.strip().lower() for line in path.read_text().splitlines())
    return frozenset(line for line in lines if line and not line.startswith("#"))


EXCLUDED_SITES_FILE = Path(__file__).with_name("excluded_sites.txt")


def is_excluded(url: str, excluded: frozenset[str] | None = None) -> bool:
    """True for a page on a site Hop never collects (excluded_sites.txt).

    Unlike the blocklist, these sites aren't unsafe; they're just not what
    Hop is for, so their pages are never stored at all.
    """
    host = urlsplit(url).hostname
    if host is None:
        return False
    return is_blocked(host, EXCLUDED_SITES if excluded is None else excluded)


def is_blocked(host: str, blocklist: frozenset[str]) -> bool:
    """True for a listed domain and all its subdomains (a.bad.example -> bad.example)."""
    parts = host.lower().rstrip(".").split(".")
    return any(".".join(parts[i:]) in blocklist for i in range(len(parts)))


class SafetyChecker:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str | None,
        blocklist: frozenset[str],
    ) -> None:
        self.client = client
        self.api_key = api_key
        self.blocklist = blocklist

    async def check(self, url: str) -> SafetyResult:
        host = urlsplit(url).hostname or ""
        if is_blocked(host, self.blocklist):
            return SafetyResult(safe=False, checked=True, reason="blocked domain")
        if not self.api_key:
            return SafetyResult(safe=True, checked=False)

        body = {
            "client": {"clientId": "hop", "clientVersion": "0.1"},
            "threatInfo": {
                "threatTypes": THREAT_TYPES,
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": url}],
            },
        }
        try:
            # The key goes in a header, not the URL: URLs end up in logs
            response = await self.client.post(
                SAFE_BROWSING_URL,
                json=body,
                headers={"X-Goog-Api-Key": self.api_key},
            )
        except httpx.HTTPError as error:
            raise SafetyCheckError(type(error).__name__) from error
        if response.status_code >= 400:
            raise SafetyCheckError(f"HTTP {response.status_code}")
        try:
            # No matches comes back as an empty object: {}
            matches = response.json().get("matches", [])
        except (ValueError, AttributeError) as error:
            raise SafetyCheckError("unreadable answer") from error

        threat_types = sorted({match.get("threatType", "UNKNOWN") for match in matches})
        if threat_types:
            return SafetyResult(
                safe=False,
                checked=True,
                reason=f"Safe Browsing: {', '.join(threat_types)}",
            )
        return SafetyResult(safe=True, checked=True)


EXCLUDED_SITES = load_blocklist(EXCLUDED_SITES_FILE)
