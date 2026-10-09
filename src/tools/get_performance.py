"""Tool 1: aggregated performance metrics over a date range."""

from __future__ import annotations

import pandas as pd

from src.data_loader import load_data

LEVEL_COLUMNS = {
    "campaign": "campaign_id",
    "ad_group": "ad_group_id",
    "search_term": "search_term",
}
NAME_COLUMNS = {"campaign": "campaign_name", "ad_group": "ad_group_name"}

_METRICS = ["impressions", "clicks", "cost_usd", "conversions", "conversion_value_usd"]

_df_cache: pd.DataFrame | None = None


def _df() -> pd.DataFrame:
    global _df_cache
    if _df_cache is None:
        _df_cache = load_data()
    return _df_cache


def _ratio(num: float, den: float, digits: int) -> float | None:
    return round(num / den, digits) if den else None


def get_performance(
    start_date: str,
    end_date: str,
    level: str = "campaign",
    include_daily: bool = False,
) -> dict:
    """Get aggregated performance metrics per entity over a date range.

    When to call: use this to pull performance numbers BEFORE making any
    diagnosis claim, and to drill down from campaign to ad group or search
    term level when an anomaly needs localization.

    Input constraints:
    - start_date / end_date: inclusive, format "YYYY-MM-DD"; start must not
      be after end. The range is clipped to the available data range.
    - level: one of "campaign" (default), "ad_group", "search_term".
    - include_daily: set True only when day-by-day detail is required.

    Returns a dict with:
    - rows: one entry per entity with keys: key (entity id or search term),
      name (campaign/ad group name; omitted at search_term level),
      impressions, clicks, cost_usd, conversions, conversion_value_usd,
      ctr, cpc, cpa, roas. Derived ratios are null when the denominator is
      0. Rows are sorted by cost_usd descending.
    - note: null, or an explanation when the requested range was clipped or
      has no data at all (rows is then an empty list).
    - daily breakdown is NOT returned unless include_daily=True (then each
      row gains a "daily" list of per-date raw metrics).

    This tool never returns per-row CSV detail, never modifies data, and
    never derives trends or judgments — it only aggregates.
    """
    if level not in LEVEL_COLUMNS:
        raise ValueError(
            f"invalid level {level!r}; must be one of {sorted(LEVEL_COLUMNS)}"
        )
    start = pd.to_datetime(start_date, format="%Y-%m-%d")
    end = pd.to_datetime(end_date, format="%Y-%m-%d")
    if start > end:
        raise ValueError(f"start_date {start_date} is after end_date {end_date}")

    df = _df()
    data_min, data_max = df["date"].min(), df["date"].max()

    note: str | None = None
    clipped_start, clipped_end = max(start, data_min), min(end, data_max)
    if clipped_start > clipped_end:
        return {
            "level": level,
            "start_date": start_date,
            "end_date": end_date,
            "rows": [],
            "note": (
                f"no data in requested range {start_date}..{end_date}; "
                f"data covers {data_min.date()}..{data_max.date()}"
            ),
        }
    if (clipped_start, clipped_end) != (start, end):
        note = (
            f"range clipped to {clipped_start.date()}..{clipped_end.date()}; "
            f"data covers {data_min.date()}..{data_max.date()}"
        )

    subset = df[(df["date"] >= clipped_start) & (df["date"] <= clipped_end)]

    key_col = LEVEL_COLUMNS[level]
    group_cols = [key_col] + ([NAME_COLUMNS[level]] if level in NAME_COLUMNS else [])
    agg = subset.groupby(group_cols, as_index=False)[_METRICS].sum()

    rows: list[dict] = []
    for rec in agg.to_dict("records"):
        row = {
            "key": rec[key_col],
            "impressions": int(rec["impressions"]),
            "clicks": int(rec["clicks"]),
            "cost_usd": round(rec["cost_usd"], 2),
            "conversions": int(rec["conversions"]),
            "conversion_value_usd": round(rec["conversion_value_usd"], 2),
            "ctr": _ratio(rec["clicks"], rec["impressions"], 4),
            "cpc": _ratio(rec["cost_usd"], rec["clicks"], 2),
            "cpa": _ratio(rec["cost_usd"], rec["conversions"], 2),
            "roas": _ratio(rec["conversion_value_usd"], rec["cost_usd"], 2),
        }
        if level in NAME_COLUMNS:
            row["name"] = rec[NAME_COLUMNS[level]]
        if include_daily:
            daily = (
                subset[subset[key_col] == rec[key_col]]
                .groupby("date", as_index=False)[_METRICS]
                .sum()
                .sort_values("date")
            )
            row["daily"] = [
                {
                    "date": str(d["date"].date()),
                    "impressions": int(d["impressions"]),
                    "clicks": int(d["clicks"]),
                    "cost_usd": round(d["cost_usd"], 2),
                    "conversions": int(d["conversions"]),
                    "conversion_value_usd": round(d["conversion_value_usd"], 2),
                }
                for d in daily.to_dict("records")
            ]
        rows.append(row)

    rows.sort(key=lambda r: r["cost_usd"], reverse=True)
    return {
        "level": level,
        "start_date": str(clipped_start.date()),
        "end_date": str(clipped_end.date()),
        "rows": rows,
        "note": note,
    }
