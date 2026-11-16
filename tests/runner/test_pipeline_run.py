import uuid
from collections import Counter
from pathlib import Path

from tests.fakes.clock import FakeClock
from tests.fakes.helpdesk import Connect, FakeHelpdesk, make_ticket
from tests.fakes.models import ScriptedModels
from tests.pipeline.samples import (
    CLEAN_AUDIT,
    FAQ,
    GOOD_DRAFT,
    PASS,
    QUESTION,
    REFUND,
    proposal,
)
from triage.journal.states import Outcome
from triage.journal.store import Journal
from triage.pipeline.graph import Pipeline, PipelineDecider
from triage.pipeline.schemas import DraftReply, SafetyAudit, TriageProposal, Verification
from triage.runlog import RunLog
from triage.runner import Runner


async def test_the_ai_pipeline_answers_routes_and_closes_through_the_real_runner(
    connect: Connect, clock: FakeClock, journal: Journal, tmp_path: Path
) -> None:
    fake = FakeHelpdesk(
        [
            make_ticket(1, subject="Nieuwe medewerker", body=QUESTION),
            make_ticket(2, subject="Terugbetaling", body=REFUND),
            make_ticket(3, subject="", body=""),
        ],
        clock=clock,
    )
    models = ScriptedModels()
    models.respond(TriageProposal, lambda spec: proposal())
    models.respond(SafetyAudit, lambda spec: CLEAN_AUDIT)
    models.respond(DraftReply, lambda spec: GOOD_DRAFT)
    models.respond(Verification, lambda spec: PASS)
    decider = PipelineDecider(Pipeline(models.gateway(), FAQ), FAQ)

    run_id = uuid.uuid4()
    async with connect(fake) as helpdesk:
        with RunLog(tmp_path, run_id) as log:
            runner = Runner(
                helpdesk=helpdesk, journal=journal, decider=decider, log=log, run_id=run_id
            )
            summary = await runner.run()

    assert summary.outcomes == Counter({Outcome.POSTED: 3})
    assert {ticket_id: entry["action"] for ticket_id, entry in fake.handled.items()} == {
        "T001": "reply",
        "T002": "handoff",
        "T003": "close",
    }
    assert fake.handled["T001"]["draft_reply"] == GOOD_DRAFT.reply
    assert "R1" in fake.handled["T002"]["handoff_note"]
