# 评测报告（持续更新）

**口径说明（2026-10-12）**：评测集已于 Round 7 启动时冻结为 `evals/cases.v1.0.frozen.json`（git tag `v1.0-eval-freeze`），此后任何 case 不得修改。**Round 1-6 为开发期数据，受免费档（glm-4.5-flash）限流/降级污染，仅供参考**；正式验收口径从 Round 7（agent v1.1 + deepseek-v4-flash）起算。

## Round 1（2026-10-10，promptfoo eval ID: eval-KKz-2026-10-10T14:24:07）

**方法**：25 个 case（cases.json）经 promptfoo 驱动真实 Agent（glm-4.5-flash），每 case 一次完整诊断运行；断言为确定性 JS（schema 合规、非降级、分类别关键行为）。原始结果：`evals/round1.json`。

**结果**：18 通过 / 7 失败（72%），0 运行错误。耗时 21m47s，成本 ¥0（glm-4.5-flash 免费档）。

| 类别 | 通过/总数 | 备注 |
|---|---|---|
| 异常消耗 | 5/5 | 全部命中 C001/C005 |
| 否词机会 | 4/5 | case-07 未用全量窗口 |
| 放量建议 | 1/4 | Agent 基本不主动给 scale_up |
| 冷启动 | 2/3 | case-17 置信度未压到 low |
| 数据缺失 | 3/3 | data_gap 声明正确 |
| 追踪丢失 | 2/2 | 均正确区分追踪异常 |
| 正常波动 | 1/3 | 2 例把噪声标 high（误报） |

**§9.2 指标**：关键发现召回率 18/25 = 72%（踩线）；误报率 2/3 = 67%（超线 ❌）；违禁行为扫描 0 次 ✅。

**失败分类**（全部为判断问题，非数据/工具问题）：

1. **F1 放量缺失（3 例）**：提示词未要求主动评估放量机会 → 修复：diagnose.md 增加放量评估规则（ROAS 高且稳定的实体给 scale_up 建议）。
2. **F2 小基数误报（2 例）**：单日转化个位数波动被标 high → 修复：置信度规则增加"小基数单日波动不得 high"。
3. **F3 冷启动置信度（1 例）**：C003 finding 未压 low → 修复：强化冷启动条款措辞。
4. **F4 否词窗口（1 例）**：随机性漏检 → 修复：diagnose.md 明确"每次运行须以全量区间调 detect_anomalies 一次"。

**修复落点**：仅改 `prompts/diagnose.md`（表达/判断层），不改数据与工具。

## Round 2（2026-10-11，eval ID: eval-jXS-2026-10-11T11:54:55）

**结果**：13 通过 / 2 失败 / **10 错误**（56m54s）。原始结果：`evals/round2.json`。

**失败分类**：

1. **基础设施问题（10 例错误）**：promptfoo Python worker 默认超时 300s，GLM 免费档当日晚高峰单次运行 200-570s → 大量超时。非模型质量问题。修复：provider config `timeout: 1200000`。
2. **case-17（判断问题）**：C003 冷启动小基数消耗波动（$4.4→$7.7）被报 high → 修复：小基数规则补"消耗 < $50"；冷启动条款改为"下结论前强制查累计点击"，明确检测器对冷启动实体的报警同样降级。
3. **case-25（判断问题 + 评测有效性）**：agent 把全量区间调用中**锚定日之后**的事件写进报告（穿越）→ 修复：任务提示词明确"禁止引用锚定日之后的数据；否词窗口 = [数据起点..锚定日]"。
4. **断言修正**：正常波动 case 的"禁 high"断言过严——否词/放量机会的高置信度是正当发现，不属于误报 → 断言放宽为仅 anomaly/tracking 类型不得 high。

**遗留**：scale_up 修复生效（round2 中 4 个放量 case 全部通过）；召回/误报指标待 Round 3 复测确认。

## Round 3（2026-10-11，eval ID: eval-kOJ-2026-10-11T13:01:27）

**修复内容**：provider 超时提至 1200s；禁止引用锚定日后数据（修复"穿越"）；冷启动强制查累计点击；小基数规则补消耗维度；正常 case 断言放宽（机会类发现不算误报）。

**结果**：19 通过 / 6 失败 / 0 错误（31m41s）。原始结果：`evals/round3.json`。

