"""Unit tests for the agent tools (spec section 5)."""

from __future__ import annotations

import pytest

from src import config
from src.data_generator import main as generate_data
from src.data_loader import load_data
from src.tools.get_performance import get_performance


@pytest.fixture(scope="session", autouse=True)
def ensure_data() -> None:
    """The CSV is gitignored; generate it deterministically if absent."""
    if not config.DATA_PATH.exists():
        generate_data()


# ---- Tool 1: get_performance ----


def test_campaign_level_aggregation() -> None:
    """Default level aggregates per campaign with correct sums and ratios."""
    res = get_performance("2026-06-01", "2026-06-30")
    assert res["note"] is None
    assert len(res["rows"]) == 5

    df = load_data()
    c001 = df[df["campaign_id"] == "C001"]
    row = next(r for r in res["rows"] if r["key"] == "C001")
    assert row["name"] == "Brand_Search"
    assert row["impressions"] == int(c001["impressions"].sum())
    assert row["clicks"] == int(c001["clicks"].sum())
    assert row["cost_usd"] == round(float(c001["cost_usd"].sum()), 2)
    assert row["conversions"] == int(c001["conversions"].sum())
    assert row["ctr"] == round(row["clicks"] / row["impressions"], 4)
    assert row["cpc"] == round(row["cost_usd"] / row["clicks"], 2)
    assert row["roas"] == round(
        row["conversion_value_usd"] / row["cost_usd"], 2
    )
    assert "daily" not in row  # no daily detail by default


def test_out_of_range_returns_empty_with_note() -> None:
    """A range outside the data returns empty rows plus an explanation."""
    res = get_performance("2027-01-01", "2027-01-31")
    assert res["rows"] == []
    assert res["note"] is not None
    assert "2027-01-01" in res["note"] and "2026-06-01" in res["note"]

    with pytest.raises(ValueError, match="after end_date"):
        get_performance("2026-06-10", "2026-06-01")


def test_levels_and_include_daily() -> None:
    """ad_group / search_term levels work; daily detail is opt-in; bad level raises."""
    ag = get_performance("2026-06-01", "2026-06-30", level="ad_group")
    assert len(ag["rows"]) == 30

    terms = get_performance("2026-06-01", "2026-06-30", level="search_term")
    assert len(terms["rows"]) == 200
    assert "name" not in terms["rows"][0]

    daily = get_performance(
        "2026-06-14", "2026-06-16", level="campaign", include_daily=True
    )
    c001 = next(r for r in daily["rows"] if r["key"] == "C001")
    assert [d["date"] for d in c001["daily"]] == [
        "2026-06-14",
        "2026-06-15",
        "2026-06-16",
    ]
    assert all("cost_usd" in d for d in c001["daily"])

    with pytest.raises(ValueError, match="invalid level"):
        get_performance("2026-06-01", "2026-06-30", level="keyword")
