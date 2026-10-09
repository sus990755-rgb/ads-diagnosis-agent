"""Simulated Google Ads report data generator (MVP).

Generates 30 days x 5 campaigns x 30 ad groups x 200 unique search terms of
three-level detail (hierarchical: each ad group belongs to exactly one
campaign, each search term belongs to exactly one ad group), then injects the
8 anomaly patterns required by spec section 4.2:

1. Cost spike        - C001 on 2026-06-15: cost +>50% DoD with conversions down
2. Tracking loss     - C002 on 2026-06-20/21: conversions = 0, clicks normal
3. Cold start        - C003 exists only from 2026-06-26, cumulative clicks < 30
4. Negative keyword  - one C004 search term: clicks >= 20, conv = 0, cost > $50
5. Impression drop   - C005 on 2026-06-18: impressions -50%+ DoD
6. Missing data      - C004 has no rows on 2026-06-22
7. Normal fluctuation- C005 on 2026-06-01..17 stays within normal variance
8. Small CPC rise    - C002 on 2026-06-08..14: CPC +3%/day, CPA stable

Reproducible: fixed seed, identical output on every run.
Usage: python -m src.data_generator
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
START_DATE = "2026-06-01"
DAYS = 30

CAMPAIGNS: list[tuple[str, str, float, float]] = [
    # (id, name, mean daily impressions per search term, base CVR)
    ("C001", "Brand_Search", 25.0, 0.08),
    ("C002", "Generic_Search", 90.0, 0.05),
    ("C003", "New_Product_Test", 40.0, 0.05),
    ("C004", "Competitor_Search", 45.0, 0.05),
    ("C005", "Shopping_Plants", 60.0, 0.05),
]

AD_GROUPS_PER_CAMPAIGN = 6  # 30 ad groups in total
TERM_COUNTS_PER_GROUP = [7] * 20 + [6] * 10  # 200 unique search terms in total

NEG_KEYWORD_TERM = "free coffee maker download"
UNIT_PRICE = 52.0

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "campaigns_30d.csv"


def _term_pool() -> list[str]:
    """Build 200 unique search terms from product x modifier x intent combos."""
    products = [
        "running shoes", "yoga mat", "coffee maker", "wireless earbuds",
        "office chair", "water bottle", "backpack", "desk lamp",
        "mechanical keyboard", "standing desk",
    ]
    modifiers = [
        "best", "cheap", "premium", "discount", "lightweight", "portable",
        "ergonomic", "waterproof", "eco friendly", "top rated",
    ]
    intents = ["buy online", "for sale"]
    return [f"{m} {p} {i}" for p in products for m in modifiers for i in intents]


def _entity_frame() -> pd.DataFrame:
    """Assign each search term to exactly one ad group and campaign."""
    ad_groups: list[tuple[str, str, str, str]] = []  # ag_id, ag_name, cid, cname
    for cid, cname, _, _ in CAMPAIGNS:
        for k in range(1, AD_GROUPS_PER_CAMPAIGN + 1):
            ag_id = f"AG{len(ad_groups) + 1:02d}"
            ad_groups.append((ag_id, f"{cname} - AdGroup {k}", cid, cname))

    rows = []
    term_idx = 0
    terms = _term_pool()
    cvr_by_cid = {cid: cvr for cid, _, _, cvr in CAMPAIGNS}
    imp_by_cid = {cid: imp for cid, _, imp, _ in CAMPAIGNS}
    for g, (ag_id, ag_name, cid, cname) in enumerate(ad_groups):
        for _ in range(TERM_COUNTS_PER_GROUP[g]):
            rows.append(
                {
                    "campaign_id": cid,
                    "campaign_name": cname,
                    "ad_group_id": ag_id,
                    "ad_group_name": ag_name,
                    "search_term": terms[term_idx],
                    "_imp_mean": imp_by_cid[cid],
                    "_cvr": cvr_by_cid[cid],
                }
            )
            term_idx += 1
    assert term_idx == 200
    return pd.DataFrame(rows)


def _baseline(entities: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Generate normal-fluctuation baseline metrics for every (date, term)."""
    dates = pd.date_range(START_DATE, periods=DAYS, freq="D").strftime("%Y-%m-%d")
    df = entities.merge(pd.DataFrame({"date": dates}), how="cross")
    n = len(df)

    imp_mean = df["_imp_mean"].to_numpy()
    df["impressions"] = np.maximum(5, np.round(rng.normal(imp_mean, imp_mean * 0.15))).astype(int)
    ctr = np.clip(rng.normal(0.05, 0.008, n), 0.01, 0.12)
    df["clicks"] = np.round(df["impressions"] * ctr).astype(int)
    cpc = np.clip(rng.normal(1.2, 0.12, n), 0.3, 3.0)
    df["cost_usd"] = np.round(df["clicks"] * cpc, 2)

    conv_float = df["clicks"] * df["_cvr"]
    base = np.floor(conv_float)
    df["conversions"] = (base + (rng.random(n) < (conv_float - base))).astype(int)
    unit_price = np.round(rng.normal(UNIT_PRICE, 8, n), 2)
    df["conversion_value_usd"] = np.round(df["conversions"] * unit_price, 2)
    return df


def _set_conversions(df: pd.DataFrame, mask: pd.Series, values: int | np.ndarray) -> None:
    df.loc[mask, "conversions"] = values
    df.loc[mask, "conversion_value_usd"] = np.round(df.loc[mask, "conversions"] * UNIT_PRICE, 2)


