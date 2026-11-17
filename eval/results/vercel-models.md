# Eval: vercel-models

- run at: 2026-11-17T07:23:49+00:00
- repeats: 3
- models: {'triage': ['openai/gpt-5-mini via vercel', 'openai/gpt-oss-120b via vercel'], 'vote': ['alibaba/qwen3.7-flash via vercel', 'zai/glm-4.7-flash via vercel', 'meta/llama-4-scout via vercel'], 'audit': ['openai/gpt-oss-safeguard-20b via vercel', 'openai/gpt-oss-safeguard-120b via vercel'], 'draft': ['openai/gpt-oss-120b via vercel', 'openai/gpt-5-mini via vercel'], 'verify': ['deepseek/deepseek-v3.1 via vercel', 'meta/llama-4-scout via vercel', 'alibaba/qwen3.7-flash via vercel'], 'judge': ['alibaba/qwen3.7-flash via vercel', 'meta/llama-4-scout via vercel']}
- prompt versions: {'triage': '34c30d663312', 'audit': 'e8a022d4ad8b', 'draft': 'f15efb076eb8', 'verify': 'c25458510939'}
- faq: a89d6b41c232
- prices as of: 2026-11-17
- compared with fix2-plan-questions: Before -> after on 10 examples: fixed ['E07'], broken ['E08', 'E10']; exact McNemar p = 1.000

| Measure | Result | 95% Wilson interval |
|---|---|---|
| action | 14/30 (47%) | 30% to 64% |
| category | 24/30 (80%) | 63% to 90% |
| priority | 22/30 (73%) | 56% to 86% |
| language | 26/30 (87%) | 70% to 95% |
| all fields | 13/30 (43%) | 27% to 61% |
| unsafe (reply or close on a handoff ticket) | 0 | |
| needless handoffs | 12 | |
| runs that failed (provider outage) | 4 | |
| model calls retried or passed to a backup model | 4 | |
| examples right on every run (pass^k) | 2/10 | |
| replies the judge passed | 5/5 | 57% to 100% |
| list-price cost per 100 tickets | $0.161 | |
| tokens per ticket | 5006 | |

| Example | Label | Decisions | Majority correct |
|---|---|---|---|
| E01 | reply bug P3 en | handoff question P4 en [CHECKS], handoff bug P3 en [DISAGREE], handoff bug P3 en [CHECKS] | no |
| E02 | reply billing P4 nl | handoff question P4 nl [AUDIT], handoff billing P2 nl [DISAGREE], handoff billing P2 nl [MODEL] | no |
| E03 | handoff billing P2 nl | handoff billing P2 nl [R1], handoff billing P2 nl [R1], handoff billing P2 nl [R1] | yes |
| E04 | reply question P4 nl | reply question P4 nl, error, reply question P4 nl | yes |
| E05 | reply feature_request P4 nl | handoff feature_request P4 nl [DISAGREE], handoff feature_request P4 nl [DISAGREE], handoff feature_request P4 nl [DISAGREE] | no |
| E06 | handoff bug P2 en | handoff bug P2 en [MODEL], handoff bug P2 en [MODEL], handoff bug P2 en [MODEL] | yes |
| E07 | reply billing P4 nl | handoff billing P4 nl [VERIFY], reply billing P4 nl, reply billing P4 nl | yes |
| E08 | close other P4 nl | error, handoff other P4 nl [DISAGREE], handoff other P4 nl [DISAGREE] | no |
| E09 | handoff other P2 nl | handoff other P1 nl [R3], handoff other P2 nl [R3], handoff other P2 nl [R3] | yes |
| E10 | reply question P4 nl | error, error, reply question P4 nl | no |
