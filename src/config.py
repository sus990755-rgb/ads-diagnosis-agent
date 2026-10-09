"""Central configuration: environment variables and shared paths.

All file paths and secrets must come from here (engineering red line 2).
Secrets are read from .env via python-dotenv and never committed.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(PROJECT_ROOT / ".env")

DATA_PATH = PROJECT_ROOT / "data" / "campaigns_30d.csv"
TRACE_DB_PATH = PROJECT_ROOT / "trace.sqlite3"
PROMPT_PATH = PROJECT_ROOT / "prompts" / "diagnose.md"

# LLM settings (Kimi / Moonshot OpenAI-compatible endpoint by default)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.moonshot.cn/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "moonshot-v1-8k")

# Feishu push
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")
FEISHU_WEBHOOK_SECRET = os.getenv("FEISHU_WEBHOOK_SECRET", "")