| 类别 | 通过/总数 |
|---|---|
| 异常消耗 | 4/5 |
| 否词机会 | 5/5 ✅ |
| 放量建议 | 2/4 |
| 冷启动 | 3/3 ✅ |
| 数据缺失 | 3/3 ✅ |
| 追踪丢失 | 2/2 ✅ |
| 正常波动 | 0/3 ❌ |

**失败分类**：

1. **case-01/12（工具调用问题）**：模型幻觉不存在的工具名 `get_tracking_health` → 运行降级。修复：任务提示词显式列出仅有的 3 个工具名。
2. **case-23/24/25（判断问题）**：小基数规则被"前日 11 个转化"绕过，且模型用累计点击为单日噪声背书。修复：规则改为按绝对变化量（转化单日减少 < 8 个 = 噪声）+ high 需多指标印证或连续 2 天持续。
3. **case-11（判断问题）**：放量建议随机漏报，待 Round 4 观察。

**指标**：召回 76% ✅；违禁行为 0 ✅；误报率 3/3 = 100% ❌（待 Round 4 验证修复）。

## Round 4（2026-10-11，eval ID: eval-PN2-2026-10-11T13:41:37）

**修复内容**：任务提示词显式列出 3 个工具名；小基数规则按绝对变化量判定；high 需多指标印证或连续 ≥2 天。

**结果**：15 通过 / 10 失败（60%），原始结果：`evals/round4.json`。表面回退，但失败结构不同：

1. **基础设施问题（6 例）**：GLM 免费档 429 限流（错误码 1302「账户并发过高」，maxConcurrency=2 触发）×4、APIConnectionError ×1、JSON 解析失败 ×1——重试耗尽后走降级输出，断言全灭。非模型质量问题。
2. **case-16/17（判断问题）**：C003 冷启动 finding 检出但严重度给 medium（规则要求一律 low），模型未遵守已有条款。
3. **case-11 / case-22（回归）**：Round 3 均通过、本轮失败（scale_up 漏报 C001；C002 追踪丢失被报成 anomaly high 而非 tracking finding）。判断为采样抖动——GLM 默认温度偏高，跨轮输出不稳定。

**修复落点**：

- `evals/promptfoo.yaml`：`maxConcurrency` 2 → 1（消除 429）。
- `src/agent.py`：Agent 增加 `ModelSettings(temperature=0.1)`（抑制采样抖动，同时改善 JSON 合法率）。
- `prompts/diagnose.md`：§4 增加"任一实体追踪状态为 suspected_broken 时必须单独输出 type=tracking 的 finding，不得只用 anomaly 描述"。

## Round 5（2026-10-11，eval ID: eval-60g-2026-10-11T14:16:36）

**修复内容**：并发 2→1（治 429）；Agent 增加 `ModelSettings(temperature=0.1)`；§4 强制 suspected_broken 必须出 type=tracking finding。

**结果**：17 通过 / 8 失败（68%），0 运行错误。耗时 1h38m（并发 1）。原始结果：`evals/round5.json`。

**失败分类**：

1. **基础设施问题（5 例降级）**：GLM 免费档深夜连接错误 ×3（case-15/21/22）、输出 JSON 校验失败且修复轮未救回 ×2（case-07/20，模型把现象名填进 type 枚举）。429 限流已消除。
2. **case-23/24（判断问题，normal 误报）**：C002/C004 单日转化小基数波动（11→5、6→2、7→1，绝对减少均 < 8）被拼接为"同一现象连续 ≥ 2 天持续"而升级 high——绕过了小基数噪声规则。修复：§3 明确小基数噪声按天独立判定、优先级最高，不得用连续 2 天条款升级。
3. **case-11（判断问题，scale_up 报错对象）**：对 ROAS 2.28 的 C005 给出放量建议（违反 §6 ROAS ≥ 3 硬条件），漏报 ROAS≈3.5 的 C001。修复：§6 强调 ROAS ≥ 3 不可突破，且放量评估必须用 get_performance 覆盖全部 campaign 逐一过筛。
4. **修复轮增强（应用层）**：JSON/schema 校验失败的修复提示现在回显具体校验错误（`src/agent.py`），提高修复轮成功率。

**指标**：召回 16/22 = 73%（降级按失败计）✅ 踩线；违禁行为 0 ✅；正常 case 误报 2/3 = 67% ❌（待 Round 6 验证修复）；5 例降级为免费档基础设施噪声。

## 基线（规则系统）对比（§9.3）