def _inject_cost_spike(df: pd.DataFrame) -> None:
    """Pattern 1: C001 on 2026-06-15, cost +>50% DoD and conversions down."""
    m = (df["campaign_id"] == "C001") & (df["date"] == "2026-06-15")
    df.loc[m, "clicks"] = np.round(df.loc[m, "clicks"] * 1.8).astype(int)
    df.loc[m, "cost_usd"] = np.round(df.loc[m, "cost_usd"] * 2.2, 2)
    _set_conversions(df, m, 0)
    first = df.index[m][0]
    _set_conversions(df, df.index == first, 1)


def _inject_tracking_loss(df: pd.DataFrame) -> None:
    """Pattern 2: C002 on 2026-06-20/21, conversions = 0 while clicks stay normal."""
    m = (df["campaign_id"] == "C002") & (df["date"].isin(["2026-06-20", "2026-06-21"]))
    _set_conversions(df, m, 0)


def _inject_cold_start(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Pattern 3: C003 launches on 2026-06-26 with cumulative clicks < 30."""
    df = df[~((df["campaign_id"] == "C003") & (df["date"] < "2026-06-26"))].copy()
    m = df["campaign_id"] == "C003"
    df.loc[m, "impressions"] = rng.integers(2, 7, m.sum())
    df.loc[m, "clicks"] = 0
    lucky = rng.choice(df.index[m].to_numpy(), size=24, replace=False)
    df.loc[lucky, "clicks"] = 1
    df.loc[m, "cost_usd"] = np.round(df.loc[m, "clicks"] * 1.1, 2)
    _set_conversions(df, m, 0)
    return df


def _inject_negative_keyword(df: pd.DataFrame) -> None:
    """Pattern 4: one C004 term with clicks >= 20, conversions = 0, cost > $50."""
    c004_terms = df.loc[df["campaign_id"] == "C004", "search_term"]
    old_term = c004_terms.iloc[0]
    df.loc[df["search_term"] == old_term, "search_term"] = NEG_KEYWORD_TERM
    m = df["search_term"] == NEG_KEYWORD_TERM
    df.loc[m, "impressions"] = 25
    df.loc[m, "clicks"] = 2
    df.loc[m, "cost_usd"] = 5.20
    _set_conversions(df, m, 0)


def _inject_impression_drop(df: pd.DataFrame) -> None:
    """Pattern 5: C005 on 2026-06-18, impressions -70% DoD."""
    m = (df["campaign_id"] == "C005") & (df["date"] == "2026-06-18")
    df.loc[m, "impressions"] = np.round(df.loc[m, "impressions"] * 0.3).astype(int)
    df.loc[m, "clicks"] = np.round(df.loc[m, "clicks"] * 0.3).astype(int)
    df.loc[m, "cost_usd"] = np.round(df.loc[m, "cost_usd"] * 0.3, 2)
    _set_conversions(df, m, np.round(df.loc[m, "conversions"] * 0.3).astype(int))


def _inject_missing_data(df: pd.DataFrame) -> pd.DataFrame:
    """Pattern 6: C004 has no rows at all on 2026-06-22."""
    return df[~((df["campaign_id"] == "C004") & (df["date"] == "2026-06-22"))].copy()


def _inject_small_cpc_rise(df: pd.DataFrame) -> None:
    """Pattern 8: C002 on 2026-06-08..14, CPC +3%/day while conversions are
    anchored to the campaign's own pre-injection CPA (mean over 06-01..07),
    so CPA stays stable (normal fluctuation control)."""
    ref = (df["campaign_id"] == "C002") & (df["date"] < "2026-06-08")
    cpa_ref = df.loc[ref, "cost_usd"].sum() / df.loc[ref, "conversions"].sum()
    for offset in range(1, 8):  # 2026-06-08 .. 2026-06-14
        day = f"2026-06-{7 + offset:02d}"
        mult = 1.03**offset
        m = (df["campaign_id"] == "C002") & (df["date"] == day)
        df.loc[m, "cost_usd"] = np.round(df.loc[m, "cost_usd"] * mult, 2)
        target = int(round(df.loc[m, "cost_usd"].sum() / cpa_ref))
        df.loc[m, "conversions"] = 0
        idx = df.index[m]
        for i in range(target):
            df.loc[idx[i % len(idx)], "conversions"] += 1
        df.loc[m, "conversion_value_usd"] = np.round(df.loc[m, "conversions"] * UNIT_PRICE, 2)


def generate() -> pd.DataFrame:
    """Build the full 30-day dataset with all 8 patterns injected."""
    rng = np.random.default_rng(SEED)
    df = _baseline(_entity_frame(), rng)
    df = _inject_cold_start(df, rng)
    _inject_cost_spike(df)
    _inject_tracking_loss(df)
    _inject_negative_keyword(df)
    _inject_impression_drop(df)
    _inject_small_cpc_rise(df)
    df = _inject_missing_data(df)
    df = df.drop(columns=["_imp_mean", "_cvr"]).sort_values(
        ["date", "campaign_id", "ad_group_id", "search_term"]
    )
    return df.reset_index(drop=True)


def main(output: Path = DEFAULT_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    df = generate()
    df.to_csv(output, index=False)
    print(f"wrote {len(df)} rows -> {output}")
    return output


if __name__ == "__main__":
    main()
