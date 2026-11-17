import re
from dataclasses import dataclass

from triage.domain import Priority

_NEAR = 80
_GAP = r"(?:\s+\S+){0,6}?\s+"
_SHORT_GAP = r"(?:\s+\S+){0,4}?\s+"
_PLAN = r"(?:plus|basis)"
_PLAN_PRODUCT = rf"{_PLAN}[\s-]*(?:abonnement|pakket|plan|subscription|abo)\b"
_CHANGE = (
    r"(?:overstappen|overgaan|overzetten|upgraden|upgrade|downgraden|downgrade|omzetten|wisselen|"
    r"wijzigen|"
    r"aanpassen|terug|switch\w*|move|change\w*|wechseln|umstellen|umsteigen)"
)
_STAFF = re.compile(
    r"\b(?:medewerkers?|werknemers?|personeel|collega'?s?|stagiairs?|oproepkrachten?|"
    r"uitzendkrachten?|baan|dienstverband|ontslag|mitarbeiter\w*|angestellte\w*|"
    r"employees?|staff|workers?|colleagues?)\b"
)


@dataclass(frozen=True, slots=True)
class Trigger:
    pattern: re.Pattern[str]
    unless_near: re.Pattern[str] | None = None

    def find(self, folded: str) -> str | None:
        for match in self.pattern.finditer(folded):
            if self.unless_near is not None:
                window = folded[max(0, match.start() - _NEAR) : match.end() + _NEAR]
                if self.unless_near.search(window):
                    continue
            return match.group(0)
        return None


@dataclass(frozen=True, slots=True)
class Rule:
    code: str
    summary: str
    minimum_priority: Priority
    next_step: str
    triggers: tuple[Trigger, ...]


@dataclass(frozen=True, slots=True)
class RuleHit:
    rule: Rule
    evidence: str


def _when(*patterns: str, unless_near: re.Pattern[str] | None = None) -> tuple[Trigger, ...]:
    return tuple(Trigger(re.compile(pattern), unless_near) for pattern in patterns)


REFUND = Rule(
    "R1",
    "refund or disputed charge",
    Priority.P2,
    "Check the invoices and payments on the account, then decide on a refund or correction.",
    _when(
        r"\bterugbetal\w*",
        r"\bterug\s*(?:te\s+)?(?:betalen|storten|boeken)\b",
        rf"\b(?:stort|storten|betaal|betalen|boek|boeken){_GAP}terug\b",
        rf"\b(?:geld|bedrag|kosten){_GAP}terug\b",
        rf"\b(?:maand|maanden|abonnementskosten){_GAP}terug\s*(?:te\s+)?(?:krijgen|betaald|gestort)",
        r"\b(?:geld\s+terug|restitutie|chargeback|storno|storneren|creditnota)\b",
        rf"\bonterecht\w*{_GAP}(?:afgeschreven|gefactureerd|in\s+rekening|betaald|aangerekend)\b",
        r"\b(?:dubbel|twee\s*keer|2x)\s+(?:betaald|afgeschreven|gefactureerd|in\s+rekening)\b",
        r"\bte\s*veel\s+(?:betaald|gefactureerd|afgeschreven|in\s+rekening)\b",
        rf"\b(?:factuur|rekening|bedrag|afschrijving|kosten|incasso){_GAP}(?:klopt|klopten)\s+niet\b",
        rf"\b(?:factuur|rekening|bedrag|afschrijving|kosten){_GAP}(?:onjuist|te\s+hoog|fout|verkeerd)\b",
        rf"\b(?:betalen|betaal|pay|paying|zahlen){_GAP}(?:maar|terwijl|but|while|aber|obwohl)\b",
        r"\b(?:refund\w*|money\s+back|charge\s*back|overcharg\w*)",
        r"\b(?:wrongly|incorrectly|double|twice)\s+(?:charged|billed)\b",
        r"\b(?:charged|billed)\s+(?:twice|double|two\s+times|too\s+much)\b",
        r"\bdisputed?\s+(?:charge|invoice|payment|transaction)\b",
        rf"\b(?:invoice|bill|charge){_GAP}(?:wrong|incorrect|too\s+high)\b",
        r"\b(?:ruckerstatt|erstatt|zuruckzahl|zuruckerstatt)\w*|\bgeld\s+zuruck\b|\bgutschrift\b",
        r"\b(?:doppelt|falsch|zu\s+viel)\s+(?:abgebucht|berechnet|bezahlt|belastet)\b",
        rf"\b(?:rechnung|betrag|abbuchung){_GAP}(?:falsch|stimmt\s+nicht|zu\s+hoch)\b",
    ),
)

