import random

from app.ingestion.simhash import (
    BANDS,
    NEAR_DUPLICATE_DISTANCE,
    band_keys,
    from_signed,
    hamming_distance,
    simhash,
    to_signed,
)

ARTICLE = " ".join(
    f"Paragraph {n} explains why retrieval practice beats rereading for exams."
    for n in range(40)
)


def test_same_text_same_fingerprint():
    assert simhash(ARTICLE) == simhash(ARTICLE)


def test_changed_heading_is_still_a_near_duplicate():
    copy = "Mirror copy. " + ARTICLE + " Thanks for reading."
    assert hamming_distance(simhash(ARTICLE), simhash(copy)) <= (
        NEAR_DUPLICATE_DISTANCE
    )


def test_small_edit_changes_few_bits():
    edited = ARTICLE + " Thanks for reading, and share this post with a friend."
    assert hamming_distance(simhash(ARTICLE), simhash(edited)) <= (
        NEAR_DUPLICATE_DISTANCE
    )


def test_unrelated_texts_are_far_apart():
    other = " ".join(
        f"Chapter {n} covers sourdough starters, flour types, and oven spring."
        for n in range(40)
    )
    assert hamming_distance(simhash(ARTICLE), simhash(other)) > 10


def test_close_fingerprints_always_share_a_band():
    # The pigeonhole guarantee the database lookup depends on
    rng = random.Random(42)
    for _ in range(500):
        fingerprint = rng.getrandbits(64)
        changed = fingerprint
        for bit in rng.sample(range(64), NEAR_DUPLICATE_DISTANCE):
            changed ^= 1 << bit
        assert set(band_keys(fingerprint)) & set(band_keys(changed))


def test_threshold_keeps_the_pigeonhole_guarantee():
    assert NEAR_DUPLICATE_DISTANCE < BANDS


def test_band_keys_are_tagged_by_position():
    # The same 8 bits in different positions must not match
    keys = band_keys(0x0101_0101_0101_0101)
    assert keys == [band * 256 + 1 for band in range(8)]
    assert len(set(keys)) == 8


def test_signed_round_trip_fits_bigint():
    for fingerprint in (0, 1, 2**63 - 1, 2**63, 2**64 - 1):
        stored = to_signed(fingerprint)
        assert -(2**63) <= stored < 2**63
        assert from_signed(stored) == fingerprint
