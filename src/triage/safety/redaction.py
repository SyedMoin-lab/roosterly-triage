import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from stdnum import iban, luhn
from stdnum.nl import bsn

# Candidates are matched generously (an IBAN may be written in groups, in any case) and then
# shortened until the checksum passes, so the words that follow a number are never part of it.
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b", re.IGNORECASE)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_BSN = re.compile(r"(?<!\d)\d{9}(?!\d)")
# A card's security code or expiry date is only recognised next to its label, to avoid hiding
# ordinary numbers and dates.
_CVC = re.compile(
    r"\b(?:cvc2?|cvv2?|csc|security\s+code|beveiligingscode|kaartcode|prufnummer|pruefnummer)"
    r"\W{0,3}(\d{3,4})\b",
    re.IGNORECASE,
)
_EXPIRY = re.compile(
    r"\b(?:geldig\s+tot|vervaldatum|verloopdatum|expiry|expires|exp|valid\s+(?:until|thru|through)"
    r"|gultig\s+bis|gueltig\s+bis|gültig\s+bis|ablaufdatum)\W{0,3}(\d{1,2}\s*[/-]\s*\d{2,4})\b",
    re.IGNORECASE,
)
_SEPARATORS = re.compile(r"[ -]")
_LONG_DIGIT_RUN = re.compile(r"\d{4,}")
_MIN_CARD_DIGITS = 13

PLACEHOLDERS = {
    "iban": "[IBAN]",
    "card": "[CARD]",
    "bsn": "[BSN]",
    "cvc": "[CVC]",
    "expiry": "[EXPIRY]",
}

type Ends = Callable[[str], Iterator[int]]


@dataclass(frozen=True, slots=True)
class Redaction:
    text: str
    found: Counter[str]

    @property
    def has_payment_details(self) -> bool:
        return bool(self.found["iban"] or self.found["card"] or self.found["cvc"])


def redact(text: str) -> Redaction:
    found: Counter[str] = Counter()
    for kind, pattern, is_valid, ends in (
        ("iban", _IBAN, _passes_iban_checksum, _token_ends),
        ("card", _CARD, luhn.is_valid, _digit_ends),
        ("bsn", _BSN, bsn.is_valid, _whole),
    ):
        text = _redact_checked(text, kind, pattern, is_valid, ends, found)
    for kind, pattern in (("cvc", _CVC), ("expiry", _EXPIRY)):
        text = _redact_labelled(text, kind, pattern, found)
    return Redaction(text, found)


def scrub(value: object) -> object:
    if isinstance(value, str):
        return redact(value).text
    if isinstance(value, list | tuple):
        return [scrub(item) for item in value]
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items()}
    return value


def digit_runs(text: str) -> frozenset[str]:
    return frozenset(_LONG_DIGIT_RUN.findall(_SEPARATORS.sub("", text)))


def _redact_checked(
    text: str,
    kind: str,
    pattern: re.Pattern[str],
    is_valid: Callable[[str], bool],
    ends: Ends,
    found: Counter[str],
) -> str:
    """Replace every candidate whose longest valid prefix passes the checksum."""
    pieces: list[str] = []
    kept_until = search_from = 0
    while (match := pattern.search(text, search_from)) is not None:
        end = next(
            (
                match.start() + length
                for length in ends(match.group(0))
                if is_valid(_SEPARATORS.sub("", match.group(0)[:length]))
            ),
            None,
        )
        if end is None:
            search_from = match.start() + 1
            continue
        pieces += [text[kept_until : match.start()], PLACEHOLDERS[kind]]
        found[kind] += 1
        kept_until = search_from = end
    pieces.append(text[kept_until:])
    return "".join(pieces)


def _redact_labelled(text: str, kind: str, pattern: re.Pattern[str], found: Counter[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        found[kind] += 1
        start, end = match.span(1)
        whole = match.group(0)
        offset = match.start()
        return whole[: start - offset] + PLACEHOLDERS[kind] + whole[end - offset :]

    return pattern.sub(replace, text)


def _token_ends(candidate: str) -> Iterator[int]:
    """Lengths that end at a token boundary, longest first: 'NL91ABNA0417164300 en' -> 21, 18."""
    ends = [match.end() for match in re.finditer(r"\S+", candidate)]
    return reversed(ends)


def _digit_ends(candidate: str) -> Iterator[int]:
    """Lengths that end after a digit and keep at least 13 digits, longest first."""
    lengths = []
    digits = 0
    for position, char in enumerate(candidate, start=1):
        if char.isdigit():
            digits += 1
            if digits >= _MIN_CARD_DIGITS:
                lengths.append(position)
    return reversed(lengths)


def _whole(candidate: str) -> Iterator[int]:
    yield len(candidate)


def _passes_iban_checksum(value: str) -> bool:
    return bool(iban.is_valid(value, check_country=False))
