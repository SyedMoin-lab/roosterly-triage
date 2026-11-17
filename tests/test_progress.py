import io
import logging

from triage.progress import show_progress, ticket_scope

NO_TICKET = f"{'':<6}"


def test_a_line_shows_the_elapsed_time_the_ticket_and_the_step() -> None:
    stream = io.StringIO()
    with show_progress(stream), ticket_scope("T007"):
        logging.getLogger("triage.pipeline.graph").info("triage (%s): %s", "gpt-oss-120b", "bug")
    assert stream.getvalue() == "  0:00  T007   triage (gpt-oss-120b): bug\n"


def test_an_explicit_ticket_wins_over_the_current_scope() -> None:
    stream = io.StringIO()
    with show_progress(stream), ticket_scope("T001"):
        logging.getLogger("triage.runner").info("posted", extra={"ticket": "T002"})
    assert stream.getvalue() == "  0:00  T002   posted\n"


def test_scopes_nest_and_a_line_outside_any_ticket_has_no_id() -> None:
    stream = io.StringIO()
    logger = logging.getLogger("triage.runner")
    with show_progress(stream):
        logger.info("planning")
        with ticket_scope("T001"):
            with ticket_scope("T002"):
                logger.info("inner")
            logger.info("outer")
    assert stream.getvalue().splitlines() == [
        f"  0:00  {NO_TICKET} planning",
        "  0:00  T002   inner",
        "  0:00  T001   outer",
    ]


def test_only_the_agents_own_lines_are_shown_and_only_while_showing() -> None:
    stream = io.StringIO()
    with show_progress(stream):
        logging.getLogger("httpx").info("HTTP Request: GET https://example.test")
        logging.getLogger("triage.cli").info("shown")
    logging.getLogger("triage.cli").info("not shown")
    assert stream.getvalue().splitlines() == [f"  0:00  {NO_TICKET} shown"]
    assert logging.getLogger("triage").propagate is True
    assert logging.getLogger("triage").level == logging.NOTSET
