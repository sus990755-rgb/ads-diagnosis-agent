# 决策日志

## D-01（2026-10-10）数据生成分布

- **问题**：规格 §9.1 要求 25 case，但注入模式在 5 Campaign × 30 天数据上如何分布未明确（共享搜索词池 or 独占）。
- **裁定**（用户）：分层独占生成——5 Campaign × 30 AdGroup × 200 唯一搜索词，共 4912 行，seed=42 可复现。

## D-02（2026-10-10）报告输出路径冲突

- **问题**：§5 工具 4 build_report 与 §7 JSON 输出Schema 冲突（工具清单含报告工具，但输出要求应用层结构化 JSON）。
- **裁定**（用户）：以 §7 为准，build_report 不作为 agent 工具，实现为 `src/report.py` 的 pipeline 函数。

## D-03（2026-10-12）正常 case 断言误判与强化

- **问题**：Round 7（deepseek-v4-flash）case-25 断言失败。失败输出中agent 给出 `{"type": "none", "confidence": "high"}` 的 finding（"确认无异常，高置信"）——语义上是正常 case 的**正确行为**，但断言白名单仅允许 negative_keyword/scale_up 给 high，属**框架误判，非降低标准**。
- **裁定**（用户）：①白名单加入 none；②同时补强核心断言：正常 case 的 findings 中 type=anomaly 数量必须为 0（噪声观察应写入 summary 或 type=none，不得以 anomaly 类型出现）；③none 类置信度不限。
- **修改前断言**（build_tests.py, category == "normal"）：
  ```js
  JSON.parse(output).findings.every(f => f.confidence !== 'high'
    || f.type === 'negative_keyword' || f.type === 'scale_up')
  ```
- **修改后断言**：
  ```js
  JSON.parse(output).findings.every(f => f.type !== 'anomaly')
  JSON.parse(output).findings.every(f => f.confidence !== 'high'
    || ['negative_keyword','scale_up','none'].includes(f.type))
  ```
- **影响**：用新断言离线重评 Round 7 输出，case-23/24/25 均因存在 anomaly/low finding 判 FAIL（agent 把已识别为噪声的波动仍以 anomaly 类型上报）——暴露的是 agent 判断层问题，转入 Round 7 失败分析。

## D-04（2026-10-12）置信度校准指标替换

- **问题**：规格 §9.2 原指标"标注 low 的 case 中确有数据问题的比例 ≥ 90%"字面是评测集自身属性（9 个 low case 中 6 个有数据问题 = 67%），无法作为 agent 验收线。
- **裁定**（用户）：旧指标废弃（Round 7 按工程解读算得 78%，保留于 eval_report.md 附录并注明废弃原因），替换为两条：
  - (a) **Finding 级校准**：agent 标注 low 的 findings 中 ≥90% 带显式 data_gap 或可指认的数据不足证据（口径：系统提示词 §3 的 low 三条件——数据缺口 / 小基数 / 冷启动累计点击<30 / 追踪存疑）；
  - (b) **Case 级保守性**：冷启动/数据缺失类 case 中，high 置信 findings 数必须为 0。

## D-05（2026-10-12）置信度封顶规则的语义细化与三项提示词修复

### 背景与失败现象

Round 7（agent v1.1 + deepseek-v4-flash，24/25）重算新口径后暴露三个失败：

1. **正常 case 误报（判断）**：case-23/24/25 各产出 1-2 条 `anomaly/low` finding。agent 已在 evidence 中正确识别为小基数噪声（"单日减少 6 个 < 8"），但仍以 type=anomaly 上报——噪声观察的类型归属错误。
2. **Case 级保守性不达标（判断）**：case-18/20（data_gap 类）各产出 1 条 `tracking/high`——窗口内含 C004 06-22 历史缺口，§3"数据不完整→low"未被严格执行。
3. **low finding 缺压低依据（表达）**：case-01 的 none/low、case-07 的 anomaly/low 未写明压 low 的理由（Finding 级校准严格文本匹配 89.2%，距 90% 线差 1 条）。

### 封顶规则的窗口验证冲突与三方案对比

粗粒度封顶规则（"窗口内任一实体存在数据缺口→全部 findings 上限 low"）落地前，先对冻结 case 做机械化影响分析（读数据文件断言每个相关 case 的窗口是否含缺口），发现：

- case-21（锚定 06-21，窗口 06-15..06-21）：不含缺口 ✓
- **case-22（锚定 06-22，窗口 06-16..06-22）：含缺口——缺口日就是锚定日当天**，触发立即停止指令

三方案对比：

