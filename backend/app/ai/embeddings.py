"""Text embeddings from Voyage AI.

There's deliberately no fallback provider here: vectors from different
models live in different spaces and can't be compared, so mixing them would
quietly break similarity search. If Voyage is down, the job retries later.
"""

import httpx

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"


class EmbeddingError(Exception):
    def __init__(self, reason: str, *, retryable: bool) -> None:
        super().__init__(reason)
        self.retryable = retryable


class VoyageEmbedder:
    def __init__(
        self, client: httpx.AsyncClient, api_key: str, model: str, dimensions: int
    ) -> None:
        self.client = client
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self.client.post(
                VOYAGE_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "input": texts,
                    # "document" adds Voyage's retrieval prompt for stored items;
                    # search text would use "query"
                    "input_type": "document",
                    "output_dimension": self.dimensions,
                    "truncation": True,
                },
            )
        except httpx.HTTPError as error:
            raise EmbeddingError(type(error).__name__, retryable=True) from error

        if response.status_code == 429 or response.status_code >= 500:
            raise EmbeddingError(f"HTTP {response.status_code}", retryable=True)
        if response.status_code >= 400:
            raise EmbeddingError(f"HTTP {response.status_code}", retryable=False)

        items = sorted(response.json()["data"], key=lambda item: item["index"])
        vectors = [item["embedding"] for item in items]
        if len(vectors) != len(texts) or any(
            len(vector) != self.dimensions for vector in vectors
        ):
            raise EmbeddingError("unexpected embedding shape", retryable=False)
        return vectors
