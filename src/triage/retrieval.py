import hashlib
import re
from collections.abc import Sequence
from typing import Protocol

from langchain_openai import OpenAIEmbeddings

from triage.config import ModelSettings
from triage.domain import Language
from triage.journal.database import Pool
from triage.knowledge.faq import Faq, FaqEntry
from triage.llm.roster import BASE_URLS, Provider

EMBEDDING_MODEL = "gemini-embedding-2"
DIMENSIONS = 768
TOP_ENTRIES = 3
MAX_QUERY_WORDS = 40
_TEXT_SEARCH = {Language.DUTCH: "dutch", Language.ENGLISH: "english", Language.GERMAN: "german"}
_WORD = re.compile(r"\w{3,}")
_HYBRID_SEARCH = """
WITH semantic AS (
    SELECT faq_id, rank() OVER (ORDER BY embedding <=> $1::vector) AS position
    FROM faq_vectors
    WHERE model = $2
),
keyword AS (
    SELECT faq_id,
           rank() OVER (ORDER BY ts_rank_cd(to_tsvector($3::regconfig, content), query) DESC)
               AS position
    FROM faq_vectors, to_tsquery($3::regconfig, $4) AS query
    WHERE model = $2 AND to_tsvector($3::regconfig, content) @@ query
)
SELECT faq_id
FROM (SELECT * FROM semantic UNION ALL SELECT * FROM keyword) AS ranked
GROUP BY faq_id
ORDER BY sum(1.0 / (60 + position)) DESC, faq_id
LIMIT $5
"""
_UPSERT = """
INSERT INTO faq_vectors (faq_id, model, content_sha, content, embedding)
VALUES ($1, $2, $3, $4, $5::vector)
ON CONFLICT (faq_id, model) DO UPDATE
SET content_sha = excluded.content_sha, content = excluded.content,
    embedding = excluded.embedding, updated_at = now()
"""


class Embedder(Protocol):
    name: str

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class GeminiEmbedder:
    name = EMBEDDING_MODEL

    def __init__(self, settings: ModelSettings) -> None:
        self._client = OpenAIEmbeddings(
            openai_api_base=BASE_URLS[Provider.GEMINI],
            openai_api_key=settings.gemini_api_key,
            model=EMBEDDING_MODEL,
            dimensions=DIMENSIONS,
            check_embedding_ctx_length=False,
        )

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._client.aembed_documents([f"title: none | text: {t}" for t in texts])

    async def embed_query(self, text: str) -> list[float]:
        return await self._client.aembed_query(f"task: search result | query: {text}")


class FaqIndex:
    def __init__(self, pool: Pool, embedder: Embedder, faq: Faq) -> None:
        self._pool = pool
        self._embedder = embedder
        self._faq = faq

    async def sync(self) -> int:
        rows = await self._pool.fetch(
            "SELECT faq_id, content_sha FROM faq_vectors WHERE model = $1", self._embedder.name
        )
        known = {row["faq_id"]: row["content_sha"] for row in rows}
        stale = [entry for entry in self._faq.entries if known.get(entry.id) != _sha(entry)]
        if stale:
            vectors = await self._embedder.embed_documents([_document(entry) for entry in stale])
            await self._pool.executemany(
                _UPSERT,
                [
                    (entry.id, self._embedder.name, _sha(entry), _document(entry), _literal(v))
                    for entry, v in zip(stale, vectors, strict=True)
                ],
            )
        return len(stale)

    async def search(self, text: str, language: Language) -> list[str]:
        vector = await self._embedder.embed_query(text)
        words = list(dict.fromkeys(word.casefold() for word in _WORD.findall(text)))
        rows = await self._pool.fetch(
            _HYBRID_SEARCH,
            _literal(vector),
            self._embedder.name,
            _TEXT_SEARCH[language],
            " | ".join(words[:MAX_QUERY_WORDS]),
            TOP_ENTRIES,
        )
        return [row["faq_id"] for row in rows]


def _document(entry: FaqEntry) -> str:
    return f"{entry.title}: {entry.text}"


def _sha(entry: FaqEntry) -> str:
    return hashlib.sha256(_document(entry).encode()).hexdigest()


def _literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.7f}" for value in vector) + "]"
