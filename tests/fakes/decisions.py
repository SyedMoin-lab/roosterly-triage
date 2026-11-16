from triage.domain import Action, Category, Decision, Language, Priority

REPLY = Decision(
    action=Action.REPLY,
    language=Language.DUTCH,
    category=Category.QUESTION,
    priority=Priority.P4,
    reason="How-to question answered by FAQ F02. No urgency.",
    draft_reply="Ga naar Team en kies Medewerker toevoegen.",
    confidence=0.9,
)

HANDOFF = Decision(
    action=Action.HANDOFF,
    language=Language.DUTCH,
    category=Category.BILLING,
    priority=Priority.P2,
    reason="Refund request. Client rule: refunds always go to a human.",
    handoff_note="Customer asks for a refund for August. Check the account and reply.",
)

CLOSE = Decision(
    action=Action.CLOSE,
    language=Language.DUTCH,
    category=Category.OTHER,
    priority=Priority.P4,
    reason="Empty ticket with nothing to answer.",
)
