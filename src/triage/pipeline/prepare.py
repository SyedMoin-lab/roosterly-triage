import re
from dataclasses import dataclass

from triage.domain import Language, Ticket
from triage.knowledge.faq import Faq
from triage.language import detect_language
from triage.safety.redaction import redact
from triage.safety.rules import RuleHit, find_injection, find_rule_hits
from triage.safety.text import clean, fold

_AUTOMATIC_REPLY = re.compile(
    r"\b(?:out\s+of\s+(?:the\s+)?office|automatic\s+reply|auto-?reply|"
    r"automatisch\s+(?:antwoord|bericht)|afwezigheidsmelding|"
    r"ik\s+ben\s+(?:tot\s+en\s+met\s+\S+\s+|momenteel\s+|vandaag\s+)?afwezig|"
    r"abwesenheitsnotiz|automatische\s+antwort|ich\s+bin\s+(?:bis\s+\S+\s+)?nicht\s+im\s+buro)\b"
)


@dataclass(frozen=True, slots=True)
class Prepared:
    ticket: Ticket
    subject: str
    body: str
    folded: str
    flags: frozenset[str]
    redacted: dict[str, int]
    detected_language: Language | None
    hits: tuple[RuleHit, ...]
    injection: str | None
    is_empty: bool
    is_automatic_reply: bool

    @property
    def text(self) -> str:
        return f"{self.subject}\n\n{self.body}".strip()


def prepare(ticket: Ticket, faq: Faq) -> Prepared:
    subject, body = clean(ticket.subject), clean(ticket.body)
    safe_subject, safe_body = redact(subject.text), redact(body.text)
    combined = f"{safe_subject.text}\n\n{safe_body.text}".strip()
    folded = fold(combined)
    return Prepared(
        ticket=ticket,
        subject=safe_subject.text,
        body=safe_body.text,
        folded=folded,
        flags=subject.flags | body.flags,
        redacted=dict(safe_subject.found + safe_body.found),
        detected_language=detect_language(combined, mask=faq.labels),
        hits=tuple(find_rule_hits(folded)),
        injection=find_injection(folded),
        is_empty=not any(char.isalpha() for char in combined),
        is_automatic_reply=bool(_AUTOMATIC_REPLY.search(folded)),
    )
