import re
import unicodedata
from dataclasses import dataclass

_INVISIBLE_RANGES = (
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xE0000, 0xE007F),
)
_INVISIBLE = re.compile(
    "["
    + "".join(
        f"{re.escape(chr(first))}-{re.escape(chr(last))}" for first, last in _INVISIBLE_RANGES
    )
    + "]"
)
_LOOKALIKES = {
    "a": ("CYRILLIC SMALL LETTER A", "GREEK SMALL LETTER ALPHA"),
    "c": ("CYRILLIC SMALL LETTER ES",),
    "d": ("CYRILLIC SMALL LETTER KOMI DE",),
    "e": ("CYRILLIC SMALL LETTER IE", "CYRILLIC SMALL LETTER IO", "GREEK SMALL LETTER EPSILON"),
    "h": ("CYRILLIC SMALL LETTER SHHA",),
    "i": (
        "CYRILLIC SMALL LETTER BYELORUSSIAN-UKRAINIAN I",
        "CYRILLIC SMALL LETTER YI",
        "GREEK SMALL LETTER IOTA",
    ),
    "j": ("CYRILLIC SMALL LETTER JE",),
    "k": ("CYRILLIC SMALL LETTER KA", "GREEK SMALL LETTER KAPPA"),
    "l": ("CYRILLIC SMALL LETTER PALOCHKA",),
    "o": ("CYRILLIC SMALL LETTER O", "GREEK SMALL LETTER OMICRON"),
    "p": ("CYRILLIC SMALL LETTER ER", "GREEK SMALL LETTER RHO"),
    "q": ("CYRILLIC SMALL LETTER QA",),
    "s": ("CYRILLIC SMALL LETTER DZE",),
    "u": ("GREEK SMALL LETTER UPSILON",),
    "v": ("GREEK SMALL LETTER NU",),
    "w": ("CYRILLIC SMALL LETTER WE",),
    "x": ("CYRILLIC SMALL LETTER HA", "GREEK SMALL LETTER CHI"),
    "y": ("CYRILLIC SMALL LETTER U",),
    "A": ("CYRILLIC CAPITAL LETTER A", "GREEK CAPITAL LETTER ALPHA"),
    "B": ("CYRILLIC CAPITAL LETTER VE", "GREEK CAPITAL LETTER BETA"),
    "C": ("CYRILLIC CAPITAL LETTER ES",),
    "E": ("CYRILLIC CAPITAL LETTER IE", "GREEK CAPITAL LETTER EPSILON"),
    "H": ("CYRILLIC CAPITAL LETTER EN", "GREEK CAPITAL LETTER ETA"),
    "I": ("CYRILLIC CAPITAL LETTER BYELORUSSIAN-UKRAINIAN I", "GREEK CAPITAL LETTER IOTA"),
    "J": ("CYRILLIC CAPITAL LETTER JE",),
    "K": ("CYRILLIC CAPITAL LETTER KA", "GREEK CAPITAL LETTER KAPPA"),
    "M": ("CYRILLIC CAPITAL LETTER EM", "GREEK CAPITAL LETTER MU"),
    "N": ("GREEK CAPITAL LETTER NU",),
    "O": ("CYRILLIC CAPITAL LETTER O", "GREEK CAPITAL LETTER OMICRON"),
    "P": ("CYRILLIC CAPITAL LETTER ER", "GREEK CAPITAL LETTER RHO"),
    "S": ("CYRILLIC CAPITAL LETTER DZE",),
    "T": ("CYRILLIC CAPITAL LETTER TE", "GREEK CAPITAL LETTER TAU"),
    "X": ("CYRILLIC CAPITAL LETTER HA", "GREEK CAPITAL LETTER CHI"),
    "Y": ("CYRILLIC CAPITAL LETTER U", "GREEK CAPITAL LETTER UPSILON"),
    "Z": ("GREEK CAPITAL LETTER ZETA",),
}
_CONFUSABLES = {
    unicodedata.lookup(name): latin for latin, names in _LOOKALIKES.items() for name in names
}
_TO_LATIN = str.maketrans(_CONFUSABLES)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WORD = re.compile(r"\w+")
_SPACES = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True, slots=True)
class CleanText:
    text: str
    folded: str
    flags: frozenset[str]


def clean(raw: str) -> CleanText:
    flags: set[str] = set()
    text = unicodedata.normalize("NFKC", raw)
    without_comments = _HTML_COMMENT.sub(" ", text)
    if without_comments != text:
        flags.add("html_comment")
    visible = _INVISIBLE.sub("", without_comments)
    if visible != without_comments:
        flags.add("hidden_characters")
    latin = _WORD.sub(_unmix_scripts, _CONTROL.sub(" ", visible))
    if latin != visible:
        flags.add("mixed_script")
    tidy = _BLANK_LINES.sub("\n\n", _SPACES.sub(" ", latin)).strip()
    return CleanText(text=tidy, folded=fold(tidy), flags=frozenset(flags))


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_accents.split())


def _unmix_scripts(match: re.Match[str]) -> str:
    word = match.group(0)
    has_latin = any("a" <= char.lower() <= "z" for char in word)
    if has_latin and any(char in _CONFUSABLES for char in word):
        return word.translate(_TO_LATIN)
    return word