CANCELLATION = Rule(
    "R2",
    "cancellation or contract change",
    Priority.P2,
    "Confirm the cancellation or plan change with the account owner and process it.",
    _when(
        r"\bopzeg\w*",
        r"\bkundig\w*",
        r"\b(?:contract|vertrag)\b(?:\s+\S+){0,5}?\s+"
        r"(?:op|opzeggen|opgezegd|beeindigen|stoppen|kundigen|beenden|cancel\w*|terminat\w*)\b",
        unless_near=_STAFF,
    )
    + _when(
        r"\bzeg(?:gen|t|den|de)?\b(?:\s+\S+){0,5}?\s+(?:abonnement|account|lidmaatschap|roosterly)"
        r"\b(?:\s+\S+){0,3}?\s+op\b",
        r"\b(?:abonnement|account|lidmaatschap|samenwerking|roosterly)\b(?:\s+\S+){0,5}?\s+"
        r"(?:opzeggen|opgezegd|annuleren|geannuleerd|stopzetten|beeindigen|opheffen|stoppen|"
        r"deactiveren)\b",
        r"\b(?:annuleren|stopzetten|beeindigen|opheffen|deactiveren)\b(?:\s+\S+){0,5}?\s+"
        r"(?:abonnement|account|lidmaatschap)\b",
        rf"\b{_CHANGE}\b{_SHORT_GAP}(?:naar|to|auf)\s+(?:het\s+|the\s+|de\s+|das\s+)?{_PLAN}\b",
        rf"\b{_PLAN_PRODUCT}{_SHORT_GAP}{_CHANGE}\b",
        rf"\b{_CHANGE}\b{_SHORT_GAP}{_PLAN_PRODUCT}",
        r"\b(?:abonnement|pakket)\b(?:\s+\S+){0,4}?\s+(?:wijzigen|aanpassen|veranderen|omzetten)\b",
        r"\b(?:upgraden|downgraden|geupgraded|gedowngraded)\b",
        r"\b(?:upgrade|downgrade)\s+(?:to|our|my|the)\b",
        r"\bcancel\w*\b(?:\s+\S+){0,4}?\s+(?:subscription|account|plan|membership)\b",
        r"\b(?:subscription|membership)\b(?:\s+\S+){0,4}?\s+"
        r"(?:cancel\w*|terminat\w*|end|ended|stop|stopped|close|closed)\b",
        r"\bterminat\w*\b(?:\s+\S+){0,4}?\s+(?:subscription|agreement|account)\b",
        r"\bunsubscribe\b",
        r"\b(?:abo|abonnement|mitgliedschaft)\w*\b(?:\s+\S+){0,4}?\s+"
        r"(?:beenden|stornieren|andern|wechseln|aufheben)\b",
    ),
)

PERSONAL_DATA = Rule(
    "R3",
    "personal data request (GDPR, AVG in Dutch)",
    Priority.P2,
    "Handle it as a GDPR (AVG) request: verify the requester and answer within the legal deadline.",
    _when(
        r"\b(?:avg|gdpr|dsgvo|ds-gvo)\b",
        r"\b(?:inzageverzoek|verwijderverzoek|inzagerecht|vergetelheid|persoonsgegevens)\b",
        r"\brecht\s+op\s+(?:inzage|verwijdering|vergetelheid|dataportabiliteit|rectificatie)\b",
        r"\b(?:verwijder\w*|wis|wissen|inzien|inzage|opvragen)\b(?:\s+\S+){0,5}?\s+"
        r"(?:gegevens|data|informatie)\b",
        r"\b(?:mijn|onze|alle)\s+(?:gegevens|data)\b(?:\s+\S+){0,4}?\s+"
        r"(?:verwijderen|wissen|inzien|opvragen)\b",
        r"\bright\s+to\s+(?:be\s+forgotten|erasure|access|portability)\b",
        r"\b(?:delete|erase|remove)\b(?:\s+\S+){0,4}?\s+(?:my|our|all)\b(?:\s+\S+){0,2}?\s+"
        r"(?:personal\s+)?(?:data|information)\b",
        r"\bpersonal\s+data\b|\bdata\s+subject\b|\bsubject\s+access\b|\bdsar\b",
        r"\bpersonenbezogen\w*\s+daten\b|\bdatenauskunft\b|\bdatenschutzanfrage\b",
        r"\b(?:loschung|loschen|auskunft)\b(?:\s+\S+){0,4}?\s+(?:\S+\s+)?(?:daten|konto)\b",
        r"\brecht\s+auf\s+(?:vergessenwerden|loschung|auskunft)\b",
    ),
)

