════════════════════════════════════════════════════════════════
ARAVALLI CAPITAL - ASSESSMENT
Time: 1-2 weeks
Tools: Claude Code, Codex, any AI (encouraged and expected)
════════════════════════════════════════════════════════════════

BUILD: A Loan Portfolio Investment Analysis Tool

You're evaluating a portfolio of consumer loans for purchase.
Build a tool that helps an investor understand the portfolio
and model returns under different scenarios.

You are not expected to know structured finance. You are
expected to figure it out — using whatever tools you have.
What we're evaluating is how well you use AI, how you
build software, and whether you can produce work that's
correct in a domain that's new to you.

────────────────────────────────────────────────────────────────
DATA SOURCE
────────────────────────────────────────────────────────────────

Use Lending Club's public loan data:
https://www.kaggle.com/datasets/wordsforthewise/lending-club

This contains ~2.2M loans with origination and performance data.

Note: This dataset has known quality issues. Finding and
handling them is part of the assessment. We will be checking
your outputs against validated benchmarks.

────────────────────────────────────────────────────────────────
REQUIREMENTS
────────────────────────────────────────────────────────────────

PART 1: PORTFOLIO ANALYTICS (the finance part)

Ingest and analyze the loan data. Provide:

- Pool stratifications (grade, term, purpose, geography, vintage)
- Credit metrics (WAC, WAM, WALA, avg FICO, avg DTI)
- Performance metrics by vintage:
  - Cumulative default rate (CDR)
  - Cumulative prepayment rate (CPR)
  - Loss severity / recovery rate
- Delinquency transition matrix (roll rates)

If you don't know what these terms mean, that's the point.
Use AI to learn them, define them precisely, implement them,
and verify the output makes sense. We care about whether your
definitions are internally consistent and defensible, not
whether you had them memorized.

────────────────────────────────────────────────────────────────

PART 2: CASH FLOW ENGINE (the engineering part)

Build a cash flow projection model for a subset of the
portfolio.

Given:
- A vintage (e.g. 2018Q1)
- A purchase price (as % of UPB)
- Assumptions for future defaults (CDR) and prepayments (CPR)

The engine should:
- Project monthly cash flows (principal, interest, losses)
- Calculate IRR at the given price
- Solve for the price that achieves a target IRR

Technical requirements:
- Handle the full dataset performantly (2.2M+ loans)
- Structure the code so the cash flow engine is decoupled
  from the data layer and the interface layer
- Include tests — at minimum, validate that your cash flow
  math is correct on a simple known case (e.g. a single
  loan with known payment schedule)
- Design a clean interface (CLI, API, notebook — your call,
  justify the choice)

────────────────────────────────────────────────────────────────

PART 3: SCENARIO COMPARISON & EXTENSIBILITY

Allow the user to run base / stress / upside scenarios and
compare IRR outcomes across them.

Then pick ONE of the following extensions and implement it:

  A. Visualization layer
     Build a dashboard or set of charts that presents the
     portfolio analytics and scenario outputs. Focus on
     what would actually be useful to an investor reviewing
     this portfolio.

  B. Data pipeline hardening
     Make the ingestion robust: schema validation, handling
     of missing/corrupt fields, logging, and the ability to
     swap in a different loan dataset with a similar schema
     without rewriting the core logic.

  C. API / service layer
     Expose the cash flow engine as a REST API or similar
     service so another application could call it
     programmatically. Include documentation.

You may propose a different extension if you can justify it.

Tell us which you chose and why. There's no right answer —
we want to see how you think about prioritization.

────────────────────────────────────────────────────────────────
DELIVERABLES
────────────────────────────────────────────────────────────────

A. Working code repository
   - Runnable with clear setup instructions (README)
   - Modular, readable, documented
   - Include your test suite

B. AI Process Log (1-2 pages, concrete not theoretical)
   - What tools did you use and how did you structure your
     workflow?
   - Where did AI output need correction? What was wrong
     and how did you catch it?
   - What did you verify independently vs. trust? Why?
   - Include at least one concrete example where you caught
     AI getting something wrong.

C. Technical Writeup (2-3 pages):
   - Architecture: how is the code structured and why?
   - Data issues you found and how you handled them
   - Your metric and cash flow definitions (briefly)
   - Performance: how does it handle the full dataset?
   - Trade-offs: what did you cut or simplify and why?
   - What would you build next with another week?

D. Presentation (15 min + 10 min Q&A + 5 min live exercise)
   - Demo the tool
   - Walk through the architecture and key design decisions
   - Walk through the cash flow logic
   - Show your AI workflow: one example of effective AI use
     and one where you had to course-correct
   - Live exercise: we will ask you to modify something and
     walk us through the impact in real time, using your AI
     tools. This could be a code change, an assumption
     change, or both.

────────────────────────────────────────────────────────────────
WHAT WE'RE LOOKING FOR
────────────────────────────────────────────────────────────────

This role involves building with AI tools daily. This
assessment is designed to evaluate that.

Specifically:

1. AI as a multiplier
   Can you use AI to work effectively in a domain you don't
   know, producing output that's actually correct — not just
   plausible?

2. Software quality
   Is the code modular, tested, and something another
   developer could pick up and extend? We read the code,
   not just the output.

3. Verification instinct
   When you get output from an AI tool — code, definitions,
   numbers — how do you decide whether to trust it? We'll
   ask you to show us.

4. Debugging and iteration
   AI will give you broken or subtly wrong code. Your ability
   to diagnose, fix, and improve it matters more than getting
   a clean first pass.

5. Technical communication
   Can you explain what your code does, why you structured it
   the way you did, and defend the choices — including choices
   the AI made that you adopted?

We will ask you to explain, modify, and defend your work live.
If you can't explain why something works, it doesn't count.
────────────────────────────────────────────────────────────────
