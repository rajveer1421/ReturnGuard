# ReturnGuard evaluation

Generated 2026-10-19T14:26:18+00:00 with `gemini-2.5-flash`. Dataset: 48 pairs (18 genuine, 30 fraud) from 6 items. 6 physical items. Genuine returns are simulated re-captures (the delivery photo, edited) except 0 real re-photographs from a separate photo session.

Positive class = fraud. *Flagged* = not auto-accepted (human review or reject).

| Metric | Value | 95% interval |
|---|---|---|
| Precision | 100.0% (28/28) | 87.9% – 100.0% |
| Recall | 93.3% (28/30) | 78.7% – 98.2% |
| F1 | 96.5% | |
| **F0.5** | **98.6%** | |
| False rejection rate (genuine returns flagged) | 0.0% (0/18) | 0.0% – 17.6% |
| Confusion (TP / FP / FN / TN) | 28 / 0 / 2 / 18 | |
| Retake requests (counted as flagged) | 0 | |

Intervals are 95% Wilson score intervals: with this few pairs, a perfect score still has a wide range.

## Ablations

| System | LLM calls / return | Precision | Recall | F0.5 | AUC |
|---|---|---|---|---|---|
| v1: original embedding gate | – | 90.9% | 100.0% | 92.6% | 1.0 |
| v2: local evidence only | 0 | 100.0% | 100.0% | 100.0% | 1.0 |
| v2: full multi-agent pipeline | 0.21 | 100.0% | 93.3% | 98.6% | – |

## Decisions by pair type

| Pair type | ACCEPT | HUMAN_REVIEW | REJECT | RETAKE |
|---|---|---|---|---|
| same_item_recapture | 18 | 0 | 0 | 0 |
| same_model_other_unit | 2 | 0 | 2 | 0 |
| different_category | 0 | 0 | 24 | 0 |
| same_category_other_model | 0 | 0 | 2 | 0 |

## Agentic metrics

- LLM calls per return: **0.21** (v1 made up to 4)
- Decided with no LLM call: **79.2%**
- Structured output valid on first try: 100.0% (after retries: 100.0%), retries: 0
- Identity agent correct: 4/4
- Visual inspector correct: 4/6
- Tokens per return: 717; est. cost per 1,000 returns: $1.05
- Latency per return: mean 3.6 s, max 17.7 s

Routes taken:

- `intake > decide`: 38
- `intake > inspector > decide`: 6
- `intake > identity > decide`: 4
