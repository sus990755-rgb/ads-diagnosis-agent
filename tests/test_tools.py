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


# ---- Tool 2: detect_anomalies ----

from src.tools.detect_anomalies import detect_anomalies

FULL_RANGE = ["2026-06-01", "2026-06-30"]
CLEAN_WINDOW = ["2026-06-01", "2026-06-17"]  # before every injected campaign-level anomaly


def _by_type(res: dict, anomaly_type: str) -> list[dict]:
    return [a for a in res["anomalies"] if a["type"] == anomaly_type]


def test_cost_spike_positive() -> None:
    """Rule cost_spike fires on C001's injected 2026-06-15 spike."""
    hits = [a for a in _by_type(detect_anomalies(FULL_RANGE), "cost_spike")
            if a["entity_key"] == "C001"]
    assert len(hits) == 1
    assert hits[0]["severity"] == "high"
    ev = hits[0]["evidence"]
    assert ev["date"] == "2026-06-15"
    assert ev["cost_usd"] > 1.5 * ev["prev_cost_usd"]


def test_cost_spike_negative() -> None:
    """Rule cost_spike stays silent on normal fluctuation (C005 clean window)."""
    res = detect_anomalies(CLEAN_WINDOW)
    assert [a for a in _by_type(res, "cost_spike") if a["entity_key"] == "C005"] == []


def test_conversion_drop_positive() -> None:
    """Rule conversion_drop fires on C001 2026-06-15 (6 -> 1 conversions)."""
    hits = [a for a in _by_type(detect_anomalies(FULL_RANGE), "conversion_drop")
            if a["entity_key"] == "C001" and a["evidence"]["date"] == "2026-06-15"]
    assert len(hits) == 1
    ev = hits[0]["evidence"]
    assert ev["conversions"] < 0.5 * ev["prev_conversions"]


def _synthetic_df(conversions: list[int]) -> "pd.DataFrame":
    """Single-campaign daily rows with steady volume, conversions as given."""
    import pandas as pd  # local import keeps the fixture lightweight

    dates = pd.date_range("2026-06-01", periods=len(conversions), freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "campaign_id": "CX",
            "campaign_name": "Synthetic",
            "ad_group_id": "AGX",
            "ad_group_name": "Synthetic - AdGroup 1",
            "search_term": "synthetic term",
            "impressions": 1000,
            "clicks": 100,
            "cost_usd": 100.0,
            "conversions": conversions,
            "conversion_value_usd": [c * 50.0 for c in conversions],
        }
    )


def test_conversion_drop_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rule conversion_drop stays silent below/at the -50% threshold.

    Uses synthetic steady-volume data: campaign-level daily conversions are
    small integers in the real mock data, where natural Poisson noise can
    exceed 50%; threshold logic must be tested against controlled input.
    """
    import src.tools.detect_anomalies as mod

    # -40% and exactly -50%: must NOT fire (rule is strictly > 50%)
    df = _synthetic_df([10, 10, 6, 5, 10, 10])
    monkeypatch.setattr(mod, "load_data", lambda: df)
    res = mod.detect_anomalies(["2026-06-01", "2026-06-06"])
    assert _by_type(res, "conversion_drop") == []

    # -60% on the same volume: must fire (sanity check of the synthetic setup)
    df = _synthetic_df([10, 10, 4, 10, 10, 10])
    monkeypatch.setattr(mod, "load_data", lambda: df)
    res = mod.detect_anomalies(["2026-06-01", "2026-06-06"])
    assert len(_by_type(res, "conversion_drop")) == 1


def test_negative_keyword_positive() -> None:
    """Rule negative_keyword_opportunity flags the injected zero-conversion term."""
    hits = _by_type(detect_anomalies(FULL_RANGE), "negative_keyword_opportunity")
    terms = {a["entity_key"] for a in hits}
    assert "free coffee maker download" in terms
    ev = next(a["evidence"] for a in hits
              if a["entity_key"] == "free coffee maker download")
    assert ev["clicks"] >= 20 and ev["conversions"] == 0 and ev["cost_usd"] > 50
    assert ev["campaign_id"] == "C004"


def test_negative_keyword_negative() -> None:
    """Rule negative_keyword_opportunity never flags a converting term."""
    hits = _by_type(detect_anomalies(FULL_RANGE), "negative_keyword_opportunity")
    flagged = {a["entity_key"] for a in hits}
    df = load_data()
    converting = df[df["conversions"] > 0]["search_term"].unique()
    assert flagged.isdisjoint(converting)


def test_impression_drop_positive() -> None:
    """Rule impression_drop fires on C005's injected 2026-06-18 drop."""
    hits = [a for a in _by_type(detect_anomalies(FULL_RANGE), "impression_drop")
            if a["entity_key"] == "C005"]
    assert len(hits) == 1
    assert hits[0]["severity"] == "medium"
    ev = hits[0]["evidence"]
    assert ev["date"] == "2026-06-18"
    assert ev["impressions"] < 0.5 * ev["prev_impressions"]


def test_impression_drop_negative() -> None:
    """Rule impression_drop stays silent on normal fluctuation."""
    res = detect_anomalies(CLEAN_WINDOW)
    assert _by_type(res, "impression_drop") == []


def test_tracking_loss_positive() -> None:
    """Rule tracking_loss_suspected fires on C002 2026-06-20/21 zero-conversion streak."""
    hits = [a for a in _by_type(detect_anomalies(FULL_RANGE), "tracking_loss_suspected")
            if a["entity_key"] == "C002"]
    assert len(hits) == 1
    assert hits[0]["severity"] == "high"
    ev = hits[0]["evidence"]
    assert ev["start_date"] == "2026-06-20" and ev["end_date"] == "2026-06-21"
    assert ev["zero_conversion_days"] == 2 and ev["clicks_on_those_days"] > 0


def test_tracking_loss_negative() -> None:
    """Cold-start C003 (low clicks) and normal campaigns are NOT flagged."""
    res = detect_anomalies(FULL_RANGE)
    flagged = {a["entity_key"] for a in _by_type(res, "tracking_loss_suspected")}
    assert "C003" not in flagged
    res_clean = detect_anomalies(CLEAN_WINDOW)
    assert _by_type(res_clean, "tracking_loss_suspected") == []


def test_data_gap_reported() -> None:
    """The C004 2026-06-22 gap (pattern 6) surfaces as a data_gap finding."""
    hits = _by_type(detect_anomalies(FULL_RANGE), "data_gap")
    assert len(hits) == 1
    assert hits[0]["entity_key"] == "C004"
    assert hits[0]["evidence"]["missing_date"] == "2026-06-22"
