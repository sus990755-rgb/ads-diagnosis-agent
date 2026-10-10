"""SQLite trace storage: one row per run, one row per tool call.

Tables:
- runs(run_id, anchor_date, model, status, started_at, ended_at,
      duration_ms, input_tokens, output_tokens, cost_cny,
      output_json, model_io_json, error)
- tool_calls(run_id, seq, tool_name, arguments_json, result_summary,
      duration_ms, error)

No external services (spec section 2); DB path comes from config.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime

from src import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    anchor_date TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_ms REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_cny REAL,
    output_json TEXT,
    model_io_json TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    seq INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    result_summary TEXT,
    duration_ms REAL,
    error TEXT
);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.TRACE_DB_PATH)
    conn.executescript(_SCHEMA)
    return conn


def start_run(anchor_date: str, model: str) -> str:
    """Insert a running row and return its run_id."""
    run_id = uuid.uuid4().hex[:12]
    with _conn() as conn:
        conn.execute(
            "INSERT INTO runs (run_id, anchor_date, model, status, started_at)"
            " VALUES (?, ?, ?, 'running', ?)",
            (run_id, anchor_date, model, datetime.now().isoformat(timespec="seconds")),
        )
    return run_id


def latest_run() -> dict | None:
    """Return the most recent finished run row as a dict, or None."""
    with _conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM runs WHERE status != 'running'"
            " ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def _next_seq(conn: sqlite3.Connection, run_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 FROM tool_calls WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row[0])


def record_tool_call(
    run_id: str,
    tool_name: str,
    arguments: dict,
    result: object,
    duration_ms: float,
    error: str | None = None,
) -> None:
    """Record one tool call with its arguments and a truncated result summary."""
    try:
        summary = json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        summary = str(result)
    if len(summary) > 1000:
        summary = summary[:1000] + "...(truncated)"
    with _conn() as conn:
        conn.execute(
            "INSERT INTO tool_calls (run_id, seq, tool_name, arguments_json,"
            " result_summary, duration_ms, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                _next_seq(conn, run_id),
                tool_name,
                json.dumps(arguments, ensure_ascii=False, default=str),
                summary,
                round(duration_ms, 1),
                error,
            ),
        )


def finish_run(
    run_id: str,
    status: str,
    started_monotonic: float,
    input_tokens: int,
    output_tokens: int,
    output_json: str,
    model_io_json: str | None,
    error: str | None = None,
) -> None:
    """Finalize a run row with usage, cost, output and replay payload."""
    cost = (
        input_tokens / 1e6 * config.PRICE_INPUT_CNY_PER_MTOK
        + output_tokens / 1e6 * config.PRICE_OUTPUT_CNY_PER_MTOK
    )
    with _conn() as conn:
        conn.execute(
            "UPDATE runs SET status = ?, ended_at = ?, duration_ms = ?,"
            " input_tokens = ?, output_tokens = ?, cost_cny = ?,"
            " output_json = ?, model_io_json = ?, error = ? WHERE run_id = ?",
            (
                status,
                datetime.now().isoformat(timespec="seconds"),
                round((time.perf_counter() - started_monotonic) * 1000, 1),
                input_tokens,
                output_tokens,
                round(cost, 6),
                output_json,
                model_io_json,
                error,
                run_id,
            ),
        )
