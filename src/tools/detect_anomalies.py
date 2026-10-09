"""Tool 2: pure-statistics anomaly detection (no LLM involved).

All numbers are computed by deterministic pandas code (engineering red
line 1). The tool reports PHENOMENA only; root-cause interpretation is
left to the LLM.
"""

from __future__ import annotations

import pandas as pd

from src.data_loader import find_data_gaps, load_data

# Rule thresholds (spec section 5, tool 2)
SPIKE_DROP_THRESHOLD = 0.5  # day-over-day cost spike / conversion drop / impression drop
NEG_KEYWORD_MIN_CLICKS = 20
NEG_KEYWORD_MAX_CONVERSIONS = 0
NEG_KEYWORD_MIN_COST_USD = 50.0
TRACKING_MIN_ZERO_CONV_DAYS = 2
TRACKING_MIN_DAILY_CLICKS = 20  # "clicks normal" floor, keeps cold starts out

_METRICS = ["impressions", "clicks", "cost_usd", "conversions"]
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def detect_anomalies(date_range: list[str]) -> dict:
    """Detect anomalous phenomena in a date range with fixed statistical rules.

    When to call: call this FIRST in every diagnosis run, before forming any
    conclusion. It surfaces candidate phenomena; you must still verify and
    interpret them (e.g. with get_performance / get_tracking_status).

    Input constraints:
    - date_range: [start_date, end_date], inclusive, "YYYY-MM-DD".
      Day-over-day comparisons use the full dataset timeline, so the first
      day of the range is still compared against the real previous day;
      only anomalies whose date falls inside the range are reported.

    Returns a dict with:
    - anomalies: list of findings, each with:
        type: one of "cost_spike" (cost +>50% DoD), "conversion_drop"
              (conversions ->50% DoD from a non-zero base),
              "negative_keyword_opportunity" (search term with clicks>=20,
              conversions=0, cumulative cost>$50 inside the range),
              "impression_drop" (impressions -50%+ DoD),
              "tracking_loss_suspected" (conversions=0 for >=2 consecutive
              days while daily clicks>=20), "data_gap" (a campaign has no
              rows on a day inside its own active range);
        entity_key: campaign_id, or the search term for
              negative_keyword_opportunity;
        severity: high | medium | low;
        evidence: the exact numbers behind the finding (previous/current
              values, dates, streak length, etc.).
      Findings are sorted by severity (high first).
    - note: null, or an explanation when the range has no data.

    This tool never explains WHY something happened, never predicts future
    performance, and never recommends actions — it only reports phenomena
    with their evidence numbers.
    """
    start = pd.to_datetime(date_range[0], format="%Y-%m-%d")
    end = pd.to_datetime(date_range[1], format="%Y-%m-%d")
    if start > end:
        raise ValueError(f"range start {date_range[0]} is after end {date_range[1]}")

    df = load_data()
    anomalies: list[dict] = []

    # --- daily campaign-level rules (full timeline for DoD context) ---
    daily = df.groupby(["campaign_id", "date"], as_index=False)[_METRICS].sum()
    all_days = pd.date_range(df["date"].min(), df["date"].max(), freq="D")
    for cid, g in daily.groupby("campaign_id"):
        s = g.set_index("date").reindex(all_days)  # NaN marks missing days
        cost_pct = s["cost_usd"].pct_change(fill_method=None)
        conv_pct = s["conversions"].pct_change(fill_method=None)
        imp_pct = s["impressions"].pct_change(fill_method=None)

        for day in s.index:
            if not (start <= day <= end):
                continue
            prev_day = day - pd.Timedelta(days=1)

            if pd.notna(cost_pct[day]) and cost_pct[day] > SPIKE_DROP_THRESHOLD:
                anomalies.append({
                    "type": "cost_spike",
                    "entity_key": cid,
                    "severity": "high",
                    "evidence": {
                        "date": str(day.date()),
                        "cost_usd": round(s["cost_usd"][day], 2),
                        "prev_date": str(prev_day.date()),
                        "prev_cost_usd": round(s["cost_usd"][prev_day], 2),
                        "change_pct": round(float(cost_pct[day]) * 100, 1),
                    },
                })

            if (
                pd.notna(conv_pct[day])
                and s["conversions"][prev_day] > 0
                and conv_pct[day] < -SPIKE_DROP_THRESHOLD
            ):
                anomalies.append({
                    "type": "conversion_drop",
                    "entity_key": cid,
                    "severity": "high",
                    "evidence": {
                        "date": str(day.date()),
                        "conversions": int(s["conversions"][day]),
                        "prev_date": str(prev_day.date()),
                        "prev_conversions": int(s["conversions"][prev_day]),
                        "change_pct": round(float(conv_pct[day]) * 100, 1),
                    },
                })

            if pd.notna(imp_pct[day]) and imp_pct[day] < -SPIKE_DROP_THRESHOLD:
                anomalies.append({
                    "type": "impression_drop",
                    "entity_key": cid,
                    "severity": "medium",
                    "evidence": {
                        "date": str(day.date()),
                        "impressions": int(s["impressions"][day]),
                        "prev_date": str(prev_day.date()),
                        "prev_impressions": int(s["impressions"][prev_day]),
                        "change_pct": round(float(imp_pct[day]) * 100, 1),
                    },
                })

        # tracking loss: >=2 consecutive zero-conversion days with normal clicks
        zero_conv = (s["conversions"] == 0) & (s["clicks"] >= TRACKING_MIN_DAILY_CLICKS)
        streak_start: pd.Timestamp | None = None
        streak: list[pd.Timestamp] = []

        def flush(streak_days: list[pd.Timestamp]) -> None:
            if len(streak_days) >= TRACKING_MIN_ZERO_CONV_DAYS:
                in_range = [d for d in streak_days if start <= d <= end]
                if in_range:
                    anomalies.append({
                        "type": "tracking_loss_suspected",
                        "entity_key": cid,
                        "severity": "high",
                        "evidence": {
                            "start_date": str(streak_days[0].date()),
                            "end_date": str(streak_days[-1].date()),
                            "zero_conversion_days": len(streak_days),
                            "clicks_on_those_days": int(
                                s["clicks"][streak_days].sum()
                            ),
                        },
                    })

        for day in s.index:
            if bool(zero_conv[day]):
                streak.append(day)
            else:
                flush(streak)
                streak = []
        flush(streak)

    # --- negative keyword opportunities (aggregated over the range) ---
    in_range = df[(df["date"] >= start) & (df["date"] <= end)]
    terms = in_range.groupby(
        ["search_term", "campaign_id", "ad_group_id"], as_index=False
    )[["clicks", "cost_usd", "conversions"]].sum()
    hits = terms[
        (terms["clicks"] >= NEG_KEYWORD_MIN_CLICKS)
        & (terms["conversions"] == NEG_KEYWORD_MAX_CONVERSIONS)
        & (terms["cost_usd"] > NEG_KEYWORD_MIN_COST_USD)
    ]
    for rec in hits.to_dict("records"):
        anomalies.append({
            "type": "negative_keyword_opportunity",
            "entity_key": rec["search_term"],
            "severity": "medium",
            "evidence": {
                "clicks": int(rec["clicks"]),
                "conversions": int(rec["conversions"]),
                "cost_usd": round(rec["cost_usd"], 2),
                "campaign_id": rec["campaign_id"],
                "ad_group_id": rec["ad_group_id"],
            },
        })

    # --- data gaps inside each campaign's active range ---
    for gap in find_data_gaps(df):
        day = pd.to_datetime(gap["missing_date"])
        if start <= day <= end:
            anomalies.append({
                "type": "data_gap",
                "entity_key": gap["campaign_id"],
                "severity": "high",
                "evidence": {
                    "missing_date": gap["missing_date"],
                    "campaign_name": gap["campaign_name"],
                },
            })

    anomalies.sort(key=lambda a: (_SEVERITY_ORDER[a["severity"]], a["type"], a["entity_key"]))
    note = None
    if in_range.empty:
        note = (
            f"no data in requested range {date_range[0]}..{date_range[1]}; "
            f"data covers {df['date'].min().date()}..{df['date'].max().date()}"
        )
    return {
        "date_range": [date_range[0], date_range[1]],
        "anomalies": anomalies,
        "note": note,
    }
