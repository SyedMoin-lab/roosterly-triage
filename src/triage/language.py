import re
from collections.abc import Iterable
from functools import cache

from fast_langdetect.infer import LangDetectConfig, LangDetector
from lingua import Language as LinguaLanguage
from lingua import LanguageDetector, LanguageDetectorBuilder

from triage.domain import Language

MIN_LETTERS = 20
_URL = re.compile(r"(?:https?://)?(?:[\w-]+\.)+(?:nl|com|eu|de|io|org|net)(?:/\S*)?", re.IGNORECASE)
_PRODUCT_NAMES = ("Roosterly", "Nmbrs", "Loket.nl", "Loket", "AFAS", "iOS", "Android")
_FROM_LINGUA = {
    LinguaLanguage.DUTCH: Language.DUTCH,
    LinguaLanguage.ENGLISH: Language.ENGLISH,
    LinguaLanguage.GERMAN: Language.GERMAN,
}
_FROM_CODE = {"nl": Language.DUTCH, "en": Language.ENGLISH, "de": Language.GERMAN}


@cache
def _lingua() -> LanguageDetector:
    return LanguageDetectorBuilder.from_languages(*_FROM_LINGUA).build()


@cache
def _fasttext() -> LangDetector:
    return LangDetector(LangDetectConfig(max_input_length=2000, model="lite"))


def detect_language(text: str, *, mask: Iterable[str] = ()) -> Language | None:
    masked = _URL.sub(" ", text)
    for term in sorted({*mask, *_PRODUCT_NAMES}, key=len, reverse=True):
        masked = masked.replace(term, " ")
    masked = " ".join(masked.split())
    if sum(char.isalpha() for char in masked) < MIN_LETTERS:
        return None
    lingua_guess = _lingua().detect_language_of(masked)
    by_lingua = _FROM_LINGUA.get(lingua_guess) if lingua_guess is not None else None
    best = _fasttext().detect(masked, k=1)
    by_fasttext = _FROM_CODE.get(str(best[0]["lang"])) if best else None
    return by_lingua if by_lingua is not None and by_lingua is by_fasttext else None