**方法**：`python -m src.baseline --date <锚定日>`，与 Agent 共用同一套检测规则（detect_anomalies 的 5 条规则），但无 LLM 判断层：无置信度校准、无追踪/投放失效区分、无冷启动抑制、无放量评估。抽样 3 个锚定日：

| 锚定日 | 基线输出 | 与 Agent 的关键差异 |
|---|---|---|
| 2026-06-21 | 11 条 finding，全部 high | C002 追踪丢失被报为"转化骤降 anomaly high"——无法区分追踪异常与投放失效；C001 单日转化 6→1 的小基数噪声同样 high |
| 2026-06-25 | 8 条 finding，全部 high | C004 个位数转化波动（3→0、11→4）全部 high——典型小基数误报；C004 缺 06-22 数据但对涉及该窗口的结论无任何置信度折损 |
| 2026-06-28 | 4 条 finding，全部 high | C003 冷启动（累计 24 点击）消耗 $4.4→$7.7 被报 high——冷启动小基数误报 |

**结论**：基线的注入模式召回尚可（C001/C002/C004 缺口/C005 均能命中），但**所有 finding 一律 high 置信度**，抽样 3 天约 23 条 finding 中近半属于噪声或错误定性（追踪丢失当转化骤降、冷启动波动当异常）；且无 scale_up 放量建议、否词机会只有现象无判断。Agent 的增量价值正是规则之外的判断层：置信度校准（小基数/冷启动压 low）、追踪状态定性（type=tracking）、数据缺口显式声明与结论折损、主动放量评估。这正是 §9.2 误报率指标（正常 case 误报 ≤20%）只有 Agent 能达标的原因。

## Round 7 / 7b（2026-10-12，正式基线；eval ID: eval-5Ql-2026-10-12T13:19:13 及 7b 复测）

**评测对象**：agent v1.1（detect_anomalies 单次双区间调用 + 小基数/放量/自检/封顶全套提示词）+ deepseek-v4-flash，并发 5。评测集 `cases.v1.0.frozen.json`（tag `v1.0-eval-freeze`）。Round 1-6 为开发期数据（免费档限流污染），仅供参考。

**过程**：Round 7 首跑 24/25（case-25 因 none/high 被旧断言误判 → D-03）；按新口径重评 22/25（正常 case 报 anomaly/low、case-18/20 tracking/high、low 缺压低依据）→ 三项提示词修复（D-05）→ Round 7b 首跑 7/25（兜底断言与强制措辞"整体降级"碰撞 → D-06 框架缺陷，修正断言标记后离线重评）。

### §9.2 四条验收线（Round 7b，修正断言后）

| 验收线 | 数值 | 判定 |
|---|---|---|
| 关键发现召回率 ≥70% | 22/22 = 100% | ✅ |
| 正常 case 误报率 ≤20%（anomaly 数必须为 0） | 0/3 = 0% | ✅ |
| 违禁行为 = 0（一票否决） | 0 次 | ✅ |
| (a) Finding 级校准 ≥90%（low 带数据不足依据） | 84/84 = 100% | ✅ |
| (b) Case 级保守性（冷启动/缺数据 high 数 = 0） | 0 条 | ✅ |

**总分 25/25，四条线全过。** 旧指标"标注 low 的 case 中确有数据问题比例"已废弃（见附录 A）。

### 分类别拆解

| 类别 | 通过/总数 |
|---|---|
| 异常消耗 | 5/5 |
| 否词机会 | 5/5 |
| 放量建议 | 4/4 |
| 冷启动 | 3/3 |
| 数据缺失 | 3/3 |
| 追踪丢失 | 2/2 |
| 正常对照 | 3/3 |

### 每 case 明细（耗时 / LLM 往返 / findings 构成）

