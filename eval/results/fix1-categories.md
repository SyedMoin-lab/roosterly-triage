# Eval: fix 1, category definitions

- run at: 2026-11-16T22:10:52+00:00
- repeats: 3
- models: {'gpt-oss': 'openai/gpt-oss-120b', 'qwen': 'qwen/qwen3.8-27b', 'gemini': 'gemini-3.5-flash-lite'}
- prompt versions: {'triage': 'b34c6ec771be', 'audit': 'b85f08dc9224', 'draft': 'ed91b5d2d410', 'verify': 'c25458510939'}
- faq: a89d6b41c232
- prices as of: 2026-11-16
- compared with baseline: Before -> after on 10 examples: fixed ['E09'], broken none; exact McNemar p = 1.000

| Measure | Result | 95% Wilson interval |
|---|---|---|
| action | 17/30 (57%) | 39% to 73% |
| category | 27/30 (90%) | 74% to 97% |
| priority | 24/30 (80%) | 63% to 90% |
| language | 30/30 (100%) | 89% to 100% |
| all fields | 17/30 (57%) | 39% to 73% |
| unsafe (reply or close on a handoff ticket) | 0 | |
| needless handoffs | 13 | |
| runs that failed (provider outage) | 0 | |
| model calls retried or passed to a backup model | 8 | |
| examples right on every run (pass^k) | 5/10 | |
| replies the judge passed | 5/5 | 57% to 100% |
| list-price cost per 100 tickets | $0.166 | |
| tokens per ticket | 3492 | |

| Example | Label | Decisions | Majority correct |
|---|---|---|---|
| E01 | reply bug P3 en | handoff bug P1 en [MODEL], handoff bug P2 en [MODEL], handoff bug P2 en [MODEL] | no |
| E02 | reply billing P4 nl | handoff billing P3 nl [DISAGREE], handoff billing P2 nl [DISAGREE], handoff billing P2 nl [DISAGREE] | no |
| E03 | handoff billing P2 nl | handoff billing P2 nl [R1], handoff billing P2 nl [R1], handoff billing P2 nl [R1] | yes |
| E04 | reply question P4 nl | reply question P4 nl, reply question P4 nl, reply question P4 nl | yes |
| E05 | reply feature_request P4 nl | handoff feature_request P4 nl [MODEL], handoff feature_request P4 nl [MODEL], handoff feature_request P4 nl [MODEL] | no |
| E06 | handoff bug P2 en | handoff bug P2 en [MODEL], handoff bug P2 en [MODEL], handoff bug P2 en [MODEL] | yes |
| E07 | reply billing P4 nl | handoff question P4 nl [DISAGREE], handoff question P4 nl [DISAGREE], handoff question P4 nl [DISAGREE] | no |
| E08 | close other P4 nl | close other P4 nl [SPAM], close other P4 nl [SPAM], close other P4 nl [SPAM] | yes |
| E09 | handoff other P2 nl | handoff other P2 nl [R3], handoff other P2 nl [R3], handoff other P2 nl [R3] | yes |
| E10 | reply question P4 nl | reply question P4 nl, handoff question P4 nl, reply question P4 nl | yes |
