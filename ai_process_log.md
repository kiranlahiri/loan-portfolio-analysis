# AI Process Log
## Aravalli Capital — Loan Portfolio Investment Analysis Tool

---

## Workflow

Claude Code (Sonnet 4.6) was the primary tool throughout, used for code generation, domain research, methodology questions, and iterative debugging. The workflow was conversational and iterative rather than prompt-and-accept: each significant output — a metric definition, a formula, a methodology choice — was reviewed before being integrated.

The structured finance domain was entirely new going into this project. AI was used heavily to learn it: understanding CDR/CPR conventions, reading and applying the Moody's Consumer Loan ABS Methodology, and determining what "correct" outputs should look like. This created a specific verification challenge — when you don't know a domain, you can't always tell when an AI answer is subtly wrong. The response was to use known-answer tests wherever possible (if the answer is provably correct in a simple case, the formula is right) and to ask "how would a professional actually derive this?" rather than accepting the first plausible answer.

The general pattern:
- **Use AI to generate first implementations** — data cleaning logic, metric formulas, engine structure
- **Verify against known-answer tests or external references** — Moody's methodology, analytically computable cases
- **Push back when assumptions are implicit** — ask where numbers came from, whether a method is data-driven or assumed

---

## What Was Verified vs. Trusted

**Verified independently:**
- All cash flow math via known-answer tests — the annuity formula, SMM rate convention, and IRR annualization are verified against independently computable cases (see below)
- Metric definitions against Moody's Consumer Loan ABS Methodology (§3, §6.3, §6.4) — CDR definition, timing curve structure, loss severity convention, recovery rate interpretation
- Vintage window selection via PSI statistical analysis rather than judgment — data-driven, not eyeballed
- CDR standard deviation computed from data rather than estimated by eye
- Scenario multipliers documented as industry conventions with explicit rationale — not presented as empirically derived
- DTI > 100 retention decision validated by checking vintage distribution of affected rows — confirmed near-zero presence in 2012–2016 baseline

**Trusted without independent verification:**
- **Moody's Delta method formula** (Appendix 1) — implemented as specified without independently re-deriving the extrapolation math. Moody's is the authoritative source for ABS methodology; the formula is standard industry practice.
- **`numpy_financial.irr()` convergence** — trusted that Newton-Raphson converges correctly for our cash flow structure. We verified the output (IRR = WAC at par) but did not audit the library's implementation.
- **PSI threshold conventions** — the standard thresholds (< 0.10 stable, 0.10–0.25 moderate shift, > 0.25 major shift) are industry convention applied without independently validating them against our specific data distribution.
- **Credibility weighting formula** — applied loan-count weighting for the CDR baseline average. Verified it produced a plausible result (17.55% vs. 17.19% simple average) but did not test alternative weighting schemes.

The dividing line: domain methodology choices and numerical assumptions were verified because errors there are silent and consequential. Established statistical conventions and well-tested libraries were trusted because the cost of re-deriving them from scratch exceeds the risk of error.

---

## Where AI Output Needed Correction

### 1. SMM vs. Compound Interest Convention (`cashflow/engine.py`)

**What AI did:** Implemented the monthly rate conversion for CDR and CPR using the compound interest formula: `(1 + r)^(1/12) - 1`.

**Why it was wrong:** CDR and CPR use the SMM (Single Monthly Mortality) convention: `1 - (1 - r)^(1/12)`. The two formulas are not equivalent. At CDR = 100%, compound gives 5.95%/month — the pool would take 17 months to extinguish. SMM correctly gives 100%/month — the pool extinguishes in one month.

**How it was caught:** Known-answer test. A CPR of 100% should extinguish the pool in a single month — any other result is definitionally wrong. The test failed. Once the failure was traced to the monthly rate formula, the correct SMM convention was identified from the Moody's methodology.

**Fix:** Changed to `1 - (1 - r)^(1/12)` for both CDR and CPR.

---

### 2. IRR Annualization Inconsistency (`cashflow/irr.py`)

**What AI did:** Annualized monthly IRR using the Effective Annual Rate formula: `(1 + monthly_irr)^12 - 1`.

**Why it was wrong:** WAC is applied in the engine as a nominal APR (`wac / 12`). If the input rate uses nominal convention, the output IRR must annualize the same way (`monthly_irr × 12`) for the known-answer test to hold: a pool priced at par with 0% CDR/CPR should return exactly the WAC.

**How it was caught:** Known-answer test. At par price, zero defaults, zero prepayments, IRR must equal WAC (12%). The test returned 12.68% — the EAR of 12% nominal. The discrepancy identified the convention mismatch.

**Fix:** Changed to `monthly_irr × 12`.

This error illustrates a general pattern: AI selected a formula that is technically correct in isolation (EAR is the mathematically "proper" annualization), but internally inconsistent with the convention already established elsewhere in the codebase.

---

### 3. Vintage Selection Without Statistical Validation

