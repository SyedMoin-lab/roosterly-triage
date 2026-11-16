import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_FAQ_PATH = Path("data/faq.md")

_HEADING = re.compile(r"^## (F\d{2}) · (.+)$")
_BRACKETED = re.compile(r"\s*\([^)]*\)")
_LABEL = r"[A-Z][a-z]+(?: [a-z]+)*"
_CHAIN = re.compile(rf"{_LABEL}(?: → {_LABEL})+")
_CHAIN_WITH_MEANING = re.compile(rf"({_LABEL}(?: → {_LABEL})+) \(([^)]*)\)")
_QUOTED = re.compile(r'"([^"]+)"')
_LABEL_BEFORE_MEANING = re.compile(rf"({_LABEL}) \([A-Z][^)]*\)")
_URL = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:nl|com|eu)(?:/[\w/-]*)?", re.IGNORECASE)
_NUMBER = re.compile(r"\d+")


@dataclass(frozen=True, slots=True)
class FaqEntry:
    id: str
    title: str
    text: str
    menu_paths: tuple[tuple[str, ...], ...]
    translated_menu_paths: tuple[tuple[str, ...], ...]
    labels: frozenset[str]
    urls: frozenset[str]
    numbers: frozenset[str]

    @classmethod
    def parse(cls, entry_id: str, title: str, text: str) -> "FaqEntry":
        dutch_only = _BRACKETED.sub("", text)
        paths = tuple(tuple(chain.split(" → ")) for chain in _CHAIN.findall(dutch_only))
        labels = {item for path in paths for item in path}
        labels.update(_QUOTED.findall(text))
        labels.update(_LABEL_BEFORE_MEANING.findall(text))
        urls = frozenset(url.lower() for url in _URL.findall(text))
        numbers = frozenset(_NUMBER.findall(_URL.sub(" ", text)))
        return cls(
            entry_id, title, text, paths, _translated_paths(text), frozenset(labels), urls, numbers
        )

    @property
    def all_menu_paths(self) -> tuple[tuple[str, ...], ...]:
        return self.menu_paths + self.translated_menu_paths


@dataclass(frozen=True, slots=True)
class Faq:
    entries: tuple[FaqEntry, ...]
    rules: tuple[str, ...]
    sha256: str

    def __getitem__(self, entry_id: str) -> FaqEntry:
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        raise KeyError(entry_id)

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(entry.id for entry in self.entries)

    @property
    def labels(self) -> frozenset[str]:
        return frozenset(label for entry in self.entries for label in entry.labels)


def parse_faq(markdown: str) -> Faq:
    text = markdown.replace("\r\n", "\n")
    help_centre, _, rules_part = text.partition("\n---\n")
    entries: list[FaqEntry] = []
    current: tuple[str, str] | None = None
    body: list[str] = []
    for line in help_centre.splitlines():
        heading = _HEADING.match(line)
        if heading or line.startswith("## "):
            if current is not None:
                entries.append(FaqEntry.parse(*current, " ".join(body).strip()))
            current = (heading.group(1), heading.group(2).strip()) if heading else None
            body = []
        elif current is not None and line.strip():
            body.append(line.strip())
    if current is not None:
        entries.append(FaqEntry.parse(*current, " ".join(body).strip()))
    return Faq(tuple(entries), _parse_rules(rules_part), hashlib.sha256(text.encode()).hexdigest())


def load_faq(path: Path = DEFAULT_FAQ_PATH) -> Faq:
    return parse_faq(path.read_text(encoding="utf-8"))


def _translated_paths(text: str) -> tuple[tuple[str, ...], ...]:
    translated = []
    for dutch, meaning in _CHAIN_WITH_MEANING.findall(text):
        items = dutch.split(" → ")
        if " → " in meaning:
            translated.append(tuple(meaning.split(" → ")))
        else:
            translated.append((*items[:-1], meaning))
    return tuple(translated)


def _parse_rules(text: str) -> tuple[str, ...]:
    rules: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            rules.append(stripped[2:])
        elif stripped and rules and not stripped.startswith("#"):
            rules[-1] = f"{rules[-1]} {stripped}"
    return tuple(rules)
