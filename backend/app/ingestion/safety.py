"""Safety screen: a domain blocklist plus Google Safe Browsing."""

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

SAFE_BROWSING_URL = "https://safebrowsing.googleapis.com/v5/urls:search"
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

        try:
            # The key goes in a header, not the URL: URLs end up in logs
            response = await self.client.get(
                SAFE_BROWSING_URL,
                params={"urls": url},
                headers={"X-Goog-Api-Key": self.api_key},
            )
        except httpx.HTTPError as error:
            raise SafetyCheckError(type(error).__name__) from error
        if response.status_code >= 400:
            raise SafetyCheckError(f"HTTP {response.status_code}")

        threat_types = sorted(
            {
                kind
                for threat in response.json().get("threats", [])
                for kind in threat.get("threatTypes", [])
            }
        )
        if threat_types:
            return SafetyResult(
                safe=False,
                checked=True,
                reason=f"Safe Browsing: {', '.join(threat_types)}",
            )
        return SafetyResult(safe=True, checked=True)