SECURITY = Rule(
    "R4",
    "possible security incident",
    Priority.P1,
    "Treat it as a possible security incident: check recent logins and secure the account first.",
    _when(
        r"\b(?:gehackt|hack|hacked|hacker\w*|ingebroken|datalek\w*|phishing|malware|ransomware)\b",
        r"\b(?:lek|gelekt|uitgelekt)\b(?:\s+\S+){0,3}?\s+(?:gegevens|data|wachtwoord\w*)\b",
        r"\b(?:gegevens|data|wachtwoord\w*)\b(?:\s+\S+){0,3}?\s+(?:gelekt|uitgelekt|gestolen)\b",
        r"\bverdacht\w*\s+(?:inlog\w*|activiteit\w*|e-?mails?|berichten?|login\w*)\b",
        r"\bonbekende?\s+(?:inlog\w*|login\w*|apparaat|apparaten|ip)\b",
        r"\b(?:iemand\s+anders|een\s+onbekende|onbekenden|vreemden?|derden)\b(?:\s+\S+){0,6}?\s+"
        r"(?:toegang|ingelogd|inloggen|ingelogt)\b",
        r"\baccount\b(?:\s+\S+){0,4}?\s+(?:overgenomen|gekaapt)\b",
        r"\bwachtwoord\b(?:\s+\S+){0,4}?\s+(?:veranderd|gewijzigd)\s+zonder\b",
        r"\b(?:ongeautoriseerd\w*|onbevoegd\w*)\b",
        r"\b(?:breach\w*|compromised|data\s+leak|unauthori[sz]ed)\b",
        r"\bsuspicious\s+(?:login|activity|e-?mails?|access)\b",
        r"\b(?:someone|somebody)\s+else\b(?:\s+\S+){0,6}?\s+(?:logged\s+in|accessed|access)\b",
        r"\b(?:account|password)\b(?:\s+\S+){0,4}?\s+(?:taken\s+over|hijacked|stolen|leaked)\b",
        r"\b(?:datenleck|sicherheitslucke|unbefugt\w*)\b",
        r"\bverdachtig\w*\s+(?:anmeldung\w*|login\w*|aktivitat\w*)\b",
        r"\b(?:jemand\s+anderes|unbekannte?)\b(?:\s+\S+){0,6}?\s+(?:eingeloggt|zugriff|angemeldet)\b",
        r"\bpasswort\b(?:\s+\S+){0,4}?\s+(?:gestohlen|geleakt)\b",
    ),
)

LEGAL = Rule(
    "R5",
    "legal threat",
    Priority.P1,
    "Escalate to the account manager or legal contact before anyone replies.",
    _when(
        r"\b(?:advocaat|advocaten|advocatenkantoor|jurist|juristen|rechtszaak|rechtbank|"
        r"ingebrekestelling|sommatie|dagvaard\w*|deurwaarder|geschillencommissie)\b",
        r"\bnaar\s+de\s+rechter\b|\brechterlijk\w*",
        r"\bjuridisch\w*\s+(?:stappen|actie|maatregelen|traject)\b",
        r"\baansprakelijk\s+(?:stellen|gesteld|houden)\b",
        r"\b(?:schadevergoeding|schadeclaim)\b",
        r"\b(?:lawyer|attorney|solicitor|lawsuit|litigation|legal\s+action|small\s+claims)\b",
        r"\b(?:sue|suing)\b|\bcease\s+and\s+desist\b|\btake\s+(?:you|this)\s+to\s+court\b",
        r"\b(?:anwalt|rechtsanwalt|klage|abmahnung|schadensersatz)\b|\brechtliche\s+schritte\b",
    ),
)

