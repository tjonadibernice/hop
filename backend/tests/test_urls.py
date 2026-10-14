import pytest

from app.ingestion.urls import InvalidUrlError, canonicalize_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("HTTPS://Example.COM/Path", "https://example.com/Path"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("http://example.com:8080/a", "http://example.com:8080/a"),
        ("https://example.com/a#section-2", "https://example.com/a"),
        ("https://example.com/a?b=2&a=1", "https://example.com/a?a=1&b=2"),
        (
            "https://example.com/a?utm_source=x&id=7&fbclid=abc",
            "https://example.com/a?id=7",
        ),
        ("  https://example.com/a  ", "https://example.com/a"),
        ("https://bücher.example/", "https://xn--bcher-kva.example/"),
        ("http://[::1]:8000/", "http://[::1]:8000/"),
    ],
)
def test_canonicalize_url(url, expected):
    assert canonicalize_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://user:secret@example.com/",
        "https:///no-host",
        "https://example.com:99999/",
    ],
)
def test_canonicalize_rejects_bad_urls(url):
    with pytest.raises(InvalidUrlError):
        canonicalize_url(url)
