# 用户诉求与决策协调（A1/A2）

主计划：[心迹认知与协同决策升级计划](plans/2026-09-22-心迹认知与协同决策升级计划.md)。后续开发以该计划为准。

## 本轮实现

输入 Safety 检查原始输入；普通流程提取用户直接输入中的诉求，读取当前状态和历史趋势，再进行一次规则或模型 Decision。Decision 的提议经过本机协调器，随后进入 Dialogue 和输出 Safety。没有新增模型调用。

| 输入示例 | 最终策略 | 行为要求 |
|---|---|---|
| 我只想倾诉，先别给建议 | supportive_listening / reflect_feelings | 倾听、反映感受，避免主动安排解决步骤 |
| 请给我一个办法 | collaborative_problem_solving / offer_small_step | 提供一个小步骤 |
| 我想理清这件事 | reflect_and_clarify / explore_context | 澄清当前问题 |
| 今天先聊到这里 | close_supportively / acknowledge_closure | 简短收尾，不再追加问题 |
| 这个建议没帮助 | reflect_and_clarify / explore_context | 在没有更明确诉求时澄清需要，不重复原建议 |
| 明确高风险表达＋只想倾诉 | crisis_support | 输入 Safety 优先，跳过 Decision/Dialogue 模型调用 |

上述是工程策略和提示约束。对话生成仍可能不完全遵循；需查看实际回答，不能凭 strategy 字段判断效果已合格。

## 诉求与会话范围

`InteractionIntent` 包含 primary、advice_preference、certainty、source、preference_source、feedback、feedback_source、evidence_codes。字段固定枚举，不保存原文证据或模型推理。certainty 是 explicit/inferred/unknown，不是校准概率。

第一版为小型规则识别器：整分句匹配常见中英文表达；unknown 不推断为允许建议。明确引用、协议操控表达及剪贴板内容不用于设置偏好；Safety 仍处理完整输入，这不是引用或否定风险豁免。

建议偏好延续到当前聊天后续轮次，直到新的明确表达覆盖。历史切换或新 Agent 清除偏好，数据库中历史诉求不会自动恢复为当前用户意愿。当前识别以直接输入为准，没有泛化理解任意转述、双重否定或复杂混合意图，相关上下文升级安排在 C。

会话内“上一策略”指最近完成输出 Safety 的生成策略，不代表用户听完或认可。取消中的生成不提交新的偏好；迟到的旧历史结果不修改新历史偏好。用户明确说有帮助/没帮助才记录反馈；沉默、断线和打断不作为负反馈。

## 协调优先级与记录

当前优先级：明确安全风险 → 结束对话 → 拒绝建议 → 明确倾诉 → 明确求助 → 明确澄清 → 明确负反馈 → 内部控制命令的本机保守策略 → 保留 Decision 提议。

长期趋势和当前状态先由 Decision 使用；明确用户意愿可以覆盖其普通策略。DecisionResult 的模型输出仍只有 strategy、behavior、voice 三组。

本机 `decision_trace.coordination` 记录 proposed_strategy、final_strategy、previous_strategy、reason_codes 和协调协议版本。输出 Safety 覆盖后，final_strategy 同步为实际保守策略；trace 不接受模型填写，旧状态缺少该字段时保持 null。

C1 增加有限协议边界：明确内部控制命令从 Decision/Dialogue 当前输入和历史副本移除，完整原文仍交给 Safety，原聊天不被改写。仅含控制命令时，输出使用本机固定澄清，并记录 `output_policy_override=true` / `protocol_boundary_response`；这不代表模型生成质量通过，与 `output_safety_override` 分开。详情和限制见 [C 阶段记录](mental_health_phase_c_results.md)。

心理状态新增可选 interaction_intent；沿用兼容的状态存储。纠正与删除遵守原有用户/记录范围。纠正文件可以使用：

```json
{"interaction_feedback":"helpful"}
```

feedback 允许 helpful、unhelpful、unspecified。纠正后 feedback_source 为 user_correction，不改变原情绪估计可信度、历史时间或真实执行 trace，也不修改当前活动会话的偏好；删除记录时连同该条诉求和反馈删除。

## 协议兼容

配置路径：`character_config.agent_config.agent_settings.mental_health_agent.decision.protocol_version`。

- `2`（默认）：Decision 输入包含诉求和上一策略；模型允许 close_supportively 与 acknowledge_closure。
- `1`：显式使用旧模型协议，输入去掉新诉求字段、上一策略及 protocol_control_detected，模型输出拒绝 v2 的结束枚举并回退。协调器仍使用本机 v2 规则，可把旧提议转换成正确的本机结束策略。

`decision_trace.protocol_version` 表示配置的 Decision 契约；`decision_trace.coordination.protocol_version` 表示本机协调协议。旧 trace 的协议版本默认为 1，不能据此误判当前已有独立模型部署。

主配置的独立 Decision 仍关闭，使用规则默认；B 已有真实独立服务和显式评估配置，语义检查需结合 C 回测，不能把任一规则/固定回应计入模型生成质量成功。

## 检查与回放

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_user_intent.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_decision_coordination.py -v
.\.venv\Scripts\python.exe scripts/check_decision.py --rules-only --output logs/decision_phase_a.json
.\.venv\Scripts\python.exe scripts/evaluate_mental_health.py --fixtures tests/fixtures/user_intent_cases.json --output logs/evaluation/phase-a-intent.json
# 已运行 ORPO 服务时可追加真实对话；仍使用规则 Decision：
.\.venv\Scripts\python.exe scripts/evaluate_mental_health.py --dialogue model --fixtures tests/fixtures/user_intent_cases.json --output logs/evaluation/phase-a-orpo.json
```

10 个虚构样例包含 13 轮输入；其中高风险轮不调用模型。报告区分 proposed decisions、final_strategies 和 coordination_traces；expected_strategies 是开发暂定标签，匹配结果只验证策略路由。人工质量评分与播放完成不由本脚本填充。
