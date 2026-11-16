# Eval: baseline

- run at: 2026-11-16T21:42:44+00:00
- repeats: 3
- models: {'gpt-oss': 'openai/gpt-oss-120b', 'qwen': 'qwen/qwen3.8-27b', 'gemini': 'gemini-3.5-flash-lite'}
- prompt versions: {'triage': '6f561308708a', 'audit': 'b85f08dc9224', 'draft': 'ed91b5d2d410', 'verify': 'c25458510939'}
- faq: a89d6b41c232
- prices as of: 2026-11-16

| Measure | Result | 95% Wilson interval |
|---|---|---|
| action | 19/30 (63%) | 46% to 78% |
| category | 21/30 (70%) | 52% to 83% |
| priority | 25/30 (83%) | 66% to 93% |
| language | 30/30 (100%) | 89% to 100% |
| all fields | 15/30 (50%) | 33% to 67% |
| unsafe (reply or close on a handoff ticket) | 0 | |
| needless handoffs | 11 | |
| runs that failed (provider outage) | 0 | |
| examples right on every run (pass^k) | 5/10 | |
| replies the judge passed | 7/7 | 65% to 100% |
| list-price cost per 100 tickets | $0.170 | |
| tokens per ticket | 3365 | |

| Example | Label | Decisions | Majority correct |
|---|---|---|---|
| E01 | reply bug P3 en | handoff bug P2 en [MODEL], handoff bug P2 en [MODEL], handoff bug P2 en [MODEL] | no |
| E02 | reply billing P4 nl | reply question P3 nl, handoff question P3 nl [DISAGREE], handoff question P4 nl [DISAGREE] | no |
| E03 | handoff billing P2 nl | handoff billing P2 nl [R1], handoff billing P2 nl [R1], handoff billing P2 nl [R1] | yes |
| E04 | reply question P4 nl | reply question P4 nl, reply question P4 nl, reply question P4 nl | yes |
| E05 | reply feature_request P4 nl | handoff feature_request P4 nl [MODEL], handoff feature_request P4 nl [MODEL], handoff feature_request P4 nl [MODEL] | no |
| E06 | handoff bug P2 en | handoff bug P2 en [MODEL], handoff bug P2 en [MODEL], handoff bug P2 en [MODEL] | yes |
| E07 | reply billing P4 nl | handoff question P4 nl [DISAGREE], handoff question P4 nl [AUDIT], handoff question P4 nl [DISAGREE] | no |
| E08 | close other P4 nl | close other P4 nl [SPAM], close other P4 nl [SPAM], close other P4 nl [SPAM] | yes |
| E09 | handoff other P2 nl | handoff question P2 nl [R3], handoff question P2 nl [R3], handoff question P2 nl [R3] | no |
| E10 | reply question P4 nl | reply question P4 nl, reply question P4 nl, reply question P4 nl | yes |
