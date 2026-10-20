import asyncio
import socket

import pytest

from app.ingestion.network import (
    HostNotFoundError,
    UnsafeUrlError,
    ensure_public_host,
    is_public_address,
)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # private
        "172.16.0.1",  # private
        "192.168.1.10",  # private
        "169.254.169.254",  # link-local: cloud metadata service
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",
        "224.0.0.1",  # multicast
        "::1",
        "fe80::1%eth0",
        "fc00::1",
        "::ffff:127.0.0.1",  # IPv4 loopback hidden in IPv6
    ],
)
def test_private_addresses_are_not_public(address):
    assert not is_public_address(address)


@pytest.mark.parametrize("address", ["93.184.216.34", "2606:4700:4700::1111"])
def test_public_addresses(address):
    assert is_public_address(address)


async def test_ensure_public_host_blocks_ip_literals():
    # IP literals resolve locally, so this needs no network
    with pytest.raises(UnsafeUrlError):
        await ensure_public_host("127.0.0.1", 80)
    with pytest.raises(UnsafeUrlError):
        await ensure_public_host("169.254.169.254", 80)
    assert await ensure_public_host("93.184.216.34", 443) == "93.184.216.34"


class FakeDns:
    """Answers each lookup with the next list of addresses."""

    def __init__(self, *answers: list[str]) -> None:
        self.answers = list(answers)
        self.lookups = 0

    async def getaddrinfo(self, host, port, **_):
        self.lookups += 1
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
            for address in self.answers.pop(0)
        ]


@pytest.fixture
def dns(monkeypatch):
    def install(*answers):
        fake = FakeDns(*answers)
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", fake.getaddrinfo)
        return fake

    return install


async def test_the_checked_address_is_returned(dns):
    dns(["93.184.216.34", "93.184.216.35"])

    assert await ensure_public_host("example.org", 443) == "93.184.216.34"


async def test_one_private_answer_is_enough_to_refuse(dns):
    dns(["93.184.216.34", "10.0.0.5"])

    with pytest.raises(UnsafeUrlError):
        await ensure_public_host("rebind.test", 80)


async def test_no_answer_means_no_host(dns):
    dns([])

    with pytest.raises(HostNotFoundError):
        await ensure_public_host("empty.test", 80)
