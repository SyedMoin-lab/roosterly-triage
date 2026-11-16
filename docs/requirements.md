# Requirements and where they are met

Every rule from Nordavo's brief, the API reference, the candidate FAQ and the client's own rules
(`faq.md`), with the design that meets it, the test that proves it, and the phase that delivers it.
✅ means done and tested. The QA scenarios behind the "Proof" column are listed in
[test-plan.md](test-plan.md).

## 1. What the agent does (brief §03)

| ID | Requirement | Design | Proof | Phase |
|---|---|---|---|---|
| A1 | One command runs the agent | `poetry run python -m triage run` | CLI tests; real practice drill of all 30 tickets on 17 November | 2 ✅ drill decider, 4 AI decider |
| A2 | Reads all open tickets | Follows `next_cursor` until it is null; refuses a repeating cursor | `test_open_tickets_follows_the_cursor_to_the_last_page`, `test_a_repeating_cursor_is_a_protocol_violation` | 1 ✅ |
| A3 | Posts one decision per ticket | Write-ahead journal and outbox; a doubt is settled by a GET, never by resending | Crash matrix (invariant I-1); a second real run posted nothing | 2 ✅ |
| A4 | Decides the language: `nl`, `en` or `de` | Model label cross-checked by two language detectors | Language scenarios | 4 |
| A5 | Decides the category from the five allowed | `Category` enum, validated before sending | `test_enum_values_match_the_api_reference` | 1 ✅ |
| A6 | Decides priority P1 to P4 with a one-line reason | Priority definitions in the prompt; minimum priorities enforced in code | Priority scenarios | 3–4 |
| A7 | Reply: a draft in the customer's language | FAQ-grounded draft, then language check G9 | Draft checks | 4 |
| A8 | Handoff: a short note in English | Note built from a template, never by a model | Note tests | 3 |
| A9 | Close: spam and empty tickets only | Close gate in code | Close scenarios | 3 |
| A10 | `draft_reply` only for a reply, `handoff_note` only for a handoff | `Decision` validator | `test_fields_that_do_not_fit_the_action_are_rejected` | 1 ✅ |

## 2. Production behaviour (brief §03 and `api_reference.md`)

| ID | Requirement | Design | Proof | Phase |
|---|---|---|---|---|
| B1 | Random 503s: retry, because nothing was saved | Exponential backoff with full jitter, 6 attempts | `test_a_503_on_a_write_is_retried_and_saved_exactly_once`, `test_random_503s_never_cause_a_lost_or_double_decision` | 1 ✅ |
| B2 | 429 above 5 calls a second: wait `Retry-After` | One shared pacer at 4 calls a second; `Retry-After` (seconds or HTTP date, capped at 60 s) pauses every worker | `test_parallel_workers_stay_under_the_rate_limit`, three `test_a_429_*` tests | 1 ✅ |
| B3 | 409: never retry, a customer never gets two answers | `AlreadyHandledError`; the journal records the ticket as already handled | `test_a_409_is_reported_and_never_retried`, `test_a_ticket_answered_meanwhile_gets_no_second_answer` | 1–2 ✅ |
| B4 | A write whose response is lost | `WriteOutcomeUnknownError`; settled by a GET, never resent blindly | `test_a_lost_response_is_settled_by_reading_not_by_resending` | 1–2 ✅ |
| B5 | Safe to re-run: after a crash it continues where it stopped | Journal states with compare-and-swap; the decision body is frozen before posting | `test_a_crash_at_any_point_never_loses_or_repeats_an_answer` (24 cases) | 2 ✅ |
| B6 | One log line per ticket in `logs/`, without payment details | One JSON line per ticket per run, refused if repeated; no ticket text; redaction of free-text fields | `test_runlog.py`; store scan after every run | 2 ✅ lines, 3 redaction |
| B7 | Keys come from environment variables | pydantic-settings with `SecretStr`; `.env` git-ignored; `.env.example` committed | `test_settings_load_from_environment_variables`, `test_the_key_never_appears_in_repr_or_str` | 1 ✅ |
| B8 | Ticket text is data, not instructions | Ticket IDs come only from the code's loop and are checked before use in a URL; spotlighting, injection screen, escalate-only rules | `test_unsafe_ticket_ids_never_reach_the_network`; red-team scenarios | 1 ✅ IDs, 3–4 |
| B9 | 400, 401, 404 and 422 handled | Typed errors that are never retried | `test_a_wrong_key_stops_at_the_first_401` and siblings | 1 ✅ |

## 3. Working in Dutch (brief §03, candidate FAQ)

| ID | Requirement | Design | Phase |
|---|---|---|---|
| C1 | Replies in the customer's language | Draft in the ticket's language; detectors confirm it | 4 |
| C2 | Handoff notes in English | Template-built note | 3 |
| C3 | Explain the language choice and its cost under Decisions | Read in Dutch, reason in English, draft in the customer's language | 7 |
| C4 | Check a Dutch reply without reading Dutch | Nine deterministic checks against `faq.md`, plus an English back-translation by a model from another family | 3–4 |