| case | 类别 | 耗时s | 往返 | findings |
|---|---|---|---|---|
| case-01 | cost_spike | 39 | 4 | anomaly/medium×1, negative_keyword/medium×5, none/low×1 |
| case-02 | cost_spike | 91 | 5 | anomaly/medium×1, negative_keyword/medium×5, none/low×2 |
| case-03 | cost_spike | 40 | 4 | anomaly/medium×1, negative_keyword/medium×4, none/low×1 |
| case-04 | cost_spike | 52 | 3 | anomaly/medium×1, anomaly/low×1, negative_keyword/medium×3, none/medium×1 |
| case-05 | cost_spike | 76 | 4 | anomaly/medium×2, negative_keyword/medium×4, none/low×1 |
| case-06 | negative_keyword | 52 | 4 | tracking/low×1, anomaly/low×2, negative_keyword/low×3, scale_up/low×1 |
| case-07 | negative_keyword | 39 | 4 | tracking/low×1, anomaly/low×1, negative_keyword/low×2, scale_up/low×1, none/low×2 |
| case-08 | negative_keyword | 63 | 4 | tracking/low×1, none/low×2, negative_keyword/low×2, scale_up/low×1 |
| case-09 | negative_keyword | 49 | 4 | anomaly/low×1, negative_keyword/low×1, scale_up/low×1, none/low×3 |
| case-10 | negative_keyword | 40 | 4 | scale_up/medium×1, negative_keyword/medium×1, anomaly/low×1, none/low×2 |
| case-11 | scale_up | 40 | 5 | negative_keyword/medium×5, negative_keyword/low×1, none/low×1 |
| case-12 | scale_up | 37 | 5 | none/low×1, negative_keyword/medium×5, negative_keyword/low×1 |
| case-13 | scale_up | 28 | 5 | negative_keyword/medium×5, negative_keyword/low×1, none/low×1 |
| case-14 | scale_up | 55 | 4 | none/low×1, negative_keyword/medium×7 |
| case-15 | cold_start | 64 | 5 | tracking/low×1, negative_keyword/low×1, scale_up/low×1, none/low×2 |
| case-16 | cold_start | 73 | 4 | tracking/low×1, negative_keyword/medium×1, scale_up/medium×1, none/low×2 |
| case-17 | cold_start | 58 | 5 | negative_keyword/medium×1, scale_up/medium×1, none/low×2 |
| case-18 | data_gap | 66 | 5 | tracking/low×1, anomaly/low×2, negative_keyword/low×6, scale_up/low×1 |
| case-19 | data_gap | 56 | 5 | tracking/low×1, anomaly/low×2, negative_keyword/low×3, scale_up/low×1, none/low×1 |
| case-20 | data_gap | 47 | 5 | tracking/low×1, negative_keyword/low×2, scale_up/low×1, none/low×1 |
| case-21 | tracking | 93 | 5 | tracking/low×1, anomaly/low×2, negative_keyword/medium×7, none/low×1 |
| case-22 | tracking | 70 | 4 | tracking/low×1, anomaly/medium×1, negative_keyword/medium×7, scale_up/medium×1 |
| case-23 | normal | 25 | 4 | negative_keyword/medium×2, none/low×1 |
| case-24 | normal | 37 | 5 | negative_keyword/medium×6, none/low×1 |
| case-25 | normal | 29 | 4 | negative_keyword/medium×5, negative_keyword/low×1, none/low×1 |

**效率**：平均 53s/case、**4.4 次 LLM 往返**（Round 6 基线 5.9 次 ↓25%，并行下钻指令生效）；全轮 4m54s（对比 Round 5 的 1h38m）。正常对照 case 的 anomaly finding 数为 0（修复一生效）；数据缺口窗口全部触发"整体降级"声明且 findings 压 low（修复二生效）；全部 84 条 low finding 带四关键词压低依据（修复三机检通过）。

### 评测框架缺陷发现与修复（本轮共 3 处，详见 DECISION_LOG）

1. **D-03**：正常 case 断言白名单缺 none → case-25 的 none/high 被误判；修复后同时补强"正常 case anomaly 数必须为 0"。
2. **D-05 修复三配套**：low finding 压低依据从模型自觉升级为机器强制（LOW_REASON_ASSERT 四关键词校验）。
3. **D-06**：兜底断言匹配词"降级"与 D-05 强制措辞"整体降级"碰撞，Round 7b 首跑 18 例误判；断言标记精确化为"诊断运行失败"。教训：提示词引入强制措辞须同步检索断言库。

### 附录 A：废弃指标留档

规格 §9.2 原指标"标注 low 的 case 中确有数据问题的比例 ≥ 90%"经 D-04 裁定废弃：字面口径是评测集自身属性（9 个 low case 中 6 个有数据问题 = 67%），无法作为 agent 验收线。Round 7 按工程解读（low case 上 agent 不乱给 high）曾算得 **78%**（7/9，失分于 case-18/20 的 tracking/high），该数字随旧指标一并废弃，仅留档。替代指标为 (a)(b) 两条（见上表）。

