"""Markdown report rendering (spec section 8; implements tool-4 semantics
of build_report as a pipeline function: agent JSON -> Markdown)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid a runtime import cycle with src.agent
    from src.agent import DiagnosisResult

# Severity proxy: findings carry confidence but not severity (spec section 7
# schema), so type criticality stands in for severity in the sort order.
_TYPE_SEVERITY = {"anomaly": 0, "tracking": 1, "negative_keyword": 2, "scale_up": 3, "none": 4}
_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
_TYPE_LABEL = {
    "anomaly": "异常",
    "tracking": "追踪",
    "negative_keyword": "否词机会",
    "scale_up": "放量建议",
    "none": "无异常",
}


def build_report(
    result: "DiagnosisResult",
    *,
    anchor_date: str,
    duration_ms: float | None = None,
    cost_cny: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> str:
    """Render a DiagnosisResult as the final Markdown report.

    Findings are sorted by type severity then confidence; every finding
    carries the four required elements (evidence / confidence /
    recommendation / risk note); the footer records run cost and duration.
    """
    lines = [
        f"# Google Ads 投放诊断报告（截至 {anchor_date}）",
        "",
        "## 总结",
        "",
        result.summary,
        "",
        "## 发现明细",
        "",
    ]

    findings = sorted(
        result.findings,
        key=lambda f: (_TYPE_SEVERITY.get(f.type, 9), _CONFIDENCE_ORDER.get(f.confidence, 9)),
    )
    if not findings:
        lines.append("本次诊断无明细发现。")
    for i, f in enumerate(findings, 1):
        lines.append(f"### {i}. [{_TYPE_LABEL.get(f.type, f.type)}｜置信度 {f.confidence}] {f.entity}")
        lines.append("")
        lines.append(f"- 数据依据：{f.evidence}")
        lines.append(f"- 置信度：{f.confidence}")
        lines.append(f"- 建议动作：{f.recommendation}")
        lines.append(f"- 风险说明：{f.risk_note}")
        if f.data_gap:
            lines.append(f"- 数据缺口：{f.data_gap}")
        lines.append("")

    lines += ["## 处理优先级", ""]
    if result.overall_priority:
        lines += [f"{i}. {p}" for i, p in enumerate(result.overall_priority, 1)]
    else:
        lines.append("无")
    lines.append("")

    parts = []
    if duration_ms is not None:
        parts.append(f"耗时 {duration_ms / 1000:.1f}s")
    if input_tokens is not None and output_tokens is not None:
        parts.append(f"token {input_tokens}+{output_tokens}")
    if cost_cny is not None:
        parts.append(f"成本 ¥{cost_cny:.4f}")
    lines.append("---")
    lines.append("")
    lines.append("本次运行：" + ("，".join(parts) if parts else "统计信息缺失"))
    lines.append("")
    lines.append("> 本报告仅为诊断建议，不会自动执行任何投放修改。")
    return "\n".join(lines)
