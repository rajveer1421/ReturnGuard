# Precision stress test (local stage, no LLM)

Generated 2026-10-20T00:39:39. Each condition changes only how the **returned** item is photographed; delivery photos are untouched. Per condition: 8 genuine + 56 fraud pairs (8 items). *Flagged* = not auto-accepted by the local stage (review, reject or retake).

Across 36 conditions, 54 of 288 genuine returns were flagged by the local stage: 2 fast-rejected outright (a hard false rejection no LLM would undo), 78 would be sent to Gemini, 4 asked for a retake; 204 were fast-accepted.

| Augmentation | Level | Genuine flagged | Fast-reject | To Gemini | Retake | Precision (95% interval) | Recall | Implied precision at 15% fraud |
|---|---|---|---|---|---|---|---|---|
| No change (same photo, re-encoded) | none | 0/8 | 0 | 0 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Rotated | mild | 1/8 | 0 | 2 | 0 | 98.2% (91–100%) | 100.0% | 58.5% |
| Rotated | strong | 2/8 | 1 | 2 | 0 | 96.5% (88–99%) | 100.0% | 41.4% |
| Viewpoint tilt | mild | 0/8 | 0 | 1 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Viewpoint tilt | strong | 2/8 | 0 | 2 | 0 | 96.5% (88–99%) | 100.0% | 41.4% |
| Photographed from further away | mild | 1/8 | 0 | 1 | 0 | 98.2% (91–100%) | 100.0% | 58.5% |
| Photographed from further away | strong | 6/8 | 1 | 5 | 0 | 90.3% (80–95%) | 100.0% | 19.1% |
| Partly out of frame | mild | 0/8 | 0 | 0 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Partly out of frame | strong | 1/8 | 0 | 1 | 0 | 98.2% (91–100%) | 100.0% | 58.5% |
| Darker room | mild | 0/8 | 0 | 0 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Darker room | strong | 0/8 | 0 | 2 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Overexposed | mild | 0/8 | 0 | 0 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Overexposed | strong | 1/8 | 0 | 2 | 0 | 98.2% (91–100%) | 100.0% | 58.5% |
| Warm (yellow) light | mild | 4/8 | 0 | 7 | 0 | 93.3% (84–97%) | 100.0% | 26.1% |
| Warm (yellow) light | strong | 8/8 | 0 | 8 | 0 | 87.5% (77–94%) | 100.0% | 15.0% |
| Cool (blue) light | mild | 3/8 | 0 | 7 | 0 | 94.9% (86–98%) | 100.0% | 32.0% |
| Cool (blue) light | strong | 8/8 | 0 | 8 | 0 | 87.5% (77–94%) | 100.0% | 15.0% |
| Low contrast / haze | mild | 0/8 | 0 | 0 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Low contrast / haze | strong | 1/8 | 0 | 2 | 0 | 98.2% (91–100%) | 100.0% | 58.5% |
| Shadow across the item | mild | 0/8 | 0 | 0 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Shadow across the item | strong | 0/8 | 0 | 0 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Glare / reflection | mild | 0/8 | 0 | 0 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Glare / reflection | strong | 0/8 | 0 | 1 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Out of focus | mild | 0/8 | 0 | 0 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Out of focus | strong | 4/8 | 0 | 0 | 4 | 93.3% (84–97%) | 100.0% | 26.1% |
| Camera shake | mild | 0/8 | 0 | 0 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Camera shake | strong | 0/8 | 0 | 6 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Sensor noise (low light) | mild | 0/8 | 0 | 0 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Sensor noise (low light) | strong | 1/8 | 0 | 2 | 0 | 98.2% (91–100%) | 100.0% | 58.5% |
| Heavy JPEG compression | mild | 0/8 | 0 | 0 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Heavy JPEG compression | strong | 8/8 | 0 | 8 | 0 | 87.5% (77–94%) | 100.0% | 15.0% |
| Low resolution | mild | 0/8 | 0 | 0 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Low resolution | strong | 0/8 | 0 | 1 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Finger covering part | mild | 1/8 | 0 | 5 | 0 | 98.2% (91–100%) | 100.0% | 58.5% |
| Finger covering part | strong | 2/8 | 0 | 5 | 0 | 96.5% (88–99%) | 100.0% | 41.4% |
| Different background | mild | 0/8 | 0 | 0 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |
| Different background | strong | 0/8 | 0 | 0 | 0 | 100.0% (94–100%) | 100.0% | 100.0% |

## Real second photo session (headphones)

| Item | Local decision | Screen | Shape | Colour ΔE |
|---|---|---|---|---|
| headphones_blue | HUMAN_REVIEW | ambiguous | 0.8345 | 2.87 |
| headphones_black | ACCEPT | ambiguous | 0.9285 | 0.0 |

*Implied precision at 15% fraud* re-weights the measured false-flag rate and recall to a realistic share of fraudulent returns (Appriss Retail 2024: 15.14%), because precision depends on how common fraud is.