## 泛化验证（留出集 cases.v1.1，2026-10-12）

**方法**：5 个全新 case（`evals/cases.v1.1.holdout.json`，锚定日 06-06/07/08/20 均未出现在 v1.0；含新异常组合与 1 个接近阈值的刁钻正常 case），设计时未参考已有失败模式。Round 7b 达标后原样跑一遍，**结果无论过不过都如实记录，未据此回调任何提示词**。

**结果：3/5 通过（60%）**，原始结果 `evals/holdout_v1_1.json`。

| case | 锚定日 | 设计意图 | 结果 |
|---|---|---|---|
| case-h01 normal | 06-07 | 常规正常对照（窗口内 4 次小基数 detector 报警） | ✅ 无 anomaly finding |
| case-h02 normal_tricky | 06-06 | **刁钻正常**：-85.7% 环比的一天绝对减少仅 6 个 | ✅ 无 anomaly finding |
| case-h03 combo_anomaly | 06-20 | 组合异常定性（C001 突增+C005 反弹+C002 归零首日） | ❌ C002 被报 tracking/low |
| case-h04 tracking_boundary | 06-20 | 追踪丢失首日 streak=1，规则未触发，考验不抢跑 | ❌ C002 被报 tracking/low |
| case-h05 negkw_boundary | 06-08 | 否词边界：目标词差 4 点击未达门槛 | ✅ 未报该词，正确报了 2 个达标词 |

**失败分析（同一行为，归类「判断」）**：h03/h04 中 agent 在 C002 归零**首日**（streak=1，低于追踪规则 ≥2 天门槛、get_tracking_status 不会判 suspected_broken）就给出 type=tracking 的 finding——越过工具判定自行提前定性。两处置信度均为 low（未造成高置信误报），属于"低置信抢跑"。

**结论**：留出集暴露了 v1.0 未覆盖的一个真实边界弱点（追踪定性抢跑），以及两个刁钻 case（h02/h05）的正确通过。按规则未修复、未调提示词，此弱点记录为已知限制：单日复零首日 agent 倾向提前报 tracking/low，实战中等同于"提前一天的低置信预警"，风险可控但定性偏激进。

## Round F（2026-10-13，定稿轮；kimi-k2.6）

**评测对象**：agent v1.1（提示词与工具自 Round 7b 起零改动）+ **kimi-k2.6**。评测集 `cases.v1.0.frozen.json`（25 case）+ `cases.v1.1.holdout.json`（5 case）。原始结果 `evals/roundF.json` / `evals/roundF_holdout.json`。按定稿铁律：**结果原样入档，未据此回调任何提示词**。

**与 7b 的环境差异（如实记录）**：temperature=1（kimi-k2.6 服务端硬限制，7b 为 0.1）；并发=1（Moonshot 账号限额 concurrency 1 / RPM 3，7b 为 5）；provider 新增 429 降级重试。详见 D-07。

**过程**：三次环境性失败（系统 Python 缺依赖全 error；并发 5 两轮 429 风暴全降级）→ 并发 1 + 重试后 25 case 全部真实完成，零降级、零限流残留。

### §9.2 验收线（v1.0 冻结集）：4/5 通过

| 验收线 | 数值 | 判定 | 7b 对照 |
|---|---|---|---|
| 关键发现召回率 ≥70% | 19/22 = 86.4% | ✅ | 100% |
| 正常 case 误报率（anomaly 数必须为 0） | 0/3 = 0% | ✅ | 0% |
| 违禁行为 = 0（一票否决） | 0 次 | ✅ | 0 |
| (a) Finding 级校准 ≥90% | 55/56 = 98.2% | ✅ | 100% |
| (b) Case 级保守性（冷启动/缺数据 high = 0） | **2 条 high** | ❌ | 0 条 |

**总分 21/25。** (b) 线失败实质：kimi-k2.6 在 case-16（冷启动，06-29）与 case-20（数据缺口，06-25）对 C001 给出 **scale_up/high**，越过 D-05 置信度封顶规则（这两 case 的 promptfoo 断言均通过，(b) 为离线计算口径）。

### 失败 case 明细（4 个）

| case | 类别 | 失败断言 | 实质 |
|---|---|---|---|
| case-11 | scale_up | 输出未包含 C001 | 漏召回：聚焦 6 条否词，未覆盖 C001 放量候选 |
| case-12 | scale_up | 输出未包含 C001 | 同上 |
| case-14 | scale_up | 无 scale_up finding | 漏召回：ROAS 达标实体未给放量建议 |
| case-05 | cost_spike | low finding 缺压低依据 | 1 条 none/low 无四关键词（机检拦截）；关键异常本身已召回 |

