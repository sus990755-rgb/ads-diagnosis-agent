# ads-diagnosis-agent

出海投放诊断 Agent（MVP）：每天检查 Google Ads 投放数据（CSV 模拟），自动发现异常并输出带置信度的结构化诊断报告，渲染为 Markdown 推送到飞书群机器人。**Agent 只产出建议，绝不自动执行任何投放修改。**

## 背景

出海投放团队每天需要人工巡查账户：消耗突增、转化骤降、追踪丢失、否词机会、缩量、冷启动等问题发现滞后就会烧钱。本项目用"规则检测器 + LLM 判断层"的架构做每日自动诊断：数值计算全部由确定性代码完成（工程红线：任何数值计算不得由 LLM 完成），LLM 只负责归纳、定性、定置信度和写建议。

## 架构

```
data/campaigns_30d.csv          # 模拟数据源（data_generator.py 生成，seed=42 可复现）
        │
        ▼
┌─────────────────────────────────────────────────┐
│ src/agent.py  (openai-agents SDK, 主循环)        │
│  ├─ prompts/diagnose.md      系统提示词          │
│  ├─ 任务提示词（锚定日/窗口/自检清单）            │
│  └─ 应用层校验：提取 JSON → pydantic → 一轮修复  │
│       → 降级报告（任何失败不静默）               │
└─────────────────────────────────────────────────┘
        │ function tools（每个调用写入 trace）
        ▼
┌─────────────────────────────────────────────────┐
│ 工具层（纯代码，无 LLM）                          │
│  src/tools/detect_anomalies.py   5 条规则检测     │
│  src/tools/get_performance.py    分层指标下钻     │
│  src/tools/get_tracking_status.py 追踪健康判定    │
└─────────────────────────────────────────────────┘
        │
        ▼
src/trace.py    SQLite 留痕（runs / tool_calls，含 token 与成本）
src/report.py   JSON → Markdown 报告
src/notify.py   飞书群机器人推送（签名验签；未配置则本地降级存盘）
src/baseline.py 纯规则基线（无 LLM），用于评测对照
```

## 快速开始

环境：Python ≥ 3.11，Windows / macOS / Linux 均可。

```bash
# 1. 安装依赖（uv）
uv sync

# 2. 生成模拟数据（可复现，seed 固定）
python -m src.data_generator

# 3. 配置密钥
cp .env.example .env
# 编辑 .env：OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME
#   按评测阶段选模型（详见 MODEL_ROUTING.md，型号均已核实）：
#   冒烟迭代用智谱 glm-4.7-flash（免费）：
#   OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
#   MODEL_NAME=glm-4.7-flash
#   FEISHU_WEBHOOK_URL/SECRET 留空则报告保存到本地 reports/ 目录

# 4. 运行一次诊断（--date 指定锚定日，默认取数据最新日期）
python -m src.agent --date 2026-06-21

# 5. 运行规则基线对照
python -m src.baseline --date 2026-06-21

# 6. 单元测试
python -m pytest tests/ -q
```

### 运行评测（promptfoo）

```bash
npm install -g promptfoo   # 需要 Node.js
cd evals
PROMPTFOO_PYTHON="..\.venv\Scripts\python.exe" \
  promptfoo eval -c promptfoo.yaml --no-cache -o roundN.json
```

25 个 case 的定义在 `evals/cases.v1.0.frozen.json`（**Round 7 启动时冻结，此后任何 case 不得修改**，见 git tag `v1.0-eval-freeze`），断言由 `evals/build_tests.py` 生成到 `evals/tests.json`；各轮结果与失败分析见 `evals/eval_report.md`。

## 评测结果

以 promptfoo 驱动真实 Agent 跑 25 个冻结 case，断言为确定性 JS。四个基准（逐 case 明细与开发期轮次见 `evals/eval_report.md`）：

| 基准 | 模型 | temperature | 总分 | §9.2 验收线 | 说明 |
|---|---|---|---|---|---|
| 规则基线（§9.3 对照，无 LLM） | — | — | — | 不达标 | 召回尚可但所有 finding 一律 high，小基数/冷启动误报严重，无放量评估 |
| Round 7b【生产定稿】 | deepseek-v4-flash | 0.1 | **25/25** | **4/4 全过**：召回 100%、误报 0、违禁 0、校准 100% + 0 high | 并发 5，4m54s |
| Round F2【对照】 | deepseek-v4-flash | 1 | 25/25 | 4/4 全过（全场 0 条 high，比 7b 更保守） | 隔离 temperature 变量，4m31s |
| Round F【对比实验】 | kimi-k2.6 | 1（模型硬限制） | 21/25 | 4/5：召回 86.4%、Finding 校准 98.2%、Case 保守性 ❌（2 条 scale_up/high 越过封顶规则） | 并发 1（账号限额），1h47m |

结论：F2 证明 temperature=1 不破坏 deepseek 的规则遵循，Round F 中 kimi-k2.6 的越界源于模型本身。**生产定稿配置 = agent v1.1 + deepseek-v4-flash @ temperature 0.1（Round 7b）**；k2.6 轮次数字按定稿铁律原样留档。开发期 Round 1-6（免费档限流污染）仅供参考。

规格 §9.2 验收线：关键发现召回 ≥70%；正常 case 误报 ≤20%（anomaly 数必须为 0）；违禁行为（声称已执行修改/预测未来）0 次；置信度校准 (a) low finding 带数据不足依据 ≥90% (b) 冷启动/缺数据 case 的 high finding 数 = 0。

## 成本

单次诊断运行约消耗 4.4 万 input token + 0.25 万 output token，平均耗时约 3 分钟（glm-4.5-flash 免费档，含 3-5 轮工具调用）。token 单价走 `config.py` 的 `PRICE_INPUT_CNY_PER_MTOK` / `PRICE_OUTPUT_CNY_PER_MTOK`，每次运行的 token 与成本自动写入 `trace.sqlite3`。免费档单价为 0，日频运行成本 ¥0；切换付费模型时改单价即可自动核算。

## 已知限制

1. **数据为 CSV 模拟**：未接真实 Google Ads API；追踪状态由数据规则推断（点击正常但转化为 0），真实场景应接转化标签/GA4 回传状态。
2. **免费档模型稳定性**：glm-4.5-flash 存在偶发 JSON 不合法、枚举值违规和限流（429）/连接错误；应用层已做一轮修复 + 降级报告兜底，但评测中仍有约 10-20% 的运行受基础设施影响。
3. **小基数判断依赖提示词约束**：模型偶发不遵守"单日转化减少 < 8 个 = 噪声"的优先级规则，弱模型上误报率会波动；更强模型或应用层硬校验可进一步收敛。
