import hashlib
import math
import re

from tests.pipeline.samples import FAQ
from triage.domain import Language
from triage.journal.store import Journal
from triage.knowledge.faq import parse_faq
from triage.retrieval import DIMENSIONS, FaqIndex

_WORD = re.compile(r"\w{3,}")


class WordHashEmbedder:
    name = "word-hash-test"

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * DIMENSIONS
        for word in _WORD.findall(text.casefold()):
            vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % DIMENSIONS] += 1.0
        vector[0] += 0.01
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector]


async def test_the_index_embeds_each_entry_once_and_again_only_when_it_changes(
    journal: Journal,
) -> None:
    index = FaqIndex(journal.pool, WordHashEmbedder(), FAQ)
    assert await index.sync() == 12
    assert await index.sync() == 0
    changed_text = FAQ["F01"].text.replace("60 minutes", "30 minutes")
    changed = parse_faq(
        "\n".join(
            f"## {entry.id} · {entry.title}\n{changed_text if entry.id == 'F01' else entry.text}\n"
            for entry in FAQ.entries
        )
    )
    assert await FaqIndex(journal.pool, WordHashEmbedder(), changed).sync() == 1


async def test_hybrid_search_finds_the_entry_a_dutch_ticket_is_about(journal: Journal) -> None:
    index = FaqIndex(journal.pool, WordHashEmbedder(), FAQ)
    await index.sync()
    top = await index.search("Wachtwoord kwijt, hoe kom ik weer in mijn account?", Language.DUTCH)
    assert top[0] == "F01"
    assert len(top) <= 3


async def test_hybrid_search_works_in_english_and_german(journal: Journal) -> None:
    index = FaqIndex(journal.pool, WordHashEmbedder(), FAQ)
    await index.sync()
    assert "F12" in await index.search("Which iOS and Android versions work?", Language.ENGLISH)
    assert await index.search("Hallo", Language.GERMAN) is not None
