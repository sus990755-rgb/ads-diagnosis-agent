"""Acceptance checks for data/campaigns_30d.csv (spec section 4.2).

Verifies that all 8 injected anomaly patterns exist and are distinguishable.
Usage: python -m scripts.verify_data  (exit code 0 = all patterns verified)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "campaigns_30d.csv"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}: {detail}")
    if not condition:
        FAILURES.append(name)


def daily(df: pd.DataFrame, cid: str) -> pd.DataFrame:
    g = df[df["campaign_id"] == cid].groupby("date")[
        ["impressions", "clicks", "cost_usd", "conversions"]
    ].sum()
    return g.sort_index()


def main() -> int:
    df = pd.read_csv(DATA_PATH)
    expected_cols = {
        "date", "campaign_id", "campaign_name", "ad_group_id", "ad_group_name",
        "search_term", "impressions", "clicks", "cost_usd", "conversions",
        "conversion_value_usd",
    }
    check("schema", set(df.columns) == expected_cols, f"columns={sorted(df.columns)}")
    check(
        "shape",
        df["campaign_id"].nunique() == 5
        and df["ad_group_id"].nunique() == 30
        and df["search_term"].nunique() == 200
        and df["date"].nunique() == 30,
        f"campaigns={df['campaign_id'].nunique()}, ad_groups={df['ad_group_id'].nunique()}, "
        f"terms={df['search_term'].nunique()}, dates={df['date'].nunique()}, rows={len(df)}",
    )

    # Pattern 1: cost spike, C001 on 2026-06-15
    d = daily(df, "C001")
    cost14, cost15 = d.loc["2026-06-14", "cost_usd"], d.loc["2026-06-15", "cost_usd"]
    conv14, conv15 = d.loc["2026-06-14", "conversions"], d.loc["2026-06-15", "conversions"]
    check(
        "P1 cost spike",
        cost15 > 1.5 * cost14 and conv15 < conv14,
        f"C001 cost {cost14:.2f} -> {cost15:.2f} (+{(cost15 / cost14 - 1) * 100:.0f}%), "
        f"conv {conv14} -> {conv15}",
    )

    # Pattern 2: tracking loss, C002 on 2026-06-20/21
    d = daily(df, "C002")
    clicks_ref = d.loc["2026-06-15":"2026-06-19", "clicks"].mean()
    conv_zero = (d.loc[["2026-06-20", "2026-06-21"], "conversions"] == 0).all()
    clicks_normal = all(
        abs(d.loc[day, "clicks"] / clicks_ref - 1) < 0.3
        for day in ["2026-06-20", "2026-06-21"]
    )
    check(
        "P2 tracking loss",
        conv_zero and clicks_normal,
        f"C002 conv=0 on 06-20/21, clicks {d.loc['2026-06-20', 'clicks']}/"
        f"{d.loc['2026-06-21', 'clicks']} vs baseline mean {clicks_ref:.0f}",
    )

    # Pattern 3: cold start, C003 from 2026-06-26, cumulative clicks < 30
    c3 = df[df["campaign_id"] == "C003"]
    total_clicks = int(c3["clicks"].sum())
    check(
        "P3 cold start",
        c3["date"].min() == "2026-06-26" and 0 < total_clicks < 30,
        f"C003 first date={c3['date'].min()}, cumulative clicks={total_clicks}",
    )

    # Pattern 4: negative keyword opportunity
    t = df[df["search_term"] == "free coffee maker download"]
    clicks_sum, conv_sum, cost_sum = (
        int(t["clicks"].sum()),
        int(t["conversions"].sum()),
        float(t["cost_usd"].sum()),
    )
    check(
        "P4 negative keyword",
        clicks_sum >= 20 and conv_sum == 0 and cost_sum > 50,
        f"term clicks={clicks_sum}, conv={conv_sum}, cost=${cost_sum:.2f}, "
        f"campaign={t['campaign_id'].unique().tolist()}",
    )

    # Pattern 5: impression drop, C005 on 2026-06-18
    d = daily(df, "C005")
    imp17, imp18 = d.loc["2026-06-17", "impressions"], d.loc["2026-06-18", "impressions"]
    check(
        "P5 impression drop",
        imp18 < 0.5 * imp17,
        f"C005 impressions {imp17} -> {imp18} ({(imp18 / imp17 - 1) * 100:.0f}%)",
    )

    # Pattern 6: missing data, C004 on 2026-06-22
    c4_dates = set(df.loc[df["campaign_id"] == "C004", "date"])
    expected_dates = {f"2026-06-{day:02d}" for day in range(1, 31)}
    check(
        "P6 missing data",
        "2026-06-22" not in c4_dates and c4_dates == expected_dates - {"2026-06-22"},
        "C004 missing exactly 2026-06-22, other 29 days present",
    )

    # Pattern 7: normal fluctuation control, C005 on 2026-06-01..17
    d = daily(df, "C005").loc["2026-06-01":"2026-06-17"]
    pct = d[["impressions", "clicks", "cost_usd"]].pct_change().dropna().abs()
    conv_zero_days = (d["conversions"] == 0).astype(int)
    max_run = conv_zero_days.groupby((conv_zero_days == 0).cumsum()).sum().max()
    check(
        "P7 normal fluctuation",
        bool((pct <= 0.5).all().all()) and max_run < 2,
        f"C005 06-01..17 max DoD change={pct.max().max() * 100:.1f}%, "
        f"max consecutive zero-conv days={max_run}",
    )

    # Pattern 8: small CPC rise with stable CPA, C002 06-08..14 vs 06-07
    d = daily(df, "C002")
    cpc7 = d.loc["2026-06-07", "cost_usd"] / d.loc["2026-06-07", "clicks"]
    cpc14 = d.loc["2026-06-14", "cost_usd"] / d.loc["2026-06-14", "clicks"]
    ref = d.loc["2026-06-01":"2026-06-07"]
    cpa_ref = ref["cost_usd"].sum() / ref["conversions"].sum()
    cpa14 = d.loc["2026-06-14", "cost_usd"] / d.loc["2026-06-14", "conversions"]
    check(
        "P8 small CPC rise",
        cpc14 > 1.15 * cpc7 and abs(cpa14 / cpa_ref - 1) < 0.10,
        f"C002 CPC ${cpc7:.2f} -> ${cpc14:.2f} (+{(cpc14 / cpc7 - 1) * 100:.0f}%), "
        f"CPA ref ${cpa_ref:.2f} -> ${cpa14:.2f} ({(cpa14 / cpa_ref - 1) * 100:+.1f}%)",
    )

    if FAILURES:
        print(f"FAILED: {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
