# E1：认知与协同决策对照

更新：2026-09-23。E1a ORPO 与 E1b SFT 自动对照均完成；E2 人工质量评价与真人体验继续后置。自动策略匹配不等于回答质量提高。

## 冻结设计

沿用 A/C/D 已完成的实现，本批不根据保留集结果修改业务规则。新增实验脚本使用同一 MentalHealthAgent、上下文 Safety v2、输出 Safety、表达能力约束和临时 SQLite；原有历史报告协议保留。

| 分组 | Decision | 结构化诉求 | 结构化长期状态 |
|---|---|---|---|
| R0 | 规则 | 开 | daily_v2 |
| R1 | 独立模型 | 开 | daily_v2 |
| R2 | 同 R1 模型 | 置 unknown | daily_v2 |
| R3 | 同 R1 模型 | 开 | 禁止读取 |
| R4 | 同 R1 模型 | 开 | rolling_v1 |

- `tests/fixtures/coordination_cases.json`：8 个虚构场景、11 轮。开发集 4 个场景包括偏好转换、负面反馈、即时风险、合成故障；保留集 4 个场景包括历史下收尾、持续多日历史、同日高频历史、明确风险否认。语义家族不交叉。标签由开发者给出，并非独立临床标注或完全盲测。
- 每组 3 次重复，共 120 个场景运行、165 轮。按固定 order_seed=20260923 随机排列场景，每个场景的五组再随机排序；多轮场景内部维持原次序，组间不共享会话或数据库。
- 虚拟参考时间固定为 2026-09-23T12:00:00+08:00，每轮推进 1 秒。相同组别条件之外的历史日期、分数与话题完全相同，真实执行日期不会把合成历史推进另一日。
- 两服务在计分前各预热 5 次，全部保存并排除评分/主体时延。ORPO 温度 0、最多 384 token；Decision 温度 0、最多 300 token、15 秒超时、llama_json_schema；SDK 重试为 0。
- Decision 请求 seed=20260923；Dialogue 服务未确认统一种子能力，不发送 seed，也不宣称逐字确定性。报告保留 requested seed、返回模型名、system_fingerprint（若提供）、usage、finish_reason 和请求哈希。
- 冻结包包括源码/样例/角色提示词哈希、基座分片和适配器权重哈希、Decision 权重/执行文件/部署清单哈希。原始配置密钥不导出。
- 真实运行暂停本项目网页服务与构建任务，模型 API 保持运行。仍未隔离全机所有后台负载，不作严格性能容量结论。

## 测量与解释

每轮记录：输入 → 当前状态与诉求来源 → 完整趋势与版本 → Decision 提议 → 协调原因/最终策略 → 输出 Safety/协议覆盖 → 最终文本、Actions 参数和存储后的 trace。输入 Safety 直接响应的轮次没有模型调用；以 trace 的最终策略为准，避免把未执行的默认状态字段当成真实策略。

实际 API 请求单独计数，与 Decision 客户端调用、规则计算、合成故障区分。合成故障不进入正常模型合法率或性能比较。每个请求保存原始模型回答、截断/异常；本机改写与最终回答也单列。完整轮次时延包含 Agent、安全处理与状态持久化，排除初始化、报告输出、TTS 和播放；请求时延是 SDK await 的时间。

自动指标覆盖策略标签匹配、拒绝建议的策略遵守、策略重复、Safety 标签与高风险调用、输出改写、请求失败/截断、来源计数及时延分布。策略重复本身不是质量失败；诊断性语言和违反偏好的文本质量仍由人工引用证据评阅，不能把未触发规则检测等同安全有效。

### 混杂与边界

1. R2 消融了结构化诉求及由其驱动的协调，但原始输入和原始多轮文本对两个模型仍可见，因此模型可以自行理解拒绝建议或收尾；不是“没有任何诉求信息”的条件。
2. R3 不读结构化状态，仍保留本场景内聊天历史；测试的是结构化跨历史状态贡献，不是完全失忆模型。
3. R4 同时恢复 v1 的按条聚合与历史输入表示；R1/R4 差异是整套统计表示的总效应，不能单独归因于日均公式。
4. 多轮后续输入是预先固定的虚构文本，不是对各组回答的真人反馈；回答可能改变后续聊天上下文。成对比较按场景/轮次/重复对齐。
5. 无标签的历史案例只比较策略/文本分歧，不按规则基线给模型制造“正确答案”。没有人工评分时，不输出支持性、连贯性、诉求适配的优劣排名。

