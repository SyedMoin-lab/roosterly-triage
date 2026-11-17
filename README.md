# Roosterly triage agent

One command reads every open helpdesk ticket and posts one decision: an FAQ reply in the customer's
language, a handoff with an English note, or a close. [docs/requirements.md](docs/requirements.md)
maps the brief to code and tests.

## How to run

```bash
git clone https://github.com/SyedMoin-lab/roosterly-triage && cd roosterly-triage
docker compose up -d --wait db                       # Postgres 18 + pgvector
poetry install && cp .env.example .env               # then fill in the keys
poetry run python -m triage run --dry-run --limit 3  # decide three tickets, post nothing
poetry run python -m triage run                      # decide and post every open ticket
poetry run python -m triage eval                     # the 10 labelled examples, 3 runs each
poetry run python scripts/check.py                   # ruff, mypy --strict, 386 tests, as in CI
```

Steps show live (`--quiet` hides them). Final run: `python -m triage reset --yes`, `run`, then `lock`
(refuses later runs until `unlock`); exit code 1 or 3: run again. Scored run: 17 November, commit
`cba7252`, 30 decisions in 10 minutes ([log](logs/20261117T082339Z-98cc06d5.jsonl)).

## Decisions

1. **Models propose, code decides.** Client rules, redaction, routing and handoff notes are code; no
   model can move a ticket away from a person. A reply needs every question mapped to an FAQ entry,
   two agreeing votes from other model families, a clean audit and no P1, because a wrong answer
   reaches a real customer.
2. **Dutch in, English reasoning, the customer's language out.** Translating first would let one slip
   decide safety. Replies are checked without reading Dutch: nine code checks against `faq.md` (every
   sentence's language, u or je, menu paths, numbers, links, payment data, promises), then a
   back-translation whose every claim must be in the cited entries. Cost: one extra call per reply.
3. **Free models from three families:** gpt-oss-120b triages, Gemini 3.5 Flash-Lite and Qwen 3.8 27B
   vote, gpt-oss-safeguard-20b audits the rules, Qwen drafts, Flash-Lite back-translates, Prompt
   Guard 2 screens. Another family catches a blind spot, at €0; faster models on Vercel's free credit
   measured worse ([results](eval/results/vercel-models.md)).

- **Assumptions:** unsure means any rule hit, disagreement or failed check. Price questions get F05;
  plan changes are contract changes (P2). GDPR at least P2, security and legal threats P1. Thank-you
  notes go to a person; automatic replies close only when every model agrees; a ticket that orders
  its own priority goes to a person at P2 (or a rule's higher floor).
- **AI tools:** Claude Code as pair programmer (research, most code, tests, docs) and as independent
  reviewers against the brief. I set the constraints, made the product calls and reviewed the work.

## Reliability

- **503:** backoff with jitter, six tries. **429:** one pacer at four calls a second for all workers,
  which all wait out `Retry-After`. **409:** never retried; recorded as answered.
- **Crashes:** `new → deciding → decided → posting → done`, each a compare-and-swap in Postgres. The
  decision is frozen before the POST; after a lost response a GET decides, and it is resent only if
  the ticket is still open. 24 crash tests answer every ticket exactly once.
- **Outages:** retry, then a backup model (the audit has none); if a step has no model left, the
  ticket stays open for the next run.
- **Security:** ticket text is data, tagged in prompts and screened by Prompt Guard 2 and code
  patterns. IBANs, cards (with CVC and expiry) and BSNs are hidden before any model, store or log; the
  log holds no ticket text; keys come from the environment.

## Eval and fix

Each labelled example runs three times without posting; gpt-oss-120b judges the replies
([eval/results](eval/results)). Language was right in every run.

| 30 runs | Unsafe | Needless handoffs | Action | Category | Priority | Judge passed |
|---|---|---|---|---|---|---|
| Baseline | 0 | 11 | 19 | 21 | 25 | 7/7 |
| Fix 1 | 0 | 13 | 17 | **27** | 24 | 5/5 |
| Fix 2 | 0 | 11 | 19 | 27 | 24 | 7/7 |

- **Fix 1:** all nine category misses were "question", on billing and GDPR tickets: the prompt never
  defined the categories. Defining them by subject: 21 to 27 of 30 (too few examples to prove it,
  McNemar p = 1.0).
- **Fix 2:** the rule that a price question is not a contract change was missing from the prompts.
  Price questions now pass the votes; the verifier rightly stops replies that leave out the total.
- **Review fixes**, each with a test: a planted note set T030's priority (fixed before the scored run);
  numbers followed by words escaped redaction; a keyword could close a ticket; English sentences slipped
  into Dutch replies. On the practice tickets these later fixes only raise T015 and T026 (GDPR) to P2.
- **Cost:** $0.19 per 100 tickets at list prices: the 30 scored tickets used 84,440 input and 14,312
  output tokens, $0.0565 at each model's price ([arithmetic per model](docs/cost.md)). Spent: €0.

## What I would improve

- **Next:** most needless handoffs come from one vote or the back-translation check disagreeing, and
  ideas still go to a person although F10 answers them. Grow the eval with synthetic tickets a person
  labels before loosening either; compute totals from FAQ prices, with check G4 redoing the sum.
- **Client rules:** define a contract change as a request to change the plan, seats or terms, and say
  that a price question is not one.