| 方案 | 内容 | 结果 |
|---|---|---|
| D | 封顶仅对"**早于锚定日**的历史缺口"生效；锚定日当天数据未到按窗口截断处理 | case-22 不触发（tracking/high 保留），case-18/20 正常触发（(b) 达标）✅ 采纳 |
| E | 规则原样执行，接受 case-22 被压 low | 断言机械上仍过，但违背 case 设计意图（min=high），且"当天数据未到"被错误等同于"历史数据不可信"❌ |
| F | 按实体封顶（仅涉及缺口实体的 finding 压 low） | case-18/20 的 C002 tracking/high 会继续存在，(b) 依旧不达标 ❌ |

**选择 D 的语义理由**："应到而未到"与"尚未到期"是两种本质不同的数据状态。早于锚定日的历史缺口意味着同步管道已经失败且不可追回，整个窗口的结论都应降权；锚定日当天的数据只是尚未到达（T+0 延迟是常态），不应惩罚整份报告，只需声明分析截止日。透明度是这两条规则共同的设计意图：宁可让报告"看起来更不完整"，也不让读者误以为结论建立在完整数据上——所以两种情形都强制在 summary 中显式声明，而非静默处理。

### 流程复盘

本次规则变更前对冻结 case 做机械化影响分析（执行顺序第 1 步），提前拦截了 case-22 的行为漂移——**评测集对系统变更本身构成回归保护**：冻结的 25 个 case 不仅验收 agent，也验收"验收规则"的变更。这验证了 v1.0-eval-freeze 的冻结决策价值。

### 落地内容

1. 修复一（`prompts/diagnose.md` §3 小基数规则）：补"判定为噪声/正常波动的现象不得输出为 type=anomaly 的 finding；如需留痕，写入 summary 或以 type=none 表达"。
2. 修复二（§3 新增数据缺口封顶规则段）：按方案 D 最终措辞写入，含两种 summary 强制声明。
3. 修复三（§3 低置信度段 + `build_tests.py` 全局断言 `LOW_REASON_ASSERT`）：low finding 必须在 evidence/risk_note/data_gap 中含"缺口/小基数/冷启动/追踪"四关键词之一——可审计性从模型自觉升级为机器强制。

## D-06（2026-10-12）兜底断言与强制措辞冲突（框架缺陷 #3）

- **现象**：Round 7b 首次结果 7/25，18 个失败全部命中兜底断言 `summary.indexOf('降级') === -1`。逐条核查：18 处"降级"全是模型按 D-05 修复二执行的强制声明（"本次诊断因历史数据缺口整体降级"）或对规则的复述（"不触发整体降级"），真实降级输出（`诊断运行失败`）为 0 条。
- **定性**：框架误判，与 D-03 同类——旧断言的匹配词与 D-05 新增的强制措辞冲突。
- **修复**：兜底标记精确化为 `_degraded_result` 的固定开头"诊断运行失败"（`build_tests.py` `NOT_DEGRADED_ASSERT`），离线重评 Round 7b 输出得 25/25。
- **教训**：凡在提示词中引入强制措辞，必须同步检索断言库中的文本匹配规则，评估措辞碰撞。

## D-07（2026-10-13）Round F 环境适配：Moonshot 限额、provider 重试与 temperature 钳制

- **现象**：Round F（kimi-k2.6 定稿轮）前三次全量尝试全部无效——(1) promptfoo 调用系统 Python 缺 `agents` 依赖，25 case 全 error；(2)(3) 并发 5 触发 Moonshot 429 风暴，25 case 全降级。
- **根因**：Moonshot 账号硬限额 `max organization concurrency: 1`、`organization max RPM: 3`（错误响应原文），并发 5 下 worker 互相踩踏，重试亦被限流吞没。
- **修复（均为评测环境层，agent/提示词零改动）**：
  1. `PROMPTFOO_PYTHON` 指向项目 .venv 解释器；
  2. `evals/provider.py` 增加降级重试（429 等基础设施降级最多重试 4 次、退避 5/10/15s）——降级报告不是 agent 真实结果，重跑等价于该 case 延后起跑，不违反"结果原样入报告"原则；
  3. 并发降为 1（CLI `-j 1`，不改已冻结的 promptfoo.yaml），25 case 全部真实完成、零降级。
- **temperature 差异（如实记录）**：kimi-k2.6 服务端硬限制只接受 temperature=1（HTTP 400），`src/agent.py` 检测 kimi 模型名自动钳制为 1 并打印提示。Round F 实际 temperature=1，与 Round 7b 的 0.1 不同，属模型方约束，非人为调参。
- **配置路由**：`src/config.py` 新增 `LLM_API_KEY/LLM_BASE_URL/LLM_MODEL` 三键，设置 `LLM_MODEL` 时优先于 `OPENAI_*` 生效，注释掉即切回 deepseek——切模型不再改动原工作配置。
- **教训**：换模型前先做单 case 冒烟（本次冒烟即暴露 temperature 限制）；评测并发度必须与账号限额匹配，限额信息以服务端错误原文为准。
