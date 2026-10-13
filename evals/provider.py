"""promptfoo python provider: run the real agent for the case's anchor date.

promptfoo calls call_api(prompt, options, context); the anchor date comes
from context['vars']['date']. Output is the agent's JSON string so the
JavaScript assertions can parse it directly.

Runs that degrade on transient infrastructure errors (e.g. HTTP 429 rate
limit) are retried with a short backoff: a degraded report is not an agent
result, so re-running it is equivalent to the case having started later.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEGRADED_MARK = "诊断运行失败"
MAX_ATTEMPTS = 4


def call_api(prompt, options, context):
    from src.agent import run_diagnosis

    date = context["vars"]["date"]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        result = asyncio.run(run_diagnosis(date))
        if DEGRADED_MARK not in result.summary:
            return {"output": result.model_dump_json(ensure_ascii=False)}
        if attempt < MAX_ATTEMPTS:
            wait = 5 * attempt
            print(
                f"[provider] {date} degraded (attempt {attempt}/{MAX_ATTEMPTS}), "
                f"retrying in {wait}s",
                file=sys.stderr,
            )
            time.sleep(wait)
    return {"output": result.model_dump_json(ensure_ascii=False)}
