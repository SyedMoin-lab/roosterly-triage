# Cost per 100 tickets

Calculated from the token counts that every model call of the scored run reported (journal epoch 5,
17 November, 30 tickets), at the list price of each model on 16 November in US dollars per million
input/output tokens. All calls ran on free tiers, so the actual spend was €0.

| Model | Calls | Input tokens | Output tokens | Price in / out | Cost |
|---|---|---|---|---|---|
| gpt-oss-120b (triage) | 31 | 45,072 | 7,311 | $0.35 / $0.75 | $0.0213 |
| Qwen 3.8 27B (vote, draft) | 23 | 14,220 | 2,232 | $0.80 / $4.00 | $0.0203 |
| Gemini 3.5 Flash-Lite (vote, back-translation) | 20 | 18,566 | 3,411 | $0.30 / $2.50 | $0.0141 |
| gpt-oss-safeguard-20b (rules audit) | 12 | 5,520 | 1,358 | $0.075 / $0.30 | $0.0008 |
| Llama Prompt Guard 2 (injection screen) | 30 | 1,062 | 0 | $0.04 / $0.04 | $0.0000 |
| **Total** | 116 | **84,440** | **14,312** | | **$0.0565** |

$0.0565 / 30 tickets = $0.00188 a ticket, so **$0.19 per 100 tickets** (about 2,800 input and 480
output tokens a ticket).

A ticket that a client rule sends to a person costs two calls (screen, triage); a reply costs seven
(screen, triage, two votes, audit, draft, back-translation). A week of 200 tickets would cost about
$0.38 at these prices.
