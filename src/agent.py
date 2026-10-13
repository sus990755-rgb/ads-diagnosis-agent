"""Agent main loop: single agent + tools with structured JSON output.

Entry point: python -m src.agent --date 2026-06-21
(--date anchors the 7-day analysis window, for evaluation replay; defaults
to the latest date available in the data.)

Degradation: any tool failure or missing data must surface in the output
(never silently skipped); if the whole run fails, a degraded result with
data_gap filled is returned instead of raising.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import re
import sys
import time
from datetime import date as date_cls, timedelta
from typing import Literal

from agents import Agent, ModelSettings, Runner, function_tool, set_tracing_disabled
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from pydantic import BaseModel

from src import config, trace
from src.data_loader import load_data
from src.tools.detect_anomalies import detect_anomalies
from src.tools.get_performance import get_performance
from src.tools.get_tracking_status import get_tracking_status

# We do our own SQLite tracing (T9); the SDK's hosted trace export would
# target OpenAI's backend, which this endpoint is not.
set_tracing_disabled(True)


class Finding(BaseModel):
    """One diagnosis finding, per spec section 7 JSON schema."""

    type: Literal["anomaly", "negative_keyword", "scale_up", "tracking", "none"]
    entity: str
    evidence: str
    confidence: Literal["high", "medium", "low"]
    recommendation: str
    risk_note: str
    data_gap: str | None


class DiagnosisResult(BaseModel):
    """Structured agent output, per spec section 7 JSON schema."""

    summary: str
    findings: list[Finding]
    overall_priority: list[str]


# The endpoint cannot be relied on for strict json_schema response formats,
# so the schema is enforced in-app: instruct -> extract -> pydantic-validate
# -> one repair round -> degraded report (spec section 7).
_SCHEMA_HINT = (
    "你的最终回复必须是且仅是一个符合以下 JSON Schema 的 JSON 对象；"
    "不要用 markdown 代码块包裹，不要输出任何其他文字。"
    "注意：findings[].type 只能取 anomaly / negative_keyword / scale_up / "
    "tracking / none 之一；detect_anomalies 返回的类型名（如 cost_spike、"
    "data_gap）是现象名，可以写进 evidence，但绝不能作为 type 的值。\n"
    + json.dumps(DiagnosisResult.model_json_schema(), ensure_ascii=False)
)


def _parse_result(text: str) -> DiagnosisResult:
    """Extract the JSON object from a model reply and validate it."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j <= i:
        raise ValueError(f"no JSON object found in model output: {text[:200]!r}")
    return DiagnosisResult.model_validate(json.loads(t[i : j + 1]))


def _traced_tools(run_id: str) -> list:
    """Wrap each tool function so every call is recorded to the trace DB.

    functools.wraps preserves the signature and docstring, so the generated
    tool schema/description are identical to the unwrapped function.
    """
    raw_tools = (detect_anomalies, get_performance, get_tracking_status)

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                trace.record_tool_call(
                    run_id, fn.__name__, {"args": args, "kwargs": kwargs},
                    None, (time.perf_counter() - t0) * 1000, error=str(exc),
                )
                raise
            trace.record_tool_call(
                run_id, fn.__name__, {"args": args, "kwargs": kwargs},
                result, (time.perf_counter() - t0) * 1000,
            )
            return result

        return inner

    return [function_tool(wrap(fn)) for fn in raw_tools]


def _build_agent(run_id: str) -> Agent:
    client = AsyncOpenAI(
        api_key=config.ACTIVE_API_KEY, base_url=config.ACTIVE_BASE_URL
    )
    model = OpenAIChatCompletionsModel(model=config.ACTIVE_MODEL, openai_client=client)
    instructions = config.PROMPT_PATH.read_text(encoding="utf-8")
    temperature = config.LLM_TEMPERATURE
    if "kimi" in config.ACTIVE_MODEL.lower() and temperature != 1:
        # kimi-k2.6 hard-rejects any temperature other than 1 (HTTP 400).
        print(f"[config] {config.ACTIVE_MODEL} only allows temperature=1; "
              f"overriding {temperature} -> 1.0", file=sys.stderr)
        temperature = 1.0
    return Agent(
        name="ads-diagnosis-agent",
        instructions=instructions,
        model=model,
        # Low temperature keeps output stable across eval replays: the free
        # tier's default sampling made severity/type labels flip run to run.
        model_settings=ModelSettings(temperature=temperature),
        tools=_traced_tools(run_id),
    )


