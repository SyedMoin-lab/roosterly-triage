# Roosterly triage agent

Reads Roosterly's open support tickets from the Nordavo helpdesk API and posts exactly one decision per
ticket: reply (answered only from the FAQ), hand off to a human, or close.

> Work in progress. This file follows the five sections the brief asks for and grows with the code.

## How to run

Needs Python 3.12 and [Poetry](https://python-poetry.org/) 2.x.

```bash
docker compose up -d --wait db        # Postgres 18 with pgvector on 127.0.0.1:5434
poetry install                        # installs the exact versions pinned in poetry.lock
cp .env.example .env                  # then fill in the keys
poetry run python -m triage status    # read-only: helpdesk counts and journal state
poetry run python -m triage run --decider drill --dry-run   # decide without posting
poetry run python scripts/check.py    # format, lint, types and tests, as in CI
```

`run` also takes `--limit N` and `--concurrency N`. `reset --yes` re-opens the practice tickets, and
`lock` refuses every live run and reset once the final run is done.

On Windows with Smart App Control on, create the environment first (`python -m venv .venv`) and run Poetry
as `python -m poetry`: Smart App Control blocks the `poetry.exe` launcher and the environments Poetry
creates by itself. Hypothesis is pinned to 6.155.7, the last release without a native extension, for
the same reason.

Every rule from the brief is traced to its code and test in [docs/requirements.md](docs/requirements.md);
the QA scenarios are in [docs/test-plan.md](docs/test-plan.md).

## Decisions

_Written down as the decisions are made._

## Reliability

- **503:** retried with exponential backoff and jitter, up to six attempts; the helpdesk saved nothing.
- **429:** one pacer shared by every worker keeps calls at four a second. A 429 pauses every worker
  for its `Retry-After`.
- **409:** never retried; the ticket is recorded as already handled.
- **Crash:** each ticket moves `new → deciding → decided → posting → done` in Postgres, every step a
  compare-and-swap. The decision is frozen before the POST, and a POST whose outcome is unknown is
  settled by reading the ticket, never by resending. Tests crash the run at four points with one and
  four workers; every re-run answers each ticket exactly once.

## Eval and fix

_To come: the eval on the 10 labelled examples, one fix with before and after numbers, and the cost per
100 tickets._

## What I would improve

_To come._
