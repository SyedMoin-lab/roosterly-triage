from enum import StrEnum


class TicketState(StrEnum):
    NEW = "new"
    DECIDING = "deciding"
    DECIDED = "decided"
    POSTING = "posting"
    DONE = "done"
    FAILED = "failed"


class Outcome(StrEnum):
    POSTED = "posted"
    CONFIRMED_BY_READ = "confirmed_by_read"
    ALREADY_HANDLED = "already_handled"
    HANDLED_ELSEWHERE = "handled_elsewhere"
    PREVIEWED = "previewed"
    DEFERRED = "deferred"
    UNSETTLED = "unsettled"
    DECIDE_FAILED = "decide_failed"
    REJECTED = "rejected"
    NOT_IN_SET = "not_in_set"


FINISHED = frozenset(
    {
        Outcome.POSTED,
        Outcome.CONFIRMED_BY_READ,
        Outcome.ALREADY_HANDLED,
        Outcome.HANDLED_ELSEWHERE,
        Outcome.PREVIEWED,
    }
)
