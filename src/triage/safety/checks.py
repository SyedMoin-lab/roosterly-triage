import re
from collections.abc import Sequence
from dataclasses import dataclass

from triage.domain import Language
from triage.knowledge.faq import Faq, FaqEntry
from triage.language import detect_language
from triage.safety.redaction import digit_runs, redact
from triage.safety.text import fold

MIN_DRAFT_CHARS = 20
MAX_DRAFT_CHARS = 1500

_URL = re.compile(
    r"(?:https?://)?(?:[\w-]+\.)+(?:nl|com|eu|de|io|org|net|app)\b(?:/[^\s)\]]*)?", re.IGNORECASE
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\([^)]*\)")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_ARROW = (
    r"\s*(?:\N{RIGHTWARDS ARROW}|->|=>|\N{RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK}"
    r"|\N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK})\s*"
)
_MENU_ITEM = r"[A-ZÀ-Ý][\w-]*(?: [a-zà-ÿ][\w-]*)*"
_MENU_CHAIN = re.compile(rf"{_MENU_ITEM}(?:{_ARROW}{_MENU_ITEM})+")
_QUOTED = re.compile(r"[\"“”„«»]([^\"“”„«»]{2,60})[\"“”„«»]")
_FAQ_ID = re.compile(r"\bF\d{2}\b")
_HTML_TAG = re.compile(r"<[a-zA-Z/!][^>]*>")
_ROLE_TAG = re.compile(r"\b(?:system|assistant|user)\s*:", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"\[(?:IBAN|CARD|BSN)\]")
_SELF_REFERENCE = re.compile(
    r"\b(?:system\s*prompt|systeemprompt|taalmodel|language\s+model|sprachmodell|"
    r"als\s+ai|as\s+an\s+ai|als\s+ki|ai-assistent)\b"
)
_PROMISE = re.compile(
    "|".join(
        (
            r"\b(?:gratis|kosteloos|korting|compensatie|vergoeding|restitutie|creditnota)\b",
            r"\bterug(?:betal|stort)\w*|\bgeld\s+terug\b|\bcrediteren\b",
            r"\b(?:we|wij|ik)\s+(?:hebben|heb)\b(?:\s+\S+){0,5}?\s+(?:aangepast|teruggestort|"
            r"terugbetaald|verwijderd|opgelost|gewijzigd|geannuleerd|verlengd|gecrediteerd)\b",
            r"\b(?:we|wij|ik)\s+(?:zullen|zal|gaan|ga|zorgen|regelen|nemen\s+contact)\b",
            r"\b(?:is|zijn|wordt|worden)\s+(?:nu\s+)?(?:opgelost|verholpen|teruggestort|terugbetaald)\b",
            r"\b(?:binnenkort|vandaag\s+nog|morgen|volgende\s+week|komende\s+(?:week|maand|release))\b",
            r"\b(?:in|voor|vanaf|eind|begin)\s+(?:januari|februari|maart|april|mei|juni|juli|"
            r"augustus|september|oktober|november|december|q[1-4]|20\d\d)\b",
            r"\bfor\s+free\b|\bfree\s+of\s+charge\b|\bat\s+no\s+(?:extra\s+)?cost\b",
            r"\b(?:discount|refund\w*|compensation|reimburse\w*)\b",
            r"\bwe\s+(?:have|'ve)\b(?:\s+\S+){0,4}?\s+(?:fixed|refunded|changed|deleted|"
            r"cancell?ed|credited|extended)\b",
            r"\b(?:we|i)\s*(?:will|'ll|shall)\b|\bwithin\s+\d+\s+(?:hours|days)\b",
            r"\b(?:soon|next\s+(?:week|month|release|update)|by\s+tomorrow)\b",
            r"\b(?:kostenlos|rabatt|erstattung|gutschrift|entschadigung)\b",
            r"\bwir\s+haben\b(?:\s+\S+){0,4}?\s+(?:erstattet|behoben|geandert|geloscht|"
            r"gekundigt|gutgeschrieben)\b|\bwir\s+werden\b",
            r"\b(?:bald|morgen|nachste\s+woche|innerhalb\s+von\s+\d+)\b",
        )
    )
)
_GREETING_NAME = re.compile(
    r"^\s*(?i:hoi|hallo|hi|hey|beste|geachte|dear|hello|liebe|lieber|sehr\s+geehrte[rs]?|"
    r"guten\s+tag)\s+(?:(?i:heer|mevrouw|herr|frau|mr\.?|ms\.?)\s+)?([A-ZÀ-Ý][\w'-]+)"
)
_GENERIC_ADDRESSEES = frozenset(
    {"klant", "heer", "mevrouw", "customer", "team", "kunde", "kundin", "allemaal", "all"}
)
_DUTCH_FORMAL = re.compile(r"\b(?:u|uw|uzelf)\b")
_DUTCH_INFORMAL = re.compile(r"\b(?:je|jij|jou|jouw|jezelf)\b")
_GERMAN_FORMAL = re.compile(r"\b(?:Sie|Ihnen|Ihr|Ihre|Ihren|Ihrem|Ihrer)\b")
_GERMAN_INFORMAL = re.compile(r"\b(?:du|dich|dir|dein|deine|deinen|deinem|deiner)\b")


