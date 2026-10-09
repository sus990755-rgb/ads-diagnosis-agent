"""CSV loading and validation for Google Ads report data.

Validation policy:
- Hard failure (DataValidationError with details): file missing, required
  columns missing, unparseable dates or non-numeric/negative metrics, and
  whole days missing across ALL campaigns (data pipeline failure).
- Soft signal: a single campaign missing days inside its own active range is
  a legitimate anomaly (spec pattern 6), reported via find_data_gaps()
  instead of raising.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src import config


class DataValidationError(Exception):
    """Raised when the input CSV fails schema or integrity validation."""


REQUIRED_COLUMNS = {
    "date",
    "campaign_id",
    "campaign_name",
    "ad_group_id",
    "ad_group_name",
    "search_term",
    "impressions",
    "clicks",
    "cost_usd",
    "conversions",
    "conversion_value_usd",
}

METRIC_COLUMNS = [
    "impressions",
    "clicks",
    "cost_usd",
    "conversions",
    "conversion_value_usd",
]


def load_data(path: str | Path | None = None) -> pd.DataFrame:
    """Load and validate the campaign CSV.

    Args:
        path: CSV path; defaults to config.DATA_PATH.

    Returns:
        DataFrame with the 11 spec columns, ``date`` parsed to Timestamp,
        sorted by date/campaign/ad group/search term.

    Raises:
        DataValidationError: file missing, columns missing, unparseable
            dates, non-numeric or negative metrics, or whole missing days.
    """
    path = Path(path) if path is not None else config.DATA_PATH
    if not path.exists():
        raise DataValidationError(f"data file not found: {path}")

    df = pd.read_csv(path)

    missing_cols = REQUIRED_COLUMNS - set(df.columns)
    if missing_cols:
        raise DataValidationError(
            f"missing required columns: {sorted(missing_cols)}; "
            f"got: {sorted(df.columns)}"
        )

    try:
        df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d")
    except ValueError as exc:
        raise DataValidationError(f"unparseable date values: {exc}") from exc

    for col in METRIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        bad = df[col].isna().sum()
        if bad:
            raise DataValidationError(
                f"column '{col}' has {bad} non-numeric value(s)"
            )
        negative = (df[col] < 0).sum()
        if negative:
            raise DataValidationError(
                f"column '{col}' has {negative} negative value(s)"
            )

    full_range = pd.date_range(df["date"].min(), df["date"].max(), freq="D")
    missing_days = full_range.difference(df["date"].unique())
    if len(missing_days):
        days = [str(d.date()) for d in missing_days]
        raise DataValidationError(
            f"whole day(s) missing from all campaigns: {days}"
        )

    return df.sort_values(
        ["date", "campaign_id", "ad_group_id", "search_term"]
    ).reset_index(drop=True)


def find_data_gaps(df: pd.DataFrame) -> list[dict]:
    """Find per-campaign missing days inside each campaign's active range.

    A campaign's active range spans its own first to last date in the data,
    so a late-launched (cold-start) campaign is not flagged for days before
    its launch.

    Args:
        df: validated DataFrame returned by load_data().

    Returns:
        List of {"campaign_id", "campaign_name", "missing_date"} entries,
        ordered by campaign then date; empty when there are no gaps.
    """
    gaps: list[dict] = []
    for (cid, cname), g in df.groupby(["campaign_id", "campaign_name"]):
        expected = pd.date_range(g["date"].min(), g["date"].max(), freq="D")
        for day in expected.difference(g["date"].unique()):
            gaps.append(
                {
                    "campaign_id": cid,
                    "campaign_name": cname,
                    "missing_date": str(day.date()),
                }
            )
    return gaps