def _task_prompt(date: str) -> str:
    df = load_data()
    data_min, data_max = df["date"].min().date(), df["date"].max().date()
    end = min(date_cls.fromisoformat(date), data_max)
    start = end - timedelta(days=6)
    return (
        f"今天是 {date}。请诊断本账户最近 7 天（{start} 至 {end}）的 Google Ads "
        f"投放数据。数据整体覆盖 {data_min} 至 {data_max}。"
        f"可用工具只有 3 个：detect_anomalies、get_performance、get_tracking_status"
        f"（不得调用任何其他工具名）。先调用一次 detect_anomalies"
        f"（一次调用即返回诊断窗口 window 与全量区间 full_range 两份结果），再按需下钻 "
        f"get_performance 或核查 get_tracking_status，最后给出结构化诊断结果。"
        f"严格禁止引用 {date} 之后的数据（未来数据不存在）；"
        f"否词机会评估可使用 [{data_min} 至 {end}] 的较长窗口，"
        f"因为搜索词转化判断需要足够累积量。"
        f"输出前逐条自检："
        f"1) anomaly/tracking finding 给 high 之前，确认其单日转化绝对减少 ≥ 8 个，"
        f"否则一律压回 low（小基数噪声按天独立判定，不得跨天拼接升级）；"
        f"2) scale_up 只给全量区间 ROAS ≥ 3 的实体，ROAS < 3 一律不得放量；"
        f"3) 异常类 finding 的证据事件必须在 {start} 至 {end} 窗口内。"
    )


def _usage(result) -> tuple[int, int]:
    """Sum (input_tokens, output_tokens) over all raw model responses."""
    inp = out = 0
    for r in result.raw_responses:
        if r.usage:
            inp += r.usage.input_tokens or 0
            out += r.usage.output_tokens or 0
    return inp, out


def _degraded_result(exc: Exception) -> DiagnosisResult:
    return DiagnosisResult(
        summary=f"诊断运行失败，输出降级报告。原因：{type(exc).__name__}: {exc}",
        findings=[
            Finding(
                type="none",
                entity="account",
                evidence="本次运行未能完成工具调用或模型输出校验。",
                confidence="low",
                recommendation="建议人工检查运行环境（API 配置/网络/数据文件）后重跑。",
                risk_note="本报告为降级输出，未基于完整数据分析。",
                data_gap=f"运行失败，无可用诊断数据：{exc}",
            )
        ],
        overall_priority=[],
    )


async def run_diagnosis(date: str) -> DiagnosisResult:
    """Run one diagnosis for the 7-day window ending at ``date``."""
    run_id = trace.start_run(date, config.ACTIVE_MODEL)
    t0 = time.perf_counter()
    inp = out = 0
    model_io: list | None = None
    status, error = "ok", None
    try:
        agent = _build_agent(run_id)
        result = await Runner.run(
            agent, input=_task_prompt(date) + "\n\n" + _SCHEMA_HINT, max_turns=12
        )
        i1, o1 = _usage(result)
        inp, out = inp + i1, out + o1
        model_io = result.to_input_list()
        try:
            output = _parse_result(result.final_output)
        except (ValueError, json.JSONDecodeError) as parse_err:
            repair = await Runner.run(
                agent,
                input=result.to_input_list()
                + [
                    {
                        "role": "user",
                        "content": f"你的上一次输出未通过校验，错误信息：{parse_err}。"
                        "请修正后只输出符合 schema 的纯 JSON 对象，不要用代码块包裹，"
                        "不要任何其他文字。注意 findings[].type 只能取 "
                        "anomaly / negative_keyword / scale_up / tracking / none。",
                    }
                ],
                max_turns=4,
            )
            i2, o2 = _usage(repair)
            inp, out = inp + i2, out + o2
            model_io = repair.to_input_list()
            output = _parse_result(repair.final_output)
    except Exception as exc:  # degraded report, never silent (spec section 7)
        status, error = "degraded", f"{type(exc).__name__}: {exc}"
        output = _degraded_result(exc)
    trace.finish_run(
        run_id,
        status=status,
        started_monotonic=t0,
        input_tokens=inp,
        output_tokens=out,
        output_json=output.model_dump_json(ensure_ascii=False),
        model_io_json=(
            json.dumps(model_io, ensure_ascii=False, default=str)
            if model_io is not None
            else None
        ),
        error=error,
    )
    return output


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console shows mojibake otherwise
    parser = argparse.ArgumentParser(description="Run the ads diagnosis agent.")
    parser.add_argument(
        "--date",
        default=None,
        help="anchor date YYYY-MM-DD; defaults to the latest date in the data",
    )
    args = parser.parse_args()
    date = args.date or str(load_data()["date"].max().date())
    result = asyncio.run(run_diagnosis(date))
    print(result.model_dump_json(indent=2, ensure_ascii=False))

    # render Markdown and push to Feishu (local fallback inside notify)
    from src import notify, report

    run = trace.latest_run() or {}
    markdown = report.build_report(
        result,
        anchor_date=date,
        duration_ms=run.get("duration_ms"),
        cost_cny=run.get("cost_cny"),
        input_tokens=run.get("input_tokens"),
        output_tokens=run.get("output_tokens"),
    )
    notify.push_feishu(markdown)


if __name__ == "__main__":
    main()
