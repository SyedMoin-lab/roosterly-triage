import pytest

from triage.domain import Language
from triage.language import detect_language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hoe voeg ik een nieuwe medewerker toe aan ons rooster?", Language.DUTCH),
        ("How do I add a new employee to our rota?", Language.ENGLISH),
        ("Wie füge ich einen neuen Mitarbeiter zu unserem Dienstplan hinzu?", Language.GERMAN),
    ],
)
def test_each_supported_language_is_detected(text: str, expected: Language) -> None:
    assert detect_language(text) is expected


def test_dutch_menu_labels_do_not_turn_an_english_ticket_dutch() -> None:
    text = "Where do I find Instellingen → Koppelingen → Salaris in the app on my phone?"
    labels = {"Instellingen", "Koppelingen", "Salaris"}
    assert detect_language(text, mask=labels) is Language.ENGLISH


def test_too_little_text_gives_no_answer() -> None:
    assert detect_language("Hoi!") is None
    assert detect_language("app.roosterly.nl/login") is None
