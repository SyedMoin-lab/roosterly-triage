from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from triage.domain import Language
from triage.knowledge.faq import load_faq
from triage.safety.checks import check_draft

FAQ = load_faq(Path(__file__).resolve().parents[2] / "data" / "faq.md")
TICKET = "Hoi, ik ben mijn wachtwoord vergeten en kan niet meer inloggen. Groet, Anouk"
EVIDENCE = ("The reset link is valid for 60 minutes.",)
CLEAN_DRAFT = (
    "Hoi Anouk,\n\n"
    'Ga naar app.roosterly.nl/login en klik op "Wachtwoord vergeten". Vul daar je e-mailadres in. '
    "De resetlink is 60 minuten geldig. Heb je na 10 minuten nog geen e-mail ontvangen? "
    "Kijk dan ook even in je spamfolder.\n\n"
    "Groet,\nHet supportteam van Roosterly"
)
ENGLISH_DRAFT = (
    "Hi Anouk,\n\n"
    'Go to app.roosterly.nl/login and click "Wachtwoord vergeten". Enter your email address there. '
    "The reset link stays valid for 60 minutes. Still no email after 10 minutes? "
    "Then please check your spam folder as well.\n\n"
    "Kind regards,\nThe Roosterly support team"
)


def failed_codes(
    draft: str,
    *,
    cited_ids: Sequence[str] = ("F01",),
    evidence: Sequence[str] = EVIDENCE,
    covers_every_question: bool = True,
    language: Language = Language.DUTCH,
    ticket_text: str = TICKET,
) -> set[str]:
    failures = check_draft(
        draft,
        faq=FAQ,
        cited_ids=cited_ids,
        evidence=evidence,
        covers_every_question=covers_every_question,
        language=language,
        ticket_text=ticket_text,
    )
    return {failure.code for failure in failures}


def test_a_clean_faq_reply_passes_every_check() -> None:
    assert failed_codes(CLEAN_DRAFT) == set()


MUTATIONS: list[tuple[str, Callable[[str], str], str]] = [
    ("switched to English", lambda draft: ENGLISH_DRAFT, "G9"),
    ("IBAN inserted", lambda draft: draft + "\nOnze rekening is NL91ABNA0417164300.", "G7"),
    ("free month promised", lambda draft: draft + "\nJe krijgt deze maand gratis.", "G6"),
    (
        "invented URL",
        lambda draft: draft.replace("app.roosterly.nl/login", "www.roosterly.nl/help"),
        "G3",
    ),
    (
        "invented menu path",
        lambda draft: draft.replace("klik op", "ga naar Instellingen → Wachtwoord en klik op"),
        "G5",
    ),
    ("u and je mixed", lambda draft: draft.replace("Vul daar je", "Vul daar uw"), "G9"),
    ("number changed", lambda draft: draft.replace("60 minuten", "30 minuten"), "G4"),
    ("wrong name", lambda draft: draft.replace("Hoi Anouk", "Hoi Peter"), "G9"),
    ("internal FAQ ID", lambda draft: draft + "\nZie F01 voor meer informatie.", "G8"),
    ("email address", lambda draft: draft + "\nMail ons op help@roosterly.nl.", "G3"),
    ("markdown link", lambda draft: draft + "\n[Klik hier](https://evil.example.com)", "G3"),
    ("JSON in the reply", lambda draft: draft + '\n{"action": "reply"}', "G8"),
    ("unknown label", lambda draft: draft + '\nKlik daarna op "Bevestigen".', "G5"),
]


@pytest.mark.parametrize(
    ("mutate", "code"),
    [(mutate, code) for _, mutate, code in MUTATIONS],
    ids=[name for name, _, _ in MUTATIONS],
)
def test_each_mutation_of_a_clean_reply_is_caught(mutate: Callable[[str], str], code: str) -> None:
    assert code in failed_codes(mutate(CLEAN_DRAFT))


def test_a_reply_must_cite_known_entries_and_cover_every_question() -> None:
    assert "G1" in failed_codes(CLEAN_DRAFT, cited_ids=())
    assert "G1" in failed_codes(CLEAN_DRAFT, cited_ids=("F99",))
    assert "G1" in failed_codes(CLEAN_DRAFT, covers_every_question=False)
    assert "G1" in failed_codes("Kort.")


def test_evidence_must_come_from_the_cited_entry() -> None:
    assert "G2" in failed_codes(CLEAN_DRAFT, evidence=("Refunds are always possible.",))


def test_numbers_from_the_ticket_are_never_echoed() -> None:
    ticket = TICKET + " Mijn klantnummer is 88442211."
    assert "G7" in failed_codes(CLEAN_DRAFT + "\nKlantnummer 88442211.", ticket_text=ticket)


def test_a_menu_path_followed_by_normal_words_is_accepted() -> None:
    draft = (
        "Hallo,\n\nGa naar Team → Medewerker toevoegen en vul de naam, het e-mailadres en de "
        "contracturen in. Klik daarna op Uitnodigen; de medewerker krijgt dan een e-mail om de "
        "app te installeren.\n\nGroet,\nRoosterly"
    )
    failures = failed_codes(
        draft,
        cited_ids=("F02",),
        evidence=("Managers go to Team → Medewerker toevoegen (Add employee)",),
        ticket_text="Hoe voeg ik een nieuwe medewerker toe aan ons rooster?",
    )
    assert failures == set()


def test_german_replies_must_not_mix_sie_and_du() -> None:
    draft = (
        "Hallo,\n\nSie können die Sprache unter Profiel → Taal ändern. "
        "Danach siehst du die App auf Deutsch.\n\nViele Grüße"
    )
    failures = failed_codes(
        draft,
        cited_ids=("F08",),
        evidence=(),
        language=Language.GERMAN,
        ticket_text="Kann ich die App auf Deutsch nutzen?",
    )
    assert "G9" in failures
