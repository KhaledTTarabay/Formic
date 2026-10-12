import os
import asyncio
from sentence_transformers import SentenceTransformer

EMBEDDINGS_MODEL = os.environ.get("EMBEDDINGS_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

_model: SentenceTransformer | None = None

def load() -> None:
    global _model
    _model = SentenceTransformer(EMBEDDINGS_MODEL)

async def embed(texts: list[str]) -> list[list[float]]:
    if _model is None:
        raise RuntimeError("Embeddings model is not loaded.")
    vectors = await asyncio.to_thread(_model.encode, texts, normalize_embeddings=True)
    return vectors.tolist()