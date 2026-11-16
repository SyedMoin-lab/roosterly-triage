from pathlib import Path

import pytest

from triage.knowledge.faq import Faq, load_faq, parse_faq

FAQ_PATH = Path(__file__).resolve().parents[2] / "data" / "faq.md"


@pytest.fixture(scope="module")
def faq() -> Faq:
    return load_faq(FAQ_PATH)


def test_all_twelve_entries_are_parsed_in_order(faq: Faq) -> None:
    assert [entry.id for entry in faq.entries] == [f"F{number:02d}" for number in range(1, 13)]
    assert faq["F01"].title == "Forgotten password"


def test_menu_paths_keep_the_dutch_labels_only(faq: Faq) -> None:
    assert ("Team", "Medewerker toevoegen") in faq["F02"].menu_paths
    assert ("Instellingen", "Abonnement", "Facturen") in faq["F06"].menu_paths
    assert ("Instellingen", "Bedrijfsgegevens") in faq["F06"].menu_paths
    assert all("Settings" not in path for entry in faq.entries for path in entry.menu_paths)


def test_labels_urls_and_numbers_are_extracted(faq: Faq) -> None:
    assert "Wachtwoord vergeten" in faq["F01"].labels
    assert "Uitnodigen" in faq["F02"].labels
    assert faq["F01"].urls == {"app.roosterly.nl/login"}
    assert faq["F01"].numbers == {"60", "10"}
    assert faq["F05"].numbers == {"4", "6"}
    assert faq["F12"].numbers == {"16", "10"}


def test_the_client_rules_are_parsed(faq: Faq) -> None:
    assert len(faq.rules) == 5
    assert faq.rules[1].startswith("These always go to a human")
    assert "customers threatening to leave" in faq.rules[1]


def test_unknown_entries_raise() -> None:
    with pytest.raises(KeyError):
        parse_faq("## F01 · Only entry\nText.\n")["F02"]


def test_the_hash_changes_when_the_faq_changes() -> None:
    first = parse_faq("## F01 · A\nOne.\n")
    second = parse_faq("## F01 · A\nTwo.\n")
    assert first.sha256 != second.sha256
