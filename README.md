# Roosterly triage agent

Reads Roosterly's open support tickets from the Nordavo helpdesk API and posts exactly one decision per
ticket: reply (answered only from the FAQ), hand off to a human, or close.

> Work in progress. This file follows the five sections the brief asks for and grows with the code.

## How to run

Needs Python 3.12 and [Poetry](https://python-poetry.org/) 2.x.

```bash
poetry install                        # installs the exact versions pinned in poetry.lock
cp .env.example .env                  # then fill in the keys
poetry run python -m triage --help
poetry run python -m pytest
```

On Windows with Smart App Control on, create the environment first (`python -m venv .venv`) and run Poetry
as `python -m poetry`: Smart App Control blocks the `poetry.exe` launcher and the environments Poetry
creates by itself.

## Decisions

_Written down as the decisions are made._

## Reliability

_To come: retries for 503 and 429, never retrying a 409, and crash-safe re-runs._

## Eval and fix

_To come: the eval on the 10 labelled examples, one fix with before and after numbers, and the cost per
100 tickets._

## What I would improve

_To come._
