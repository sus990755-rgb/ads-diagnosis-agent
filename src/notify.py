"""Feishu (Lark) group-bot push with signature, plus local fallback.

On any failure (not configured, HTTP error, timeout) the report is saved
under reports/ and the function returns False — the main flow is never
blocked (spec section 8).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from datetime import datetime

import requests

from src import config

LOCAL_REPORT_DIR = config.PROJECT_ROOT / "reports"


def _sign(timestamp: str, secret: str) -> str:
    """Feishu custom-bot signature: base64(HMAC-SHA256(key=ts\\nsecret, msg=''))."""
    key = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(key, b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def save_local(markdown: str) -> str:
    """Persist the report under reports/ and return the file path."""
    LOCAL_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = LOCAL_REPORT_DIR / f"report_{datetime.now():%Y%m%d_%H%M%S}.md"
    path.write_text(markdown, encoding="utf-8")
    return str(path)


def push_feishu(markdown: str, *, title: str = "Google Ads 投放诊断报告") -> bool:
    """POST a markdown card to the Feishu webhook.

    Returns True on Feishu acceptance; on any failure saves locally and
    returns False. Never raises.
    """
    if not config.FEISHU_WEBHOOK_URL:
        path = save_local(markdown)
        print(f"[notify] webhook not configured; saved locally: {path}")
        return False

    payload: dict = {
        "msg_type": "interactive",
        "card": {
            "config": {"enable_forward": False},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [{"tag": "markdown", "content": markdown}],
        },
    }
    if config.FEISHU_WEBHOOK_SECRET:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = _sign(timestamp, config.FEISHU_WEBHOOK_SECRET)

    try:
        resp = requests.post(config.FEISHU_WEBHOOK_URL, json=payload, timeout=10)
        ok = resp.status_code == 200 and resp.json().get("StatusCode", resp.json().get("code")) == 0
    except Exception as exc:
        ok = False
        resp = None
        print(f"[notify] webhook request failed: {type(exc).__name__}: {exc}")
    if not ok and resp is not None:
        print(f"[notify] webhook rejected: HTTP {resp.status_code} {resp.text[:200]}")
    if not ok:
        path = save_local(markdown)
        print(f"[notify] fell back to local save: {path}")
    return ok
