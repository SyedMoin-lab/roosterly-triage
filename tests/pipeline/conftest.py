import pytest

from tests.fakes.models import ScriptedModels
from tests.pipeline.samples import CLEAN_AUDIT, FAQ, GOOD_DRAFT, PASS, proposal
from triage.pipeline.graph import Pipeline
from triage.pipeline.schemas import DraftReply, SafetyAudit, TriageProposal, Verification


@pytest.fixture
def models() -> ScriptedModels:
    scripted = ScriptedModels()
    scripted.respond(TriageProposal, lambda spec: proposal())
    scripted.respond(SafetyAudit, lambda spec: CLEAN_AUDIT)
    scripted.respond(DraftReply, lambda spec: GOOD_DRAFT)
    scripted.respond(Verification, lambda spec: PASS)
    return scripted


@pytest.fixture
def pipeline(models: ScriptedModels) -> Pipeline:
    return Pipeline(models.gateway(), FAQ)
