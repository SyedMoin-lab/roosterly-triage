import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from stdnum import iban, luhn
from stdnum.nl import bsn

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b", re.IGNORECASE)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_BSN = re.compile(r"(?<!\d)\d{9}(?!\d)")
_SEPARATORS = re.compile(r"[ -]")
_LONG_DIGIT_RUN = re.compile(r"\d{4,}")

PLACEHOLDERS = {"iban": "[IBAN]", "card": "[CARD]", "bsn": "[BSN]"}


@dataclass(frozen=True, slots=True)
class Redaction:
    text: str
    found: Counter[str]

    @property
    def has_payment_details(self) -> bool:
        return bool(self.found["iban"] or self.found["card"])


def redact(text: str) -> Redaction:
    found: Counter[str] = Counter()
    for kind, pattern, is_valid in (
        ("iban", _IBAN, _passes_iban_checksum),
        ("card", _CARD, luhn.is_valid),
        ("bsn", _BSN, bsn.is_valid),
    ):
        text = pattern.sub(_replacer(kind, is_valid, found), text)
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


def _passes_iban_checksum(value: str) -> bool:
    return bool(iban.is_valid(value, check_country=False))


def _replacer(
    kind: str, is_valid: Callable[[str], bool], found: Counter[str]
) -> Callable[[re.Match[str]], str]:
    def replace(match: re.Match[str]) -> str:
        if is_valid(_SEPARATORS.sub("", match.group(0))):
            found[kind] += 1
            return PLACEHOLDERS[kind]
        return match.group(0)

    return replace
