"""promptfoo python provider: run the real agent for the case's anchor date.

promptfoo calls call_api(prompt, options, context); the anchor date comes
from context['vars']['date']. Output is the agent's JSON string so the
JavaScript assertions can parse it directly.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def call_api(prompt, options, context):
    from src.agent import run_diagnosis

    date = context["vars"]["date"]
    result = asyncio.run(run_diagnosis(date))
    return {"output": result.model_dump_json(ensure_ascii=False)}
