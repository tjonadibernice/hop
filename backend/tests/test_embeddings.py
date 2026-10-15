import json

import httpx
import pytest

from app.ai.embeddings import EmbeddingError, VoyageEmbedder


def embedder(handler, dimensions: int = 4) -> VoyageEmbedder:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return VoyageEmbedder(client, "v-key", "voyage-4-lite", dimensions)


async def test_returns_vectors_in_input_order():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 0.0, 0.0, 2.0]},
                    {"index": 0, "embedding": [1.0, 0.0, 0.0, 0.0]},
                ]
            },
        )

    vectors = await embedder(handler).embed_documents(["first", "second"])

    assert vectors == [[1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 2.0]]
    body = json.loads(requests[0].content)
    assert body["input_type"] == "document"
    assert body["output_dimension"] == 4
    assert requests[0].headers["authorization"] == "Bearer v-key"


@pytest.mark.parametrize(
    ("status", "retryable"), [(429, True), (503, True), (400, False), (401, False)]
)
async def test_errors_say_whether_to_retry(status, retryable):
    with pytest.raises(EmbeddingError) as caught:
        await embedder(lambda request: httpx.Response(status)).embed_documents(["x"])
    assert caught.value.retryable is retryable


async def test_wrong_dimensions_are_rejected():
    def handler(request):
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})

    with pytest.raises(EmbeddingError, match="shape"):
        await embedder(handler).embed_documents(["x"])