LEAVING = Rule(
    "R6",
    "customer threatening to leave",
    Priority.P2,
    "Contact the customer soon: they are considering leaving.",
    _when(
        r"\bconcurrent(?:en|ie)\b|\b(?:naar|bij)\s+(?:een\s+|de\s+)?concurrent\b",
        r"\b(?:andere|nieuwe)\s+(?:aanbieder|leverancier|software|planningstool|oplossing|partij)\b",
        r"\b(?:we|wij|ik)\s+(?:gaan|stappen)\b(?:\s+\S+){0,3}?\s+over\s+(?:naar|op)\s+"
        r"(?:een\s+)?(?:andere?|concurrent)\b",
        r"\b(?:we|wij|ik)\s+(?:gaan|vertrekken|stoppen)\b(?:\s+\S+){0,2}?\s+(?:weg|ermee)\b",
        r"\bstoppen\s+(?:met|bij)\s+roosterly\b",
        r"\b(?:laatste\s+kans|anders\s+(?:zeggen|stappen|gaan|stoppen)\s+(?:we|wij|ik))\b",
        r"\b(?:competitor|another\s+(?:provider|vendor|supplier)|go\s+elsewhere)\b",
        r"\b(?:leave|switch|move)\b(?:\s+\S+){0,3}?\s+(?:elsewhere|to\s+(?:a\s+)?(?:competitor|"
        r"another\s+(?:provider|tool|app|vendor)|a\s+different\s+(?:provider|tool|app|vendor)))\b",
        r"\b(?:konkurrenz|wettbewerber|anderen\s+anbieter)\b",
        r"\b(?:wir|ich)\s+(?:wechseln|gehen)\b(?:\s+\S+){0,3}?\s+(?:anbieter|weg)\b",
    ),
)

RULES = (REFUND, CANCELLATION, PERSONAL_DATA, SECURITY, LEGAL, LEAVING)

_INJECTION = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(?:ignore|disregard|forget)\b(?:\s+\S+){0,3}?\s+(?:previous|prior|above|earlier|all)"
        r"\b(?:\s+\S+){0,2}?\s+(?:instructions?|rules|prompts?)\b",
        r"\b(?:negeer|vergeet)\b(?:\s+\S+){0,3}?\s+(?:vorige|eerdere|bovenstaande|alle)\b"
        r"(?:\s+\S+){0,2}?\s+(?:instructies?|regels|opdrachten?)\b",
        r"\b(?:ignoriere|vergiss)\w*\b(?:\s+\S+){0,3}?\s+(?:vorherigen|alle|obigen)\b"
        r"(?:\s+\S+){0,2}?\s+(?:anweisungen|regeln)\b",
        r"\b(?:system\s*prompt|systeemprompt|developer\s+mode|jailbreak)\b",
        r"\b(?:you\s+are\s+now|je\s+bent\s+nu|du\s+bist\s+jetzt)\b",
        r"(?:^|\s)(?:system|assistant)\s*:\s",
        r"<\s*/?\s*(?:system|assistant|instructions?|prompt)\s*>",
        r"/practice/reset|/tickets/\w+/(?:reply|handoff|close)",
        # Text addressed to an AI, which customers write to people, not to the support team.
        r"\b(?:ai|ki)[- ]?(?:assistent|assistant|assistentin|agent|bot|model)\b",
        r"\b(?:assistant|assistent)[- ]?(?:model|bot)\b",
        r"\b(?:voor|aan|for|to|fur|an)\s+(?:de\s+|het\s+|the\s+|die\s+|den\s+|dem\s+)?"
        r"(?:ai|ki|chatbot|bot|taalmodel|language\s+model|llm)\b",
        # Orders to set the triage outcome, which only the agent decides.
        r"\b(?:zet|stel|set|change|wijzig|verander|setze)\b(?:\s+\S+){0,3}?\s+"
        r"(?:prioriteit|priority|prioritat|prio)\b",
        r"\b(?:prioriteit|priority|prioritat)\s+(?:op|naar|to|auf|=|:)\s*p[1-4]\b",
        r"\b(?:markeer|mark|markiere)\b(?:\s+\S+){0,3}?\s+(?:als|as)\s+"
        r"(?:opgelost|resolved|gesloten|closed|erledigt|geschlossen|gelost)\b",
    )
)


def find_rule_hits(folded: str) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for rule in RULES:
        for trigger in rule.triggers:
            evidence = trigger.find(folded)
            if evidence is not None:
                hits.append(RuleHit(rule, evidence))
                break
    return hits


def find_injection(folded: str) -> str | None:
    for pattern in _INJECTION:
        match = pattern.search(folded)
        if match:
            return match.group(0)
    return None
