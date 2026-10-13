# MODEL_ROUTING.md

> 状态：已入库（2026-10-13）。注意第 3 节路由表为评测诊断期的**原计划**；
> 最终定稿轮（Round F/F2）已推翻"kimi-k2.6 定稿"一行——生产定稿配置为
> deepseek-v4-flash @ temperature=0.1，依据见 `evals/eval_report.md`
> "模型选型决策"一节。

## 0. 型号核实记录

本文件所有型号已于 **2026-10-12** 对照官方价格页核实，禁止凭记忆写型号：

| 型号 | 状态 | 来源 |
|---|---|---|
| deepseek-v4-flash | 真实在售，输入 ¥1.01/M、输出 ¥2.02/M（闲时半价） | [api-docs.deepseek.com 定价（经掘金 2026-07-28 转录）](https://juejin.cn/post/7667404454753812523)、[算力网型号页](https://www.suanlix.com/token/deepseek-v4-flash.html) |
| glm-4.7-flash | 真实在售，永久免费（1 并发），200K 上下文 | [智谱官方定价页](https://open.bigmodel.cn/pricing)、[财联社 2026-01-20 发布稿](https://www.cls.cn/detail/2263473) |
| kimi-k2.6 | 真实在售，输入 ¥6.50/M、输出 ¥27.00/M | [platform.moonshot.cn 定价（经算盘 2026-10-12 转录）](https://www.llmabacus.com/models/kimi-k2-6) |

纠错备注：此前草稿写的 glm-4.5 / glm-4.6 为凭记忆臆造的型号，已删除；glm-4.5-flash 曾真实存在，但已于 2026-01-30 下线（请求自动路由至 glm-4.7-flash），本项目 Round 1-6 实际跑的就是该旧型号。

> 数据来源：`trace.sqlite3`（runs / tool_calls 表），Round 1-5 共 25 case × 5 轮的完成记录。
> LLM 调用次数由 model_io_json 中 function_call 数 +1（最终回答）推得；LLM 平均延迟 = (运行总耗时 − 工具耗时) / LLM 调用次数。

## 1. 诊断结论表

| case_id | 类别 | 均耗时(s) | LLM调用次数 | 平均LLM延迟(s) | 工具调用次数 | 429/断连/解析错 | 瓶颈归类 |
|---|---|---|---|---|---|---|---|
| case-01 | cost_spike | 100 | 5.2 | 19.3 | 4.2 | 0/0/0 | 工具执行慢* |
| case-02 | cost_spike | 121 | 5.6 | 20.4 | 4.6 | 0/0/0 | 模型推理慢 |
| case-03 | cost_spike | 161 | 5.8 | 28.1 | 4.8 | 0/0/0 | 模型推理慢 |
| case-04 | cost_spike | 167 | 6.4 | 26.1 | 5.2 | 0/0/0 | 工具轮次过多 |
| case-05 | cost_spike | 185 | 5.8 | 31.7 | 4.8 | 0/0/0 | 模型推理慢 |
| case-06 | negative_keyword | 222 | 6.5 | 34.1 | 5.5 | 0/0/0 | 工具轮次过多 |
| case-07 | negative_keyword | 129 | 5.6 | 23.2 | 4.6 | 0/1/1 | 排队限流 |
| case-08 | negative_keyword | 112 | 5.8 | 20.0 | 4.8 | 0/0/0 | 工具执行慢* |
| case-09 | negative_keyword | 122 | 6.2 | 19.8 | 5.2 | 0/0/1 | 工具轮次过多 |
| case-10 | negative_keyword | 131 | 5.8 | 23.0 | 4.8 | 0/0/0 | 模型推理慢 |
| case-11 | scale_up | 129 | 6.2 | 20.0 | 5.2 | 0/0/0 | 工具轮次过多 |
| case-12 | scale_up | 118 | 6.1 | 19.2 | 5.1 | 1/0/0 | 排队限流 |
| case-13 | scale_up | 322 | 5.4 | 55.7 | 4.4 | 0/0/0 | 模型推理慢 |
| case-14 | scale_up | 174 | 6.4 | 24.8 | 5.4 | 0/0/0 | 工具轮次过多 |
| case-15 | cold_start | 188 | 5.7 | 34.7 | 4.7 | 0/1/1 | 排队限流 |
| case-16 | cold_start | 172 | 5.8 | 30.0 | 4.8 | 0/0/0 | 模型推理慢 |
| case-17 | cold_start | 131 | 5.8 | 23.0 | 4.8 | 0/0/0 | 模型推理慢 |
| case-18 | data_gap | 211 | 5.6 | 37.6 | 4.6 | 0/0/0 | 模型推理慢 |
| case-19 | data_gap | 222 | 6.5 | 34.1 | 5.5 | 0/0/0 | 工具轮次过多 |
| case-20 | data_gap | 129 | 5.6 | 23.2 | 4.6 | 0/1/1 | 排队限流 |
| case-21 | tracking | 184 | 5.7 | 32.5 | 4.7 | 1/1/0 | 排队限流 |
| case-22 | tracking | 313 | 6.0 | 52.9 | 5.0 | 0/1/0 | 排队限流 |
| case-23 | normal | 293 | 6.2 | 45.6 | 5.2 | 1/0/0 | 排队限流 |
| case-24 | normal | 98 | 6.7 | 14.4 | 5.7 | 1/0/0 | 排队限流 |
| case-25 | normal | 118 | 6.1 | 19.2 | 5.1 | 1/0/0 | 排队限流 |

\* case-01/08 按规则落入"工具执行慢"，但实测工具平均 50ms/次（最大 2.2s），运行耗时 95%+ 在 LLM 侧——这两例实为"模型延迟略低于 20s 阈值"，本质仍是模型推理慢。

## 2. 结论

**瓶颈分布（25 case）**：排队限流 9（36%）｜模型推理慢 8+2（40%，含 2 例误判）｜工具轮次过多 6（24%）｜真·工具执行慢 0（0%）

- **主要瓶颈在 LLM 侧，合计约 76%**：免费档平均单次推理 27s（峰值 55.7s），且 429 限流/断连导致 14 次降级运行。工具层（pandas 纯代码）平均 50ms，可忽略。
- 次要瓶颈是**工具轮次过多**（24%）：平均 5.9 次 LLM 调用 / 4.9 次工具调用才产出结果，每多一轮就多一次 20-50s 的推理延迟。
- 解决手段：
  - 限流 → 换不限流的付费模型（deepseek-v4-flash，闲时半价）
  - 轮次多 → 合并工具/批量取数减少往返（detect_anomalies 已重构为单次调用返回窗口+全量两区间）
  - 模型慢 → 换更快的模型（低价 flash 档推理慢是普遍现象；定稿用 kimi-k2.6 补指令遵循能力）

## 3. 模型路由表（按阶段）

| 阶段 | 用途 | 型号 | base_url | 理由 |
|---|---|---|---|---|
| 冒烟迭代（8-10 case） | 提示词/规则快速试错 | glm-4.7-flash（免费兜底） | https://open.bigmodel.cn/api/paas/v4 | 成本 ¥0，容忍偶发限流；失败重跑代价低 |
| 全量里程碑评测（25 case） | 验收口径数据 | deepseek-v4-flash（主力工作马） | https://api.deepseek.com/v1 | 付费不限流，消除 429 污染；价格低（输入 ¥1.01/M） |
| 最终定稿报告 | ~~交付物质量兜底~~ **已被 Round F/F2 推翻** | ~~kimi-k2.6~~ → 实际定稿：deepseek-v4-flash @ temp=0.1 | https://api.deepseek.com/v1 | k2.6 实测违反 D-05 封顶规则 2 次且召回/速度/成本全面劣势（详见 eval_report.md"模型选型决策"）；本行保留原样以存档决策演变 |

三个端点均为 OpenAI 兼容协议，代码零改动，只换 `.env`。注意各家需各家的 API Key。

## 4. .env 切换说明

`.env` 中只需改 3 个键（其余配置不变）：

```bash
# 冒烟迭代：智谱 glm-4.7-flash（永久免费，1 并发）
OPENAI_API_KEY=<智谱 API Key>
OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
MODEL_NAME=glm-4.7-flash

# 全量里程碑：DeepSeek deepseek-v4-flash（付费主力，闲时半价）
OPENAI_API_KEY=<DeepSeek API Key>
OPENAI_BASE_URL=https://api.deepseek.com/v1
MODEL_NAME=deepseek-v4-flash

# 最终定稿：Moonshot kimi-k2.6
OPENAI_API_KEY=<Moonshot API Key>
OPENAI_BASE_URL=https://api.moonshot.cn/v1
MODEL_NAME=kimi-k2.6
```

切换后无需重启任何服务，下一次 `python -m src.agent` 或 promptfoo 评测即生效。token 单价在 `src/config.py` 的 `PRICE_INPUT_CNY_PER_MTOK` / `PRICE_OUTPUT_CNY_PER_MTOK` 中按所选模型更新（参考第 0 节核实价格），成本核算自动生效。