### 每 case 明细（耗时 / LLM 往返 / findings 构成）

| case | 类别 | 耗时s | 往返 | findings |
|---|---|---|---|---|
| case-01 | cost_spike | 130 | 4 | anomaly/low×2, negative_keyword/medium×5 |
| case-02 | cost_spike | 158 | 4 | anomaly/medium×1, negative_keyword/medium×5 |
| case-03 | cost_spike | 126 | 4 | anomaly/medium×1, none/low×1, negative_keyword/medium×4 |
| case-04 | cost_spike | 544 | 4 | anomaly/medium×2, negative_keyword/medium×3 |
| case-05 | cost_spike | 108 | 4 | none/low×4, negative_keyword/medium×4 |
| case-06 | negative_keyword | 163 | 4 | tracking/low×1, anomaly/low×1, negative_keyword/low×3, scale_up/low×1 |
| case-07 | negative_keyword | 307 | 5 | tracking/high×1, anomaly/medium×1, anomaly/low×1, negative_keyword/medium×3, none/low×2 |
| case-08 | negative_keyword | 193 | 4 | tracking/low×1, negative_keyword/low×3, scale_up/low×1, none/low×2 |
| case-09 | negative_keyword | 412 | 4 | anomaly/low×1, negative_keyword/low×1, scale_up/low×1, none/low×3 |
| case-10 | negative_keyword | 295 | 4 | negative_keyword/high×1, scale_up/high×1, none/low×1 |
| case-11 | scale_up | 151 | 4 | negative_keyword/medium×6 |
| case-12 | scale_up | 198 | 4 | anomaly/low×1, negative_keyword/medium×6 |
| case-13 | scale_up | 159 | 4 | negative_keyword/medium×6, none/low×1 |
| case-14 | scale_up | 347 | 4 | negative_keyword/high×1, negative_keyword/medium×4, none/low×1 |
| case-15 | cold_start | 191 | 4 | tracking/low×1, anomaly/low×2, negative_keyword/low×1, scale_up/low×1 |
| case-16 | cold_start | 189 | 4 | negative_keyword/medium×1, **scale_up/high×1**, none/low×1 |
| case-17 | cold_start | 295 | 4 | negative_keyword/medium×1, scale_up/medium×1, none/low×1 |
| case-18 | data_gap | 179 | 4 | tracking/low×1, anomaly/low×1, negative_keyword/low×1, scale_up/low×1 |
| case-19 | data_gap | 163 | 4 | tracking/low×1, anomaly/low×1, negative_keyword/low×3, scale_up/low×1 |
| case-20 | data_gap | 307 | 5 | tracking/medium×1, negative_keyword/low×2, **scale_up/high×1** |
| case-21 | tracking | 691 | 4 | tracking/high×1, anomaly/medium×2, negative_keyword/medium×2, negative_keyword/low×1 |
| case-22 | tracking | 809 | 4 | tracking/low×1, negative_keyword/low×1, negative_keyword/medium×1 |
| case-23 | normal | 175 | 4 | none/low×2, negative_keyword/medium×2 |
| case-24 | normal | 138 | 4 | negative_keyword/medium×6 |
| case-25 | normal | 198 | 4 | negative_keyword/medium×6 |

**效率**：平均 265s/case、**4.1 次 LLM 往返**、每 case 约 1.9 万 input + 0.8 万 output token；全轮 1h47m（并发 1 受账号限额制约）。对比 7b（deepseek）：53s/case、4.4 往返、4m54s（并发 5）。kimi-k2.6 思考链使 output token 约为 deepseek 的 3 倍，单 case 延迟约 5 倍。

### v1.1 留出集：2/5

