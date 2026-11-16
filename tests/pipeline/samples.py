from datetime import UTC, datetime
from pathlib import Path

from triage.domain import Action, Category, Language, Priority, Ticket
from triage.knowledge.faq import load_faq
from triage.pipeline.schemas import (
    Claim,
    CustomerQuestion,
    DraftReply,
    SafetyAudit,
    TriageProposal,
    Verification,
)

FAQ = load_faq(Path(__file__).resolve().parents[2] / "data" / "faq.md")
QUESTION = "Hoe voeg ik een nieuwe medewerker toe aan ons rooster?"
REFUND = "We waren in augustus dicht. Kunnen we het abonnement van die maand terugkrijgen?"
PAYROLL = "Kan ik de goedgekeurde uren exporteren naar Nmbrs?"

GOOD_DRAFT = DraftReply(
    reply=(
        "Hallo,\n\nGa naar Team → Medewerker toevoegen en vul de naam, het e-mailadres en de "
        "contracturen in. Klik daarna op Uitnodigen; de medewerker krijgt dan een e-mail om de "
        "app te installeren.\n\nGroet,\nHet supportteam van Roosterly"
    ),
    cited_ids=["F02"],
    evidence=["Managers go to Team → Medewerker toevoegen (Add employee)"],
)
BAD_DRAFT = DraftReply(
    reply=GOOD_DRAFT.reply.replace("Groet", "Meer info op www.roosterly.nl/help. Groet"),
    cited_ids=["F02"],
    evidence=GOOD_DRAFT.evidence,
)
PLUS_DRAFT = DraftReply(
    reply=(
        "Hallo,\n\nDe koppeling met Nmbrs, Loket.nl en AFAS hoort bij het Plus-abonnement. "
        "Je kunt op elk moment upgraden via Instellingen → Abonnement. Daarna stel je de export "
        "in onder Instellingen → Koppelingen → Salaris.\n\nGroet,\nHet supportteam van Roosterly"
    ),
    cited_ids=["F04", "F05"],
    evidence=["Set this up under Instellingen → Koppelingen → Salaris"],
)
PASS = Verification(
    back_translation="Hello, go to Team → Add employee and fill in the name.",
    claims=[Claim(claim="Employees are added under Team → Medewerker toevoegen.", supported=True)],
    answers_every_question=True,
    verdict="pass",
)
FAIL = PASS.model_copy(
    update={"verdict": "fail", "claims": [Claim(claim="It is free.", supported=False)]}
)
CLEAN_AUDIT = SafetyAudit(violation=False, rule="none", rationale="A how-to question.")


def ticket(
    body: str, *, subject: str = "Vraag", plan: str = "Basis", ticket_id: str = "T001"
) -> Ticket:
    return Ticket(
        id=ticket_id,
        received_at=datetime(2026, 11, 17, 8, 0, tzinfo=UTC),
        channel="email",
        customer_plan=plan,
        subject=subject,
        body=body,
    )


def proposal(
    action: Action = Action.REPLY,
    *,
    faq_ids: tuple[str, ...] = ("F02",),
    priority: Priority = Priority.P4,
    category: Category = Category.QUESTION,
) -> TriageProposal:
    questions = [
        CustomerQuestion(question="How do I add a new employee?", faq_id=faq_id)
        for faq_id in faq_ids
    ]
    return TriageProposal(
        language=Language.DUTCH,
        category=category,
        priority=priority,
        action=action,
        questions=questions,
        evidence=["Managers go to Team → Medewerker toevoegen (Add employee)"],
        english_summary="The customer asks how to add a new employee to the rota.",
        reason="A how-to question that the help centre answers; no urgency.",
    )
