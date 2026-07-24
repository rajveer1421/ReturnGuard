# ReturnGuard 🛡️

**Agentic AI system for e-commerce return fraud detection**

ReturnGuard is a multi-agent AI pipeline that verifies whether a returned product is genuinely the same item that was delivered — catching substitution, self-inflicted damage, and policy abuse in real time, while giving human reviewers a clear evidence report for anything ambiguous.

---

## The Problem

Return fraud is one of the largest, most underaddressed sources of financial loss in e-commerce. A common pattern: a customer receives the correct product, but returns a different, damaged, or substituted item — and still claims a full refund.

Most platforms handle this with manual inspection at the pickup/warehouse stage. That process is:
- **Slow** — inspection happens well after pickup
- **Inconsistent** — delivery agents aren't trained fraud analysts
- **Late** — refunds are often processed before inspection even happens

There's no widely-used system that captures evidence at delivery, compares it against the returned item, and makes a fast, explainable, confidence-scored decision.

## The Solution

ReturnGuard closes this gap with a two-phase pipeline:

1. **Delivery Phase** — captures multi-angle photos of the product at the moment of delivery and stores a product embedding as ground truth.
2. **Return Phase** — when a return is initiated, a chain of specialized agents validates policy, checks return reason against visual evidence, scores customer risk, compares delivery vs. return images, and outputs a final decision.

Every decision — accept, reject, or escalate — comes with a human-readable evidence report, not a black-box score.

---

## How It Works

### Phase 1 — Delivery
- Capture images from multiple angles (front, back, sides, packaging)
- Generate a single aggregated product embedding from all angles
- Store the embedding + delivery timestamp as the ground-truth reference

### Phase 2 — Return
A pipeline of five agents runs when a return is requested:

| Agent | Role |
|---|---|
| **1. Policy Validation** | Checks return window, category policy, and whether the stated reason is policy-eligible |
| **2. Reason Validation** | Cross-checks the customer's stated reason against visual evidence (e.g. "wrong item" claim vs. a matching product) |
| **3. Fraud Pattern** | Analyzes customer return history to generate a dynamic risk score that adjusts decision thresholds |
| **4. Visual Analysis** | Two-stage check: fast embedding similarity, then a vision-language model for damage detection and evidence captioning on ambiguous cases |
| **5. Decision** | Synthesizes all agent outputs into a final fraud probability and routes to accept / escalate / reject |

**Final routing:**
- `> 90%` fraud probability → automatically reject the return
- `50–90%` → escalate to a human reviewer with full evidence package
- `< 50%` → accept and process the refund

---

## Key Features

- **Multi-angle product fingerprinting** — angle-invariant identity via mean-pooled embeddings, robust to lighting/camera differences
- **Explainable fraud detection** — every decision ships with a natural-language evidence summary
- **Dynamic risk thresholds** — stricter scrutiny for repeat offenders, benefit of the doubt for first-time returners
- **Human-in-the-loop escalation** — ambiguous cases go to reviewers with complete context, not just a score
- **Category-aware analysis** — electronics get flagged for functional testing since internal damage isn't visually detectable
- **Seller protection reports** — shareable proof of decision rationale for dispute resolution

---

## Tech Highlights

- Multi-agent orchestration with stateful workflow and conditional routing
- Two-stage visual analysis: embedding similarity screening + VLM deep analysis for ambiguous cases
- Mean-pooled multi-angle embeddings for product identity verification
- Vision-language model for simultaneous damage detection + caption generation
- Customer behavior modeling for dynamic risk scoring
- Full audit trail for every decision
- Containerized, production-ready deployment

---

## Business Impact

- Reduces fraudulent refunds processed without manual intervention
- Protects third-party seller revenue with documented evidence
- Scales fraud detection without scaling human review teams 1:1
- Produces explainable decisions usable in dispute resolution
- Flags repeat offenders for account-level action

---

## Status

🚧 *Actively in development.* Feedback, issues, and contributions are welcome.

## Author

Built by **Rajveer Gupta** — 3rd year, IIIT Nagpur, Amazon ML Summer School.

---

*ReturnGuard — built to protect sellers, serve genuine customers, and make return fraud economically unviable at scale.*