## 工程验证

本批新增 5 项实验测试与 2 项跨模型比较/混合匿名评阅测试，完整后端 **127 项通过**，Ruff 通过。测试覆盖均衡和可复现的调度、家族隔离、五组均经过 Agent/Safety、R2/R3/R4 消融生效、高风险零请求、只写新报告、完整运行/哈希/指标检查、跨模型条件差异拒绝及匿名评阅材料。`--dry-run` 仅用作工程检查，导出器默认拒绝把它当真实模型结果。完整日志为 `logs/phase-e1-final-tests.txt`。

源码冻结：`private/baselines/mental-health-e1-before-models-20260923.zip`，332 文件，SHA256 `d8f63bf6282ba3c3a31cb643443f2d39d2aebf687e10071f006bc4e4cdcb8ac7`。真实实验启动时还会写独立 manifest，并在结束时核对冻结源码没有改变。

## 运行结果

ORPO 实验目录：`logs/evaluation/e1-orpo-20260923/`；导出目录：`logs/evaluation/e1-orpo-20260923-export/`。三次重复全部完成，165 轮无流程错误或截断，108 次正常 Decision 请求全合法、无非注入故障回退；150 次 Dialogue 请求。另有预热5次 Decision/5次 Dialogue，排除主体统计。15 个高风险轮次零模型调用，15 个注入故障轮次均正确回退，单独计数。

| ORPO 分组 | 有策略标签轮次 | 策略不符 | 正常 Decision / Dialogue 请求 | Decision 请求均值 / p95 秒 |
|---|---:|---:|---|---|
| R0 | 24 | 0 | 0 / 27 | — |
| R1 | 24 | 0 | 27 / 27 | 6.911 / 8.604 |
| R2 | 24 | 12 | 27 / 27 | 6.573 / 8.185 |
| R3 | 24 | 0 | 27 / 27 | 4.779 / 5.530 |
| R4 | 24 | 0 | 27 / 27 | 6.297 / 7.918 |

表内正常统计不含各组3个注入故障轮次；各组另含3个高风险固定响应轮次。R2 的不符涉及改为寻求建议、负面反馈和结束对话等策略；标签匹配只验证路由。其他组的本机诉求协调参与最终策略选择，因此不能把 0 次不符全部归功于独立模型。

### ORPO 首轮暴露的实际限制

- R1 的27次正常模型提议全部是 supportive_listening；本机协调改变其中12次，覆盖求助、负面反馈和结束等诉求。R2 取消结构化诉求之后，这些覆盖消失，对应12次策略不符。R3/R4 的模型提议也全部为 supportive_listening。
- R0 的27次规则提议中，21次 supportive_listening、6次 reflect_and_clarify；其中12次同样被本机诉求协调覆盖。R1/R0 最终策略只有3轮不同，来自无预设“正确策略”的历史条件，不能据此宣布模型更好。
- R1/R3 与 R1/R4 各30个正常对齐轮次中，最终策略差异均为0；回答文本分别有27轮不同。只能报告文本差异，尚不能把长期状态或 daily_v2 的工程统计改进解释为已证实的对话收益。
- 当前得到支持的是这些固定工程样例上的“结构化诉求 + 确定性协调”路由作用。独立 Decision 模型存在策略提议单一的问题，且增加请求时延。主配置继续用规则；后续若改进模型提议，须另建开发样例并重新冻结，不能在本轮保留结果上调参后替换失败记录。

### SFT 复查与最终交付

SFT 第二轮同样完成120个场景运行/165轮，108次正常 Decision 请求全合法、150次 Dialogue 请求，无流程错误/接口错误/截断；高风险15轮零模型调用，注入故障15轮均回退。预热另记5次 Decision/5次 Dialogue。R2策略不符12/24，其他各组0/24，与 ORPO 一致；R1 的27次正常模型提议也全部为 supportive_listening。

