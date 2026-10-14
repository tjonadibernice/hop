import pytest

from app.ingestion.network import UnsafeUrlError, ensure_public_host, is_public_address


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
    await ensure_public_host("93.184.216.34", 443)
