"""
examples/api_example.py
------------------------
Example script demonstrating a complete workflow using the Aravalli Capital
loan portfolio analysis API.

Workflow:
  1. Load pool parameters for a vintage range (POST /pool)
  2. Run base/stress/upside scenario comparison (POST /scenarios)
  3. Solve for bid price at a target IRR (POST /solve-price)
  4. Get month-by-month cash flow projection (POST /project)

Prerequisites:
  - API running: uvicorn interface.api:app --reload
  - requests library: pip install requests
"""

import requests

API_URL = "http://localhost:8000"
API_KEY = "dev-key-aravalli"
HEADERS = {"X-API-Key": API_KEY}


def main():
    # -------------------------------------------------------------------------
    # Step 1: Load pool parameters for a vintage range
    # -------------------------------------------------------------------------
    print("=" * 60)
    print("Step 1: Load pool — vintages 2014-2016")
    print("=" * 60)

    r = requests.post(f"{API_URL}/pool", headers=HEADERS, json={
        "vintage_year_start": 2014,
        "vintage_year_end":   2016,
    })
    r.raise_for_status()
    pool = r.json()

    print(f"  Loan count : {pool['loan_count']:,}")
    print(f"  Balance    : ${pool['balance']/1e9:.2f}B")
    print(f"  WAC        : {pool['wac']:.2%}")
    print(f"  WAM        : {pool['wam']} months")
    print(f"  CDR (base) : {pool['cdr']:.2%}")
    print(f"  CPR (base) : {pool['cpr']:.2%}")
    print(f"  Loss sev.  : {pool['loss_severity']:.2%}")

    # -------------------------------------------------------------------------
    # Step 2: Run scenario comparison at 85 cents on the dollar
    # -------------------------------------------------------------------------
    print()
    print("=" * 60)
    print("Step 2: Scenario comparison at 85¢ purchase price")
    print("=" * 60)

    purchase_price = 0.85

    r = requests.post(f"{API_URL}/scenarios", headers=HEADERS, json={
        "balance":        pool["balance"],
        "wac":            pool["wac"],
        "wam":            pool["wam"],
        "purchase_price": purchase_price,
        "target_irrs":    [0.10, 0.12, 0.15],
    })
    r.raise_for_status()
    scenarios = r.json()["scenarios"]

    print(f"  {'Scenario':<10} {'CDR':>8} {'CPR':>8} {'IRR':>10} {'Price@10%':>12} {'Price@12%':>12} {'Price@15%':>12}")
    print(f"  {'-'*74}")
    for s in scenarios:
        prices = s["prices"]
        print(
            f"  {s['scenario']:<10}"
            f" {s['cdr']:>8.2%}"
            f" {s['cpr']:>8.2%}"
            f" {s['irr']:>10.2%}"
            f" {prices.get('10pct', 'N/A'):>12}"
            f" {prices.get('12pct', 'N/A'):>12}"
            f" {prices.get('15pct', 'N/A'):>12}"
        )

    # -------------------------------------------------------------------------
    # Step 3: Solve for bid price at target IRR (base scenario assumptions)
    # -------------------------------------------------------------------------
    print()
    print("=" * 60)
    print("Step 3: What price achieves 12% IRR under base assumptions?")
    print("=" * 60)

    r = requests.post(f"{API_URL}/solve-price", headers=HEADERS, json={
        "balance":       pool["balance"],
        "wac":           pool["wac"],
        "wam":           pool["wam"],
        "cdr":           pool["cdr"],
        "cpr":           pool["cpr"],
        "loss_severity": pool["loss_severity"],
        "target_irr":    0.12,
    })
    r.raise_for_status()
    result = r.json()

    print(f"  Bid price  : {result['price']:.4f} ({result['price']*100:.1f}¢ on the dollar)")
    print(f"  Target IRR : {result['target_irr']:.2%}")
    print(f"  Achieved   : {result['achieved_irr']:.2%}")

    # -------------------------------------------------------------------------
    # Step 4: Get monthly cash flow projection under base assumptions
    # -------------------------------------------------------------------------
    print()
    print("=" * 60)
    print("Step 4: Monthly cash flows — base scenario (first 6 months)")
    print("=" * 60)

    r = requests.post(f"{API_URL}/project", headers=HEADERS, json={
        "balance":       pool["balance"],
        "wac":           pool["wac"],
        "wam":           pool["wam"],
        "cdr":           pool["cdr"],
        "cpr":           pool["cpr"],
        "loss_severity": pool["loss_severity"],
    })
    r.raise_for_status()
    cf = r.json()

    print(f"  {'Month':>5} {'Interest':>14} {'Principal':>14} {'Prepayments':>14} {'Losses':>14} {'Net CF':>14}")
    print(f"  {'-'*77}")
    for i in range(min(6, len(cf["months"]))):
        print(
            f"  {cf['months'][i]:>5}"
            f" ${cf['interest'][i]:>13,.0f}"
            f" ${cf['principal'][i]:>13,.0f}"
            f" ${cf['prepayments'][i]:>13,.0f}"
            f" ${cf['losses'][i]:>13,.0f}"
            f" ${cf['net_cf'][i]:>13,.0f}"
        )

    print()
    print("Full projection covers", len(cf["months"]), "months.")
    print("Done. Interactive docs: http://localhost:8000/docs")


if __name__ == "__main__":
    main()