两套实验合计330轮、216次正常 Decision 请求、300次 Dialogue 请求；另有20次预热请求。共享源码/样例/角色提示词/调度/生成控制/Decision权重/基座权重已通过程序一致性校验。各组30个正常跨模型对齐轮次中，最终策略差异都是0、最终回答差异都是27；3个固定 Safety 回复相同。顺序运行仍有负载/服务状态混杂，不据此排名速度或质量。

| 交付 | 路径 |
|---|---|
| ORPO 原报告与120份逐场景记录 | `logs/evaluation/e1-orpo-20260923/` |
| ORPO 逐轮轨迹、自动指标与匿名表 | `logs/evaluation/e1-orpo-20260923-export/` |
| SFT 原报告与120份逐场景记录 | `logs/evaluation/e1-sft-20260923/` |
| SFT 逐轮轨迹、自动指标与匿名表 | `logs/evaluation/e1-sft-20260923-export/` |
| 跨模型校验、成对比较、330条混合匿名表 | `logs/evaluation/e1-model-comparison-20260923/` |
| 配置环境版本快照 | `logs/evaluation/e1-runtime-20260923.json` |

ORPO report.json SHA256：`fbce4b7b2653dc0437e3fa1fcfef50ecd4b6cd22df8833dc9f91a3883a5a2323`；SFT：`22c67ac1a0089bb4c76d0312f149b06974693f689ed3bf99d5d0a558cf7e40ba`。混合评阅表330项，评分/事件标记全部为 null，模型/组别映射单独保存；没有自动代填人工评分。

环境快照：应用 Python3.10.11、OpenAI SDK2.15.0、Pydantic2.12.5；已配置的训练推理环境 torch2.8.0+cu128、transformers4.57.6、peft0.18.1、LLaMA-Factory0.9.6.dev0；Decision llama.cpp b10964。快照用于环境追溯，不代表隔离了整机负载。

实验后已恢复 ORPO 与网页，主配置仍为 context_v2 + daily_v2 + 规则 Decision。独立模型策略提议单一是明确未解决项，本批保留原始结果，没有围绕本轮保留集调参。

## 使用命令

```powershell
# 先暂停本项目网页服务；保持两个本机模型 API 在线。
# 该评估配置需要显式启用 Decision v2、context v2，并填写两个服务地址。
.\.venv\Scripts\python.exe scripts/evaluate_coordination.py --config private/decision/conf-context-v2.yaml --output-dir logs/evaluation/NEW_E1 --repeats 3
.\.venv\Scripts\python.exe scripts/export_coordination_trace.py logs/evaluation/NEW_E1 --output-dir logs/evaluation/NEW_E1_export
# SFT 完成后，校验并生成跨模型比较与混合匿名评阅表：
.\.venv\Scripts\python.exe scripts/compare_coordination_models.py logs/evaluation/ORPO_RUN logs/evaluation/SFT_RUN --output-dir logs/evaluation/NEW_PAIR
```

所有输出路径要求不存在，逐场景落盘；进程失败时 report.status=partial/pending，不能导出成完整比较。缺失真实服务不会退成 stub 完成实验。单次真实 Decision 超时/格式错误仍保留生产回退路径与实际失败记录。

导出内容：`summary.md` 自动指标与成对差异、`trace.jsonl` 全轮事实、`review-blinded.json` 去组别/模型名并随机排列的评分表、`review-key.json` 单独映射、`export-manifest.json` 文件哈希。每份评分表绑定原报告/manifest 哈希，所有评分和事件标记初始为 null；播放完成也是 null。两位评阅者可各用一份评分表，分歧处理留待 E2。

## 后续入口

E1 工程实验已完成。下一开发入口为 E2 的评分回填校验、双评阅者一致性/分歧表和成对评分汇总工具；实际人工评分与真人体验仍后置，不把空值视为零分或通过。独立 Decision 策略提议单一需要后续另建开发样例分析，保留本批冻结结果作为未调优基线；收益未证实前主配置保持规则 Decision。
