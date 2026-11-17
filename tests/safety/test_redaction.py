import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from triage.safety.redaction import digit_runs, redact
from triage.safety.text import clean

VALID_CARD = "4111 1111 1111 1111"
FULL_WIDTH_CARD = (
    "\N{FULLWIDTH DIGIT FOUR}" + "\N{FULLWIDTH DIGIT ONE}" * 3 + ("\N{NO-BREAK SPACE}1111" * 3)
)


@pytest.mark.parametrize(
    "iban",
    [
        "NL91ABNA0417164300",
        "NL91 ABNA 0417 1643 00",
        "BE71096123456769",
        "BE68539007547034",
        "DE89 3704 0044 0532 0130 00",
    ],
)
def test_ibans_that_pass_the_checksum_are_redacted_whatever_the_bank(iban: str) -> None:
    result = redact(f"Mijn rekening is {iban}, graag controleren.")
    assert result.text == "Mijn rekening is [IBAN], graag controleren."
    assert result.has_payment_details


@pytest.mark.parametrize(
    "card", [VALID_CARD, "4111-1111-1111-1111", "4111111111111111", "5555 5555 5555 4444"]
)
def test_luhn_valid_card_numbers_are_redacted(card: str) -> None:
    assert redact(f"Kaart {card} is geblokkeerd").text == "Kaart [CARD] is geblokkeerd"


def test_full_width_and_non_breaking_card_numbers_are_redacted_after_cleaning() -> None:
    assert redact(clean(FULL_WIDTH_CARD).text).text == "[CARD]"


def test_a_number_that_fails_luhn_is_not_payment_data() -> None:
    result = redact("Klantnummer 1234 5678 9012 3456")
    assert result.text == "Klantnummer 1234 5678 9012 3456"
    assert not result.has_payment_details


def test_a_valid_bsn_is_redacted_and_an_invalid_one_is_not() -> None:
    assert redact("BSN 111222333").text == "BSN [BSN]"
    assert redact("Order 123456789").text == "Order 123456789"


def test_digit_runs_join_numbers_split_by_spaces_or_dashes() -> None:
    assert digit_runs("klant 12 34-56 en 789") == {"123456"}


@given(
    prefix=st.text(alphabet="abc ,.", max_size=20),
    suffix=st.text(alphabet="abc ,.", max_size=20),
)
def test_redaction_is_idempotent_and_leaves_no_card_digits(prefix: str, suffix: str) -> None:
    once = redact(f"{prefix}{VALID_CARD}{suffix}")
    assert redact(once.text).text == once.text
    assert not re.search(r"\d{4}", once.text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Mijn IBAN is NL91ABNA0417164300 en ik wil het geld graag terug",
            "Mijn IBAN is [IBAN] en ik wil het geld graag terug",
        ),
        (
            "Rekening: NL91 ABNA 0417 1643 00 graag deze gebruiken",
            "Rekening: [IBAN] graag deze gebruiken",
        ),
        ("iban nl91abna0417164300 klopt nog", "iban [IBAN] klopt nog"),
        (
            "Oud NL91ABNA0417164300 of nieuw BE68539007547034, welke?",
            "Oud [IBAN] of nieuw [IBAN], welke?",
        ),
        ("Kaart 4111 1111 1111 1111 123 is afgeschreven", "Kaart [CARD] 123 is afgeschreven"),
    ],
)
def test_a_number_is_hidden_whatever_follows_it(text: str, expected: str) -> None:
    assert redact(text).text == expected


def test_a_cards_security_code_and_expiry_date_are_hidden_next_to_their_label() -> None:
    redaction = redact("Nieuwe kaart, geldig tot 09/28, CVC 123. Groet")
    assert redaction.text == "Nieuwe kaart, geldig tot [EXPIRY], CVC [CVC]. Groet"
    assert redaction.has_payment_details


def test_ordinary_numbers_and_dates_stay_readable() -> None:
    text = "Ons team heeft 123 medewerkers en de dienst start op 09/12 om 14:00."
    assert redact(text).text == text
