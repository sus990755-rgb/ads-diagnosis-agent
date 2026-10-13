"""Connectivity check for the kimi-k2.6 final-report run (Round F).

Reads LLM_API_KEY / LLM_BASE_URL / LLM_MODEL from .env — stdlib urllib only,
no third-party dependencies. The API key is never printed in full.

Run:  python test_kimi.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path


def load_env(path: str = ".env") -> dict:
    """Parse a .env file without python-dotenv (stdlib-only requirement)."""
    env: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def chat(base_url: str, api_key: str, payload: dict) -> dict:
    """POST /chat/completions and return the parsed JSON response."""
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    env = load_env()
    api_key = env.get("LLM_API_KEY", "")
    base_url = env.get("LLM_BASE_URL", "https://api.moonshot.cn/v1")
    model = env.get("LLM_MODEL", "kimi-k2.6")
    if not api_key:
        print("FAIL: .env 中 LLM_API_KEY 为空，请先填入 Key 再运行")
        return
    masked = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"
    print(f"端点: {base_url} | 请求模型: {model} | Key: {masked}")
    print()

    results: list[bool] = []

    # ---- check 1: basic chat completion ----
    try:
        r = chat(base_url, api_key, {
            "model": model,
            "messages": [{"role": "user", "content": "只回复两个字：正常"}],
            "max_tokens": 128,
            # kimi-k2.6 rejects any temperature other than 1; omit the field.
            # Small max_tokens gets fully consumed by the model's thinking,
            # leaving content empty — 128 leaves room for the actual reply.
        })
        content = (r["choices"][0]["message"].get("content") or "").strip()
        actual_model = r.get("model", "?")
        ok = bool(content)
        print(f"检查1 基础调用: {'PASS' if ok else 'FAIL'} | "
              f"实际返回模型: {actual_model} | 内容: {content[:20]!r}")
        results.append(ok)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:150]
        print(f"检查1 基础调用: FAIL | HTTP {e.code}: {body}")
        results.append(False)
    except Exception as e:
        print(f"检查1 基础调用: FAIL | {type(e).__name__}: {e}")
        results.append(False)

    # ---- check 2: tool calling ----
    tools = [{
        "type": "function",
        "function": {
            "name": "get_date",
            "description": "获取今天的日期",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }]
    try:
        r = chat(base_url, api_key, {
            "model": model,
            "messages": [{"role": "user", "content": "今天几号？请调用工具获取"}],
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": 256,
        })
        tool_calls = r["choices"][0]["message"].get("tool_calls") or []
        ok = len(tool_calls) > 0
        names = [t.get("function", {}).get("name", "?") for t in tool_calls]
        print(f"检查2 工具调用: {'PASS' if ok else 'FAIL'} | tool_calls: {names}")
        results.append(ok)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:150]
        print(f"检查2 工具调用: FAIL | HTTP {e.code}: {body}")
        results.append(False)
    except Exception as e:
        print(f"检查2 工具调用: FAIL | {type(e).__name__}: {e}")
        results.append(False)

    print()
    if len(results) == 2 and all(results):
        print("总结论: 全部 PASS，可以进入 Round F 定稿轮")
    else:
        print("总结论: 存在 FAIL，请按报错含义排查后重试")


if __name__ == "__main__":
    main()
