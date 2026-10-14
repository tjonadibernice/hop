"""SimHash: a 64-bit fingerprint where similar texts get similar fingerprints.

Exact duplicates are easy (same URL). Near-duplicates (the same article on two
URLs, or with a different footer) need a fingerprint that changes a little
when the text changes a little. SimHash does that:

1. Split the text into overlapping 3-word phrases ("shingles").
2. Hash each shingle to 64 bits.
3. For each bit position, add 1 if the shingle's bit is set, else subtract 1.
4. The fingerprint has bit i set if position i ended up positive.

The number of differing bits (Hamming distance) between two fingerprints
estimates how different the texts are. We treat 7 bits or fewer as duplicates:
copies that differ only in a heading or footer land around 6, while unrelated
articles land around 32. (Web-scale crawlers use 3, because with billions of
pages even rare false matches add up.)

Finding matches fast: split each fingerprint into 8 bands of 8 bits. If two
fingerprints differ in at most 7 bits, those bits touch at most 7 bands, so at
least one band is identical (pigeonhole principle). The database indexes the
bands, finds pages sharing any band, and only those are compared bit by bit.
"""

import hashlib
import re

BITS = 64
BANDS = 8
BAND_BITS = BITS // BANDS
NEAR_DUPLICATE_DISTANCE = 7  # must be below BANDS (pigeonhole)
SHINGLE_SIZE = 3

_WORD = re.compile(r"\w+")


def _shingles(text: str) -> list[str]:
    words = _WORD.findall(text.lower())
    if len(words) <= SHINGLE_SIZE:
        return [" ".join(words)] if words else []
    return [
        " ".join(words[i : i + SHINGLE_SIZE])
        for i in range(len(words) - SHINGLE_SIZE + 1)
    ]


def simhash(text: str) -> int:
    weights = [0] * BITS
    for shingle in _shingles(text):
        digest = hashlib.blake2b(shingle.encode(), digest_size=BITS // 8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(BITS):
            weights[bit] += 1 if value >> bit & 1 else -1
    return sum(1 << bit for bit in range(BITS) if weights[bit] > 0)


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def band_keys(fingerprint: int) -> list[int]:
    """The 8 bands, each tagged with its position so band 0 never matches band 1."""
    mask = (1 << BAND_BITS) - 1
    return [
        (band << BAND_BITS) | (fingerprint >> (band * BAND_BITS) & mask)
        for band in range(BANDS)
    ]


def to_signed(fingerprint: int) -> int:
    """Postgres BIGINT is signed: map 0..2^64-1 onto -2^63..2^63-1."""
    return fingerprint - (1 << BITS) if fingerprint >= 1 << (BITS - 1) else fingerprint


def from_signed(value: int) -> int:
    return value + (1 << BITS) if value < 0 else value
