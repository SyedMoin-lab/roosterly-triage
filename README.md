# Roosterly triage agent

Posts one decision per open helpdesk ticket: an FAQ reply in the customer's language, a handoff with an
English note, or a close. [docs/requirements.md](docs/requirements.md) traces every rule in the brief to
code and tests.

## How to run

```bash
docker compose up -d --wait db                       # Postgres 18 + pgvector
poetry install && cp .env.example .env               # then fill in the keys
poetry run python -m triage run --dry-run --limit 3  # decide three tickets, post nothing
poetry run python -m triage eval                     # the 10 labelled examples, 3 runs each
poetry run python scripts/check.py                   # ruff, mypy --strict, 348 tests, as in CI
```

`run` and `eval` print each step as it happens (`--quiet` hides it); `eval --limit 2 --repeats 1` is a
quick demo. Final run: `triage reset --yes`, `triage run`, then `triage lock` to refuse later runs. Exit
code 1 or 3: run again to finish. With Windows Smart App Control: `python -m venv .venv`, then
`python -m poetry`.
The scored run on 17 November posted 30 decisions in 10 minutes; its log is
[logs/20261116T224609Z-7ac058f5.jsonl](logs/20261116T224609Z-7ac058f5.jsonl).

## Decisions

- **Models propose, code decides.** Eight LangGraph steps; rules, redaction, routing and notes are code,
  and every signal can only escalate. A reply needs each question mapped to an FAQ entry, two agreeing
  votes from other model families, a clean safety audit and no P1.
- **Free models, three families:** gpt-oss-120b triages, Gemini 3.5 Flash-Lite and Qwen 3.8 27B vote,
  gpt-oss-safeguard-20b audits the rules, Qwen drafts, Flash-Lite verifies, Prompt Guard 2 screens.
- **Dutch:** read in Dutch, reasoned in English, drafted in the customer's language. Drafts are checked
  without reading Dutch: nine code checks against `faq.md` (language, u or je, menu paths, numbers,
  links, payment data, promises), then a back-translation whose claims must all be in the cited entries.
  Cost: one extra call per reply.
- **A Postgres journal** prevents double answers; pgvector search only logs a cross-check.
- **Open points:** unsure means any rule hit, disagreement or failed check. Price questions get F05;
  plan changes are contract changes (P2). GDPR at least P2, security and legal threats P1, thank-you
  notes a P4 handoff, automatic replies closed.
- **AI tools:** Claude Code as a pair programmer for research, most code, tests and docs. I set the
  constraints, made the product calls and reviewed the work.

## Reliability

- **503:** backoff with jitter, six tries. **429:** one pacer at four calls a second for all workers,
  which all wait out `Retry-After`. **409:** never retried; recorded as answered.
- **Crashes:** `new → deciding → decided → posting → done`, each a compare-and-swap. Decisions are frozen
  before the POST; a lost response is settled by a GET, never resent. 24 crash tests answer every ticket
  exactly once.
- **Outages:** retry, then a backup model. If every model for a step is down, the ticket stays open.
- **Privacy:** IBANs, cards and BSNs are redacted before any model, store or log; no ticket text is
  stored; one redacted JSON line per ticket in `logs/`; keys from the environment.

## Eval and fix

Each labelled example runs three times without posting; gpt-oss-120b judges the replies
([eval/results](eval/results)).

| 30 runs | Unsafe | Needless handoffs | Action | Category | Priority | Language | Judge passed |
|---|---|---|---|---|---|---|---|
| Baseline | 0 | 11 | 19 | 21 | 25 | 30 | 7/7 |
| Fix 1 | 0 | 13 | 17 | **27** | 24 | 30 | 5/5 |
| Fix 2 | 0 | 11 | 19 | 27 | 24 | 30 | 7/7 |

- **Fix 1:** all nine category misses were "question", on billing and GDPR tickets: the prompt never
  defined the categories. Defining them by subject: 21 to 27 of 30 (too few examples to prove it,
  McNemar p = 1.0).
- **Fix 2:** our rule that a price question is not a contract change was missing from the prompts. Price
  questions now pass the votes; the verifier rightly stops two of three replies that omit the total.
- **Cost:** $0.21 per 100 tickets = reported tokens (about 4,000 a ticket) × list prices of 16 November
  per million input/output tokens: gpt-oss-120b $0.35/$0.75, Qwen $0.80/$4.00, Flash-Lite $0.10/$0.40
  (assumed), safeguard $0.075/$0.30. Spent: €0.

## What I would improve

- **Next:** compute totals from FAQ prices, with check G4 redoing the sum; then grow the eval with
  synthetic tickets a person labels, before loosening what counts as an answer (the model still hands
  off a crash that F12 explains). Cloudflare hosting in `cloudflare/` is built, not deployed.
- **Client rules:** define a contract change as a request to change the plan, seats or terms, and say
  that a price question is not one.
