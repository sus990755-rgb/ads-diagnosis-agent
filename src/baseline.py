"""Pure if-else rule baseline (spec section 9.3), no LLM involved.

Maps detect_anomalies phenomena directly to findings with canned wording.
Deliberately naive: no cold-start exemption, no uncertainty handling for
data gaps — this is the contrast object for the agent in evaluation.

Entry point: python -m src.baseline --date 2026-06-21
"""

from __future__ import annotations

import argparse
import sys
from datetime import date as date_cls, timedelta

from src.agent import DiagnosisResult, Finding
from src.data_loader import load_data
from src.report import build_report
from src.tools.detect_anomalies import detect_anomalies

_SEVERITY_TO_CONFIDENCE = {"high": "high", "medium": "medium", "low": "low"}

_RULES = {
    "cost_spike": (
        "anomaly",
        "建议人工排查该系列出价、预算与匹配方式变化，评估是否需要回调。",
        "消耗突增若持续将快速浪费预算。",
    ),
    "conversion_drop": (
        "anomaly",
        "建议人工检查转化下降当天的广告与落地页变更记录。",
        "转化骤降直接影响 ROI。",
    ),
    "impression_drop": (
        "anomaly",
        "建议人工检查预算是否耗尽、排名变化与广告审核状态。",
        "曝光缩量会导致潜在客户流失。",
    ),
    "negative_keyword_opportunity": (
        "negative_keyword",
        "建议人工将该搜索词加入否定关键词。",
        "该词持续消耗且无转化，浪费预算。",
    ),
    "tracking_loss_suspected": (
        "tracking",
        "建议人工检查转化追踪代码与转化事件配置。",
        "追踪异常会导致转化数据失真，误导投放决策。",
    ),
    "data_gap": (
        "anomaly",
        "建议人工检查数据同步任务，补齐缺失日期数据。",
        "数据缺失期间无法判断真实投放表现。",
    ),
}


def baseline_diagnose(date: str) -> DiagnosisResult:
    """Diagnose the 7-day window ending at ``date`` with pure rules."""
    end = date_cls.fromisoformat(date)
    start = end - timedelta(days=6)
    result = detect_anomalies([str(start), str(end)])

    findings: list[Finding] = []
    for a in result["anomalies"]:
        ftype, recommendation, risk = _RULES.get(
            a["type"], ("anomaly", "建议人工核查。", "未知风险。")
        )
        findings.append(
            Finding(
                type=ftype,  # type: ignore[arg-type]
                entity=a["entity_key"],
                evidence=str(a["evidence"]),
                confidence=_SEVERITY_TO_CONFIDENCE[a["severity"]],  # type: ignore[arg-type]
                recommendation=recommendation,
                risk_note=risk,
                data_gap=None,  # naive: never declares data gaps
            )
        )

    n = len(findings)
    return DiagnosisResult(
        summary=f"规则基线：最近 7 天（{start} 至 {end}）共检测到 {n} 条异常现象。",
        findings=findings,
        overall_priority=[f.entity for f in findings],
    )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run the rule-based baseline.")
    parser.add_argument(
        "--date",
        default=None,
        help="anchor date YYYY-MM-DD; defaults to the latest date in the data",
    )
    args = parser.parse_args()
    date = args.date or str(load_data()["date"].max().date())
    result = baseline_diagnose(date)
    print(result.model_dump_json(indent=2, ensure_ascii=False))
    print("\n---MARKDOWN---\n")
    print(build_report(result, anchor_date=date))


if __name__ == "__main__":
    main()
