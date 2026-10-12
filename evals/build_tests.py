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

# The degraded fallback report always starts with this exact marker
# (src/agent.py _degraded_result). Matching the bare word 降级 would
# false-positive on the mandated cap-rule summary phrase "整体降级" (D-06).
NOT_DEGRADED_ASSERT = "JSON.parse(output).summary.indexOf('诊断运行失败') === -1"

# Every low-confidence finding must state its downgrade reason with one of
# the four keywords (decision log D-05, fix 3): machine-enforced auditability
# instead of relying on model self-discipline.
LOW_REASON_ASSERT = (
    "JSON.parse(output).findings.every(f => f.confidence !== 'low'"
    " || /缺口|小基数|冷启动|追踪/.test("
    "(f.evidence || '') + (f.risk_note || '') + (f.data_gap || '')))"
)


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
            # false positive = ANY anomaly-type finding on a clean day
            # (decision log D-03: noise observations belong in type=none or
            # the summary, never in type=anomaly)
            "JSON.parse(output).findings.every(f => f.type !== 'anomaly')",
            # high confidence is legitimate only for opportunity findings
            # (negative_keyword / scale_up) and the all-clear type (none);
            # none confidence is otherwise unrestricted
            "JSON.parse(output).findings.every(f => f.confidence !== 'high'"
            " || ['negative_keyword','scale_up','none'].includes(f.type))",
        ]
    raise ValueError(f"unknown category: {category}")


def main() -> Path:
    cases = json.loads((EVALS / "cases.v1.0.frozen.json").read_text(encoding="utf-8"))
    tests = []
    for c in cases:
        asserts = [
            {"type": "javascript", "value": SCHEMA_ASSERT},
            {"type": "javascript", "value": NOT_DEGRADED_ASSERT},
            {"type": "javascript", "value": LOW_REASON_ASSERT},
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