| case | 设计意图 | 结果 | 7b 对照 |
|---|---|---|---|
| case-h01 normal | 常规正常对照 | ✅ | ✅ |
| case-h02 normal_tricky | 刁钻正常（-85.7% 环比、绝对减少仅 6） | ❌ 1 条 none/low 缺压低依据（机检） | ✅ |
| case-h03 combo_anomaly | 组合异常定性 | ❌ C002 归零首日报 tracking/low（同 7b 的已知弱点） | ❌ 同 |
| case-h04 tracking_boundary | 追踪首日不抢跑 | ❌ tracking/**medium**（比 7b 的 low 更激进） | ❌ tracking/low |
| case-h05 negkw_boundary | 否词边界 | ✅ | ✅ |

### Round F 结论

1. **4/5 验收线通过，(b) Case 级保守性未过**：kimi-k2.6 在冷启动/数据缺口场景对高 ROAS 实体（C001）敢给 scale_up/high，越过 D-05 封顶规则；deepseek-v4-flash 在同提示词下零越界。
2. **模型行为画像**：deepseek 偏保守（medium/low 为主），kimi-k2.6 更敢给 high/medium——召回 86.4% vs 100%、保守性越界 2 条、校准 98.2% vs 100%。同一份提示词下两模型均可运行，但严格按 §9.2 全口径，**deepseek-v4-flash 仍是唯一四线全过的定稿配置**。
3. 已知弱点（追踪定性抢跑，h03/h04）在两模型上复现一致，证实该弱点属提示词/规则层而非模型个体差异，维持"已知限制"结论。
4. 按铁律未回调提示词；本报告与 README 评测表如实记录两组数字，7b 保留为对照行。

## 对照实验 Round F2（2026-10-13，deepseek-v4-flash @ temperature=1）

**目的**：隔离 Round F 的混淆变量。kimi-k2.6 只接受 temperature=1，而 7b 用 0.1——k2.6 的 (b) 线越界究竟是模型本身的规则遵循问题，还是高温所致？

**设置**：agent v1.1 提示词与代码零改动，唯一变量 temperature 0.1→1（shell 环境变量 `LLM_TEMPERATURE=1` 注入，.env 与代码均未改动）；deepseek-v4-flash，并发 5，v1.0 冻结集 25 case。原始结果 `evals/roundF2.json`。

### 结果：25/25，四条线全过

| 验收线 | 数值 | 判定 |
|---|---|---|
| 关键发现召回率 ≥70% | 22/22 = 100% | ✅ |
| 正常 case 误报率（anomaly = 0） | 0/3 = 0% | ✅ |
| 违禁行为 = 0 | 0 次 | ✅ |
| (a) Finding 级校准 ≥90% | 91/91 = 100% | ✅ |
| (b) Case 级保守性（high = 0） | 0 条（**全场 25 case high 总数为 0**） | ✅ |

全轮 4m31s（与 7b 的 4m54s 相当）。temperature 升至 1 后 deepseek 反而更保守——全场未产出任何 high finding，D-05 封顶规则零越界。

### 结论

**temperature=1 不破坏 deepseek 的规则遵循**，Round F 中 kimi-k2.6 的 (b) 越界与召回下滑不能归因于其 temperature 硬限制，差异在模型本身的规则遵循能力。混淆变量排除，选型依据成立。

## 模型选型决策（定稿）

1. **原计划**：按 MODEL_ROUTING.md 的路由表，最终定稿轮用旗舰模型 kimi-k2.6 跑全量，数字作为 README 定稿行。
2. **受控对比推翻原计划**：Round F（k2.6）21/25、(b) 线 2 条 scale_up/high 越过 D-05 封顶规则、召回 86.4%；Round F2（deepseek @ temp=1）25/25 四线全过，证明 k2.6 的失败源于模型本身而非高温。
3. **选择依据**（deepseek-v4-flash 全面胜出）：
   - 规则遵循：四线全过（含 temp=1 对照）vs k2.6 保守性越界 2 条
   - 速度：53s/case、并发 5 vs 265s/case、并发 1（账号限额）
   - 成本与稳定性：付费档无限流 vs concurrency 1 / RPM 3 硬限额；output token 量 k2.6 约为 3 倍（思考链）
4. **最终裁定**：**生产定稿配置 = agent v1.1 + deepseek-v4-flash @ temperature=0.1（Round 7b）**。kimi-k2.6 不作生产配置，Round F 数字原样留档作对照；禁止为让 k2.6 通过而回调任何提示词。
5. **混淆变量如实声明**：k2.6 无法与 7b 在同一 temperature 下对比（服务端只接受 1），两轮对比的温度不对称（0.1 vs 1）；F2（deepseek @ temp=1 仍全过）是对该不对称性的补强证据，但严格说三方的运行条件（并发、限额）也不完全一致，结论以规则遵循差异为主、效率差异为辅。
