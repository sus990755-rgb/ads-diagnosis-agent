"""Tool 3: conversion-tracking health check."""

from __future__ import annotations

import pandas as pd

from src.data_loader import load_data
from src.tools.detect_anomalies import (
    TRACKING_MIN_DAILY_CLICKS,
    TRACKING_MIN_ZERO_CONV_DAYS,
)

# A clicks-per-conversion increase beyond this ratio (vs the previous
# equal-length window) counts as a tracking mutation signal.
RATIO_SPIKE_THRESHOLD = 1.0
# Minimum clicks in the current window before the ratio rule may fire.
MIN_WINDOW_CLICKS = 50


def _zero_conv_streaks(
    s: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> list[dict]:
    """Zero-conversion day streaks (with normal clicks) intersecting [start, end]."""
    zero = (s["conversions"] == 0) & (s["clicks"] >= TRACKING_MIN_DAILY_CLICKS)
    streaks: list[dict] = []
    current: list[pd.Timestamp] = []
    for day in s.index:
        if bool(zero[day]):
            current.append(day)
        else:
            if current:
                streaks.append(current)
            current = []
    if current:
        streaks.append(current)
    return [
        {
            "start_date": str(days[0].date()),
            "end_date": str(days[-1].date()),
            "days": len(days),
            "clicks": int(s["clicks"][days].sum()),
        }
        for days in streaks
        if len(days) >= TRACKING_MIN_ZERO_CONV_DAYS
        and any(start <= d <= end for d in days)
    ]


def get_tracking_status(date_range: list[str]) -> dict:
    """Check conversion-tracking health per campaign over a date range.

    When to call: whenever conversions look suspiciously low or a
    conversion_drop / tracking_loss_suspected anomaly was reported, to
    distinguish a tracking failure from a real performance drop. Also safe
    to call routinely as a sanity check.

    Input constraints:
    - date_range: [start_date, end_date], inclusive, "YYYY-MM-DD".

    Returns a dict with:
    - status: "healthy" | "suspected_broken" — the worst per-campaign
      status. "suspected_broken" means the DATA PATTERN is consistent with
      a tracking outage; it is still a phenomenon, not a proven root cause.
    - campaigns: one entry per campaign active in the range, with:
        status, zero_conversion_streaks (streaks of >=2 zero-conversion
        days with >=20 daily clicks, including dates and clicks),
        clicks_per_conversion {current, previous, change_pct} comparing the
        range against the previous equal-length window (null when the
        previous window is unavailable or has no conversions), and reasons
        (plain-language list of why the campaign was flagged, empty when
        healthy). Campaigns with too little traffic to judge
        (<20 clicks/day on average) get status "healthy" plus a
        "insufficient click volume to judge" reason.
    - note: null, or an explanation when the range has no data at all.

    Signals used (deterministic): zero-conversion streaks, and a
    clicks-per-conversion increase of more than +100% versus the previous
    window with >=50 clicks in the current window.

    This tool never inspects tag/pixel configuration and never proves a
    tracking root cause — it only reports tracking-related data patterns.
    """
    start = pd.to_datetime(date_range[0], format="%Y-%m-%d")
    end = pd.to_datetime(date_range[1], format="%Y-%m-%d")
    if start > end:
        raise ValueError(f"range start {date_range[0]} is after end {date_range[1]}")

    df = load_data()
    in_range = df[(df["date"] >= start) & (df["date"] <= end)]
    if in_range.empty:
        return {
            "status": "healthy",
            "date_range": date_range,
            "campaigns": [],
            "note": (
                f"no data in requested range {date_range[0]}..{date_range[1]}; "
                f"data covers {df['date'].min().date()}..{df['date'].max().date()}"
            ),
        }

    window_days = (end - start).days + 1
    prev_start, prev_end = start - pd.Timedelta(days=window_days), start - pd.Timedelta(days=1)

    daily = df.groupby(["campaign_id", "campaign_name", "date"], as_index=False)[
        ["clicks", "conversions"]
    ].sum()
    all_days = pd.date_range(df["date"].min(), df["date"].max(), freq="D")

    campaigns: list[dict] = []
    for (cid, cname), g in daily.groupby(["campaign_id", "campaign_name"]):
        active = g[(g["date"] >= start) & (g["date"] <= end)]
        if active.empty:
            continue
        s = g.set_index("date").reindex(all_days)

        reasons: list[str] = []
        streaks = _zero_conv_streaks(s, start, end)
        for streak in streaks:
            reasons.append(
                f"conversions=0 for {streak['days']} consecutive days "
                f"({streak['start_date']}..{streak['end_date']}) with "
                f"{streak['clicks']} clicks"
            )

        cur_clicks = float(active["clicks"].sum())
        cur_conv = float(active["conversions"].sum())
        # The ratio rule needs a FULL previous window; a clipped one (e.g. at
        # the data boundary) makes the comparison meaningless.
        prev_window_complete = prev_start >= g["date"].min()
        prev = g[(g["date"] >= prev_start) & (g["date"] <= prev_end)] if prev_window_complete else g.iloc[0:0]
        prev_clicks = float(prev["clicks"].sum())
        prev_conv = float(prev["conversions"].sum())

        cur_cpr = cur_clicks / cur_conv if cur_conv > 0 else None
        prev_cpr = prev_clicks / prev_conv if prev_conv > 0 else None
        change_pct = (
            round((cur_cpr / prev_cpr - 1) * 100, 1)
            if cur_cpr is not None and prev_cpr
            else None
        )
        if (
            cur_clicks >= MIN_WINDOW_CLICKS
            and prev_clicks >= MIN_WINDOW_CLICKS
            and prev_cpr
            and (cur_cpr is None or cur_cpr / prev_cpr - 1 > RATIO_SPIKE_THRESHOLD)
        ):
            reasons.append(
                f"clicks-per-conversion mutated: {round(prev_cpr, 1)} -> "
                f"{round(cur_cpr, 1) if cur_cpr is not None else 'inf'} "
                f"({change_pct if change_pct is not None else '+inf'}%) "
                f"on {int(cur_clicks)} clicks"
            )

        avg_clicks = cur_clicks / max(len(active), 1)
        if not reasons and avg_clicks < TRACKING_MIN_DAILY_CLICKS:
            reasons.append("insufficient click volume to judge")

        campaigns.append({
            "campaign_id": cid,
            "campaign_name": cname,
            "status": "suspected_broken"
            if (streaks or any("clicks-per-conversion" in r for r in reasons))
            else "healthy",
            "zero_conversion_streaks": streaks,
            "clicks_per_conversion": {
                "current": round(cur_cpr, 1) if cur_cpr is not None else None,
                "previous": round(prev_cpr, 1) if prev_cpr is not None else None,
                "change_pct": change_pct,
            },
            "reasons": reasons,
        })

    status = (
        "suspected_broken"
        if any(c["status"] == "suspected_broken" for c in campaigns)
        else "healthy"
    )
    return {
        "status": status,
        "date_range": date_range,
        "campaigns": sorted(campaigns, key=lambda c: c["campaign_id"]),
        "note": None,
    }