## 4. The client's rules (`faq.md`)

| ID | Rule | Design | Phase |
|---|---|---|---|
| D1 | Only answer from the help centre; otherwise a human | Per-question coverage map; reply only if every question maps to an FAQ entry | 4 |
| D2 | Always a human, even if the FAQ seems to cover it: refunds or disputed charges, cancellations and contract changes, GDPR (AVG) requests, possible security incidents, legal threats, customers threatening to leave | Escalate-only keyword rules R1–R6 (Dutch, German, English), then model and safeguard checks | 3 |
| D3 | Never repeat payment details in a reply or a log | Redaction before any model, store or log; check G7 on every draft | 3 |
| D4 | Reply in the customer's language | As C1 | 4 |
| D5 | Notes for the support team in English | As C2 | 3 |

## 5. Measure it and fix one thing (brief §04)

| ID | Requirement | Design | Phase |
|---|---|---|---|
| E1 | Eval on the 10 labelled examples from `GET /examples` | Eval runner with replay | 5 |
| E2 | The tested model never writes labels | Labels come only from `GET /examples`; synthetic cases are labelled by construction | 5 |
| E3 | One thing fixed, with the result before and after | McNemar test on paired results | 5 |
| E4 | Cost per 100 tickets, with the calculation | Provider-reported tokens times dated list prices | 5 |

## 6. The final run and how it is scored (brief §05)

| ID | Requirement | Design | Phase |
|---|---|---|---|
| F1 | Reset, then one run over all 30 tickets | `reset --yes`, `run`, then `lock` so no later run or reset can touch the scored run | 2 ✅ commands, 7 final run |
| F2 | Scored on safety first, then good FAQ replies in the right language, then category, priority and action | The eval weighs failures in the same order | 5 |
| F3 | No answers typed in or copied into code | Answers come from `faq.md` at run time; no ticket text or ticket-specific logic in code; ticket data was profiled for structure only | All |
| F4 | An unsure ticket to a human is never punished; everything to a human is | Unnecessary-handoff rate measured and gated | 5 |
| F5 | Live session on new tickets: explain the code and change it | Small modules, one command, fast tests | All |

## 7. Deliverables (brief §06–07, candidate FAQ)

| ID | Requirement | Owner | Phase |
|---|---|---|---|
| G1 | GitHub repo; private with read access for `nordavo-hiring` | You, before sending | 7 |
| G2 | Code, eval, logs and `.env.example` in the repo | Claude Code | 7 |
| G3 | Commit as you work; the history is read | Every phase | All |
| G4 | README of at most one page with the five headings | Claude Code | 7 |
| G5 | README says how AI tools were used to build it | Claude Code | 7 |
| G6 | Open points decided and written under Decisions | Claude Code | 7 |
| G7 | Free models; a paid model well under €1 in total | Free tiers only | 4 |
| G8 | Reply email: subject "Take-home: full name", one line with the repo link | You | 7 |

## 8. Helpdesk contract (`api_reference.md`, checked read-only against the real API on 17 November)

| ID | Contract | Design | Proof | Phase |
|---|---|---|---|---|
| H1 | Bearer key and `X-Candidate-Email` on every request | Set once on the HTTP client | `test_every_request_carries_the_key_and_the_candidate_email` | 1 ✅ |
| H2 | Always the same email address | `CANDIDATE_EMAIL` setting | Settings tests | 1 ✅ |
| H3 | At most 10 tickets per page; follow `next_cursor` | `PAGE_SIZE = 10` | Pagination tests | 1 ✅ |
| H4 | Errors are `{"error", "message"}`, with `problems` on a 422 | `_error_details` | `test_a_422_carries_the_problems_and_is_not_retried` | 1 ✅ |
| H5 | Examples cannot receive decisions | Examples are only read by the eval | Eval tests | 5 |
| H6 | API not responding: wait a minute, try `GET /status`, then email Nordavo | Runbook in the README | — | 7 |
| H7 | Methods other than GET and POST get an undocumented 405 | Treated as a request error, never retried | Fake helpdesk tests | 1 ✅ |

## Open points, decided and written down

The brief leaves some cases open on purpose. These defaults are checked by the eval and recorded
under Decisions in the README.

- **Unsure** means any rule hit, any disagreement between models or checks, or any failed check.
  An unsure ticket goes to a human, with the reasons in the log line.
- A request to **change plan** is a contract change: handoff, P2. A **question** about plans gets a
  reply from F05.
- **GDPR (AVG)** requests: handoff, at least P2.
- **Possible security incidents** and **legal threats**: handoff, P1 ("a security or legal risk").
- **Thank-you or "solved" messages** are not spam: handoff, P4. **Auto-replies** (out of office):
  close.
