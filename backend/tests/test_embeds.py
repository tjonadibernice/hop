import httpx

from app.services.embeds import allows_framing, check_embeddable


def headers(*pairs: tuple[str, str]) -> httpx.Headers:
    return httpx.Headers(list(pairs))


def test_no_framing_headers_allows_framing():
    assert allows_framing(headers()) is True


def test_x_frame_options_blocks_framing():
    assert allows_framing(headers(("X-Frame-Options", "DENY"))) is False
    assert allows_framing(headers(("X-Frame-Options", "sameorigin"))) is False


def test_csp_frame_ancestors_none_blocks_framing():
    csp = "default-src 'self'; frame-ancestors 'none'"
    assert allows_framing(headers(("Content-Security-Policy", csp))) is False


def test_csp_frame_ancestors_specific_sites_blocks_us():
    csp = "frame-ancestors 'self' https://partner.example"
    assert allows_framing(headers(("Content-Security-Policy", csp))) is False


def test_csp_frame_ancestors_star_allows_framing():
    csp = "frame-ancestors *"
    assert allows_framing(headers(("Content-Security-Policy", csp))) is True


def test_csp_wins_over_x_frame_options():
    # Browsers ignore X-Frame-Options when frame-ancestors is present
    assert (
        allows_framing(
            headers(
                ("Content-Security-Policy", "frame-ancestors *"),
                ("X-Frame-Options", "DENY"),
            )
        )
        is True
    )


def test_every_csp_policy_must_allow_framing():
    assert (
        allows_framing(
            headers(
                ("Content-Security-Policy", "frame-ancestors *"),
                ("Content-Security-Policy", "frame-ancestors 'self'"),
            )
        )
        is False
    )


def test_csp_without_frame_ancestors_falls_back_to_x_frame_options():
    assert (
        allows_framing(
            headers(
                ("Content-Security-Policy", "default-src 'self'"),
                ("X-Frame-Options", "DENY"),
            )
        )
        is False
    )


def test_report_only_csp_is_ignored():
    csp = "frame-ancestors 'none'"
    assert allows_framing(headers(("Content-Security-Policy-Report-Only", csp))) is True


def fake_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_check_embeddable_reads_response_headers():
    def handler(request):
        return httpx.Response(200, headers={"X-Frame-Options": "DENY"})

    async with fake_client(handler) as client:
        assert await check_embeddable(client, "https://example.com") is False


async def test_check_embeddable_unknown_when_page_fails():
    def server_error(request):
        return httpx.Response(500)

    def unreachable(request):
        raise httpx.ConnectError("no route to host")

    async with fake_client(server_error) as client:
        assert await check_embeddable(client, "https://example.com") is None
    async with fake_client(unreachable) as client:
        assert await check_embeddable(client, "https://example.com") is None