@dataclass(frozen=True, slots=True)
class CheckFailure:
    code: str
    detail: str


# Sentences end at . ! ? followed by space, or at a line break; URLs keep their dots.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")
MIN_SENTENCE_WORDS = 5


def check_draft(
    draft: str,
    *,
    faq: Faq,
    cited_ids: Sequence[str],
    evidence: Sequence[str],
    covers_every_question: bool,
    language: Language,
    ticket_text: str,
) -> list[CheckFailure]:
    cited = [faq[entry_id] for entry_id in cited_ids if entry_id in faq.ids]
    failures = _check_schema(draft, faq, cited_ids, covers_every_question)
    failures += _check_quotes(evidence, cited)
    failures += _check_links(draft, cited)
    failures += _check_numbers(draft, cited)
    failures += _check_menu_paths(draft, cited)
    failures += _check_promises(draft)
    failures += _check_personal_data(draft, ticket_text)
    failures += _check_leakage(draft)
    failures += _check_language(draft, language, faq, ticket_text)
    return failures


def _check_schema(
    draft: str, faq: Faq, cited_ids: Sequence[str], covers_every_question: bool
) -> list[CheckFailure]:
    failures = []
    if not cited_ids:
        failures.append(CheckFailure("G1", "the reply cites no FAQ entry"))
    unknown = sorted(set(cited_ids) - faq.ids)
    if unknown:
        failures.append(CheckFailure("G1", f"unknown FAQ entries cited: {', '.join(unknown)}"))
    if not covers_every_question:
        failures.append(CheckFailure("G1", "not every question in the ticket is covered"))
    if not MIN_DRAFT_CHARS <= len(draft.strip()) <= MAX_DRAFT_CHARS:
        failures.append(CheckFailure("G1", f"draft length {len(draft.strip())} is out of range"))
    return failures


def _check_quotes(evidence: Sequence[str], cited: Sequence[FaqEntry]) -> list[CheckFailure]:
    sources = [_normalise(entry.text) for entry in cited]
    return [
        CheckFailure("G2", f"evidence is not in the cited FAQ text: {quote[:60]!r}")
        for quote in evidence
        if not any(_normalise(quote) in source for source in sources)
    ]


def _check_links(draft: str, cited: Sequence[FaqEntry]) -> list[CheckFailure]:
    failures = []
    if _MARKDOWN_LINK.search(draft):
        failures.append(CheckFailure("G3", "markdown link or image"))
    if _EMAIL.search(draft):
        failures.append(CheckFailure("G3", "email address"))
    allowed = {url for entry in cited for url in entry.urls}
    without_emails = _EMAIL.sub(" ", draft)
    for url in _URL.findall(without_emails):
        bare = url.lower().removeprefix("https://").removeprefix("http://").rstrip("/.,")
        if bare not in allowed:
            failures.append(CheckFailure("G3", f"URL not in the cited FAQ entries: {bare}"))
    return failures


def _check_numbers(draft: str, cited: Sequence[FaqEntry]) -> list[CheckFailure]:
    allowed = {number for entry in cited for number in entry.numbers}
    text = _URL.sub(" ", draft)
    return [
        CheckFailure("G4", f"number not in the cited FAQ entries: {number}")
        for number in _NUMBER.findall(text)
        if _canonical_number(number) not in allowed
    ]