**What AI did:** Selected 2013–2016 as the CDR baseline window by judgment — eliminated crisis years and incomplete vintages, and treated the remaining selection as settled.

**Why it was wrong:** No statistical method was used to determine where the borrower population actually changed. The selection could not be defended rigorously: "it looked stable" is not a methodology.

**How it was caught:** Pushing back with the question: "How would a professional actually determine this from scratch?" This exposed that AI had optimized for getting to the next step (building the tool) rather than producing defensible analysis. It had applied engineering instinct — eliminate the obvious outliers and proceed — to a question that required a statistical answer.

**Fix:** Ran Population Stability Index (PSI) across six pool characteristics (FICO, DTI, annual income, revolving utilization, loan purpose, employment length) for all consecutive vintage pairs from 2007–2018. Found a DTI PSI of 0.41 between 2011→2012, indicating a population break — likely reflecting tightened underwriting after the 2008–2011 credit cycle. All PSI values within 2012–2016 were below 0.10 (stable). Baseline window updated to 2012–2016 and BASE_CDR updated from 17.19% (simple average) to 17.55% (loan-count credibility-weighted).

---

### 4. PSI Analysis Implemented Too Narrowly

**What AI did:** Ran PSI across 2007–2016 consecutive vintage pairs to identify the 2011→2012 regime break and validate the 2012–2016 baseline window. Stopped there.

**Why it was wrong:** The CDR timing curve derived from 2012–2016 is applied to extrapolate lifetime CDR for 2017–2018 vintages. This implicitly assumes 2017–2018 borrowers behave like 2012–2016 borrowers — exactly the assumption PSI is designed to test. By not extending PSI to 2016→2017 and 2017→2018 transitions, the core extrapolation assumption was left unvalidated. The same gap also prevented a complete synthetic cohort transition matrix, which requires 2017–2018 loans to cover early age buckets (months 1–24).

**How it was caught:** Asking whether PSI should include 2017–2018 to validate the CDR extrapolation assumption. This revealed a systematic pattern: AI implemented PSI to solve the immediate problem ("find the regime break to justify the vintage window") without considering what else the same analysis was needed for.

**Fix:** Extended PSI to include 2016→2017 and 2017→2018 transitions. All values were below 0.10, confirming population stability and validating both the CDR extrapolation assumption and the synthetic cohort methodology.

---

### 5. Monte Carlo Simulation — Statistical Complexity Without Statistical Foundation

**What AI did:** Added a Monte Carlo IRR distribution simulation, drawing CDR and CPR from independent normal distributions with hardcoded standard deviations (CDR σ = 0.0098, CPR σ = 0.047) calibrated from 2012–2016 vintages. Presented this as a meaningful analytical output alongside the scenario comparison table.

**Why it was wrong:** Multiple compounding issues: CDR and CPR are economically negatively correlated (recession → defaults rise, prepayments fall), but were drawn independently, systematically understating tail risk. The standard deviations were hardcoded regardless of the user's vintage selection — a user filtering to 2007–2010 would receive a simulation calibrated entirely from 2012–2016 benign-cycle data. The calibration itself was derived from only five vintage data points, which is insufficient for reliable distribution estimation. Normal distributions also assume CDR and CPR can take any value, while they are bounded and right-skewed under stress.

**How it was caught:** Asking whether the standard deviation was always computed from 2012–2016 regardless of pool selection. This exposed the hardcoded assumption and triggered a broader review that surfaced all four issues. The underlying pattern: AI added complexity that sounded rigorous — a Monte Carlo with calibrated parameters — without examining whether the inputs were defensible.

**Fix:** Replaced independent draws with a bivariate normal using a correlation of −0.4 (economic convention, explicitly documented). Locked the uncertainty parameters to the 2012–2016 calibration as an explicit design choice rather than a hidden assumption, and added UI text clearly stating what the simulation represents: benign-cycle vintage-to-vintage variation, not full economic cycle uncertainty.

---

## Pattern

Errors 1 and 2 were caught by known-answer tests — the most reliable verification method when domain knowledge is limited. If the answer is provably correct in a simple case, the formula is right.

Errors 3 and 4 share a common root: AI optimizes for forward progress. It produces a plausible answer to the immediate question and moves on, without asking whether the same question requires a more rigorous method (Error 3) or whether the same logic is needed elsewhere (Error 4). These errors are harder to catch because the output looks correct — the vintage window is reasonable, the PSI analysis runs. They require actively asking "is this the right method?" and "what else does this touch?" rather than just checking whether the code works.

Error 5 represents a third failure mode: AI adding analytical complexity that signals rigor without actually providing it. The Monte Carlo looked like a sophisticated output — calibrated parameters, thousands of simulations, a distribution with percentiles. But the inputs were not defensible, and the appearance of precision was misleading. The fix was partly technical (correlation structure) and partly about honest framing: clearly documenting what the simulation does and does not represent. This kind of error is the hardest to catch because the code runs correctly and the output looks reasonable — it requires asking "are these assumptions actually defensible?" rather than just "does this work?"
