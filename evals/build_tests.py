"""Generate promptfoo-native tests.json from spec-format cases.v1.0.frozen.json.

Adds deterministic JavaScript assertions per category. The frozen cases file
stays the human-readable source of truth (spec section 9.1 fields) and MUST
NOT be edited after the v1.0-eval-freeze tag; tests.json is a generated
artifact:

    python -m evals.build_tests
"""

from __future__ import annotations

import json
from pathlib import Path

EVALS = Path(__file__).resolve().parent

SCHEMA_ASSERT = """
const o = JSON.parse(output);
return typeof o.summary === 'string' && Array.isArray(o.findings)
  && Array.isArray(o.overall_priority)
  && o.findings.every(f => ['anomaly','negative_keyword','scale_up','tracking','none'].includes(f.type)
      && ['high','medium','low'].includes(f.confidence));
"""

NOT_DEGRADED_ASSERT = "JSON.parse(output).summary.indexOf('降级') === -1"


def _category_asserts(category: str, focus: str) -> list[str]:
    text = "JSON.stringify(JSON.parse(output))"
    if category == "cost_spike":
        return [
            f"{text}.includes('{focus}')",
            f"/消耗|成本|cost/i.test({text})",
        ]
    if category == "negative_keyword":
        return [
            f"{text}.includes('free coffee maker download')",
            f"JSON.parse(output).findings.some(f => f.type === 'negative_keyword')",
        ]
    if category == "scale_up":
        return [
            f"{text}.includes('C001')",
            f"JSON.parse(output).findings.some(f => f.type === 'scale_up')"
            f" || {text}.includes('放量')",
        ]
    if category == "cold_start":
        return [
            f"JSON.parse(output).findings.some(f => /C003|New_Product/.test(f.entity)"
            " && f.confidence === 'low')",
            f"JSON.parse(output).findings.every(f => !/C003|New_Product/.test(f.entity)"
            " || f.confidence === 'low')",
        ]
    if category == "data_gap":
        return [
            f"{text}.includes('06-22')",
            "JSON.parse(output).findings.some(f => f.data_gap)",
        ]
    if category == "tracking":
        return [
            f"JSON.parse(output).findings.some(f => f.type === 'tracking')",
            f"/C002|Generic/.test({text})",
        ]
    if category == "normal":
        return [
            # false positive = high-confidence anomaly/tracking on a clean day;
            # high-confidence opportunity findings (neg keyword / scale up) are
            # legitimate and do not count as false positives
            "JSON.parse(output).findings.every(f => f.confidence !== 'high'"
            " || f.type === 'negative_keyword' || f.type === 'scale_up')",
        ]
    raise ValueError(f"unknown category: {category}")


def main() -> Path:
    cases = json.loads((EVALS / "cases.v1.0.frozen.json").read_text(encoding="utf-8"))
    tests = []
    for c in cases:
        asserts = [
            {"type": "javascript", "value": SCHEMA_ASSERT},
            {"type": "javascript", "value": NOT_DEGRADED_ASSERT},
        ] + [
            {"type": "javascript", "value": v}
            for v in _category_asserts(c["category"], c["data_ref"].get("focus", ""))
        ]
        tests.append(
            {
                "vars": {
                    "case_id": c["id"],
                    "date": c["data_ref"]["date"],
                    "category": c["category"],
                    "expected_finding": c["expected_finding"],
                },
                "assert": asserts,
            }
        )
    out = EVALS / "tests.json"
    out.write_text(json.dumps(tests, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(tests)} tests -> {out}")
    return out


if __name__ == "__main__":
    main()