def _check_menu_paths(draft: str, cited: Sequence[FaqEntry]) -> list[CheckFailure]:
    known_paths = [path for entry in cited for path in entry.all_menu_paths]
    known_labels = {label.casefold() for entry in cited for label in entry.labels}
    unknown_paths = [
        CheckFailure("G5", f"menu path not in the cited FAQ: {chain}")
        for chain in _MENU_CHAIN.findall(draft)
        if not any(_follows(_menu_items(chain), path) for path in known_paths)
    ]
    unknown_labels = [
        CheckFailure("G5", f"quoted label not in the cited FAQ: {label}")
        for label in _QUOTED.findall(draft)
        if label.strip().casefold() not in known_labels
    ]
    return unknown_paths + unknown_labels


def _menu_items(chain: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in re.split(_ARROW, chain))


def _check_promises(draft: str) -> list[CheckFailure]:
    match = _PROMISE.search(fold(draft))
    return [CheckFailure("G6", f"promise or commitment: {match.group(0)}")] if match else []


def _check_personal_data(draft: str, ticket_text: str) -> list[CheckFailure]:
    failures = []
    if redact(draft).found:
        failures.append(CheckFailure("G7", "payment details or a BSN in the reply"))
    echoed = digit_runs(draft) & digit_runs(ticket_text)
    if echoed:
        failures.append(
            CheckFailure("G7", "repeats a number of four or more digits from the ticket")
        )
    return failures


def _check_leakage(draft: str) -> list[CheckFailure]:
    checks = (
        (_FAQ_ID, "internal FAQ ID"),
        (_HTML_TAG, "HTML tag"),
        (_ROLE_TAG, "role tag"),
        (_PLACEHOLDER, "redaction placeholder"),
    )
    failures = [CheckFailure("G8", name) for pattern, name in checks if pattern.search(draft)]
    if _SELF_REFERENCE.search(fold(draft)):
        failures.append(CheckFailure("G8", "talks about itself as an AI or its prompt"))
    if "{" in draft or "}" in draft:
        failures.append(CheckFailure("G8", "JSON or template braces"))
    return failures


def _check_language(
    draft: str, language: Language, faq: Faq, ticket_text: str
) -> list[CheckFailure]:
    failures = []
    detected = detect_language(draft, mask=faq.labels)
    if detected is not None and detected is not language:
        failures.append(CheckFailure("G9", f"reply is in {detected}, the ticket in {language}"))
    else:
        foreign = _foreign_sentence(draft, language, faq)
        if foreign is not None:
            failures.append(
                CheckFailure("G9", f"a sentence is not in {language}: {foreign[:60]!r}")
            )
    if language is Language.DUTCH and _mixes(draft.casefold(), _DUTCH_FORMAL, _DUTCH_INFORMAL):
        failures.append(CheckFailure("G9", "mixes formal 'u' and informal 'je'"))
    if language is Language.GERMAN and _mixes(draft, _GERMAN_FORMAL, _GERMAN_INFORMAL):
        failures.append(CheckFailure("G9", "mixes formal 'Sie' and informal 'du'"))
    greeting = _GREETING_NAME.match(draft)
    if greeting:
        name = greeting.group(1)
        if (
            name.casefold() not in _GENERIC_ADDRESSEES
            and name.casefold() not in ticket_text.casefold()
        ):
            failures.append(CheckFailure("G9", f"greets '{name}', who is not in the ticket"))
    return failures


def _foreign_sentence(draft: str, language: Language, faq: Faq) -> str | None:
    """A whole reply can read as Dutch while one copied sentence stays English."""
    for sentence in _SENTENCE_BREAK.split(draft):
        if len(sentence.split()) < MIN_SENTENCE_WORDS:
            continue
        detected = detect_language(sentence, mask=faq.labels)
        if detected is not None and detected is not language:
            return sentence.strip()
    return None


def _mixes(text: str, formal: re.Pattern[str], informal: re.Pattern[str]) -> bool:
    return bool(formal.search(text) and informal.search(text))


def _follows(items: tuple[str, ...], path: tuple[str, ...]) -> bool:
    if len(items) > len(path) or items[:-1] != path[: len(items) - 1]:
        return False
    last, expected = items[-1], path[len(items) - 1]
    return last == expected or last.startswith(f"{expected} ")


def _canonical_number(number: str) -> str:
    whole, _, fraction = number.replace(",", ".").partition(".")
    return whole if fraction.strip("0") == "" else number


def _normalise(text: str) -> str:
    return " ".join(text.casefold().split())
