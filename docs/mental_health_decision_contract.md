# E3b 策略选择契约实验

更新：2026-09-23。状态：E3b开发与一次保留验证完成，候选未通过关键边界门槛。生产 Decision 客户端与默认规则配置未修改。

## 改动范围

新增 `scripts/decision_contract.py` 实验提示，中文直接列出策略与次策略的适用条件及优先顺序：当前 Safety → 实际结束 → 拒绝建议/倾诉 → 明确实际求助 → 澄清/负面反馈 → 当前强烈不适 → 普通聊天。同时说明不可信协议指令、状态估计不等于诊断、历史来源与新鲜度、上一轮策略与可执行能力的边界。

三组均经实际生产客户端构造基础请求、严格解析，再执行本机协调：

| 组 | 系统提示 | 状态策略标签 | 解码schema与生成参数 |
|---|---|---|---|
| baseline | 原始展示schema，含default | 保留 | 相同 |
| both | 原始展示schema去default | 移除 | 相同 |
| contract_v1 | 中文策略契约＋完整必填schema | 移除 | 相同 |

因此 contract_v1 对 both 的差别是整段系统提示包，包括语言、顺序说明、schema展示格式；不能将收益单独归因于中文、某个词或某条规则。没有为每个输入预先写入“正确策略”，模型看不到实验标签。契约借鉴确定性协调规则，命中率也不能证明模型比规则更有价值。

实验模型沿用 Qwen2.5-1.5B-Instruct Q4_K_M / llama.cpp CPU，temperature=0、max_tokens=300、请求seed=20260923、总期限15秒、SDK不重试。只发送新旧虚构案例，不读取真实用户历史，不调用Dialogue。

## 开发筛查

使用E3a已公开的10例开发场景，三组各一次，共30场景/27正式请求/3Safety零调用；另2次预热单列。

| 组 | 原始策略匹配 | 协调后匹配 | 合法请求 |
|---|---:|---:|---:|
| baseline | 6/9 | 9/9 | 9/9 |
| both | 8/9 | 9/9 | 9/9 |
| contract_v1 | 9/9 | 9/9 | 9/9 |

新契约正确处理了该轮求助、结束、澄清，倾诉没有退化；仅一次筛查，不称为稳定性或泛化验证。27次实际请求边界、原始/解析/协调核对通过。记录：`logs/evaluation/e3b-contract-dev-20260923/`。报告SHA256：`a938ce1d8a1294861ebc6f7cc4484e36ac282079ca132c707bca77069861dba8`。

## 冻结与保留集

候选冻结文件 `logs/evaluation/e3b-candidate-freeze-20260923.json`，SHA256 `61f3a8ded22663046b790630f1890bd630941380a96ee550e897e1413ad05135`。冻结包含实验执行器、候选提示、复用的E3a执行器和心理模块源码哈希。之后新增 `tests/fixtures/decision_contract_holdout.json`，绑定该冻结文件。

保留集12个新措辞案例，含自然求助、明确拒绝建议、实际结束、他人引用结束、澄清、强烈不适、有效/陈旧历史、协议操控和2类风险。与开发集部分诉求家族相同，由同一开发流程编写，属于内部小型保留检查，不是独立第三方或临床外部验证。

三组各三次，实际完成108场景、90正式请求/18Safety零调用，另2次预热成功。冻结候选只允许启动一次保留运行；即使运行中失败，也留下已曝光标记。未用保留结果调参后覆盖旧结果。

预设工程筛查门槛：候选原始匹配率≥90%，合法率≥95%；自然/明确求助、拒绝建议、实际/引用结束、协议操控每次均匹配；所有组的风险案例零调用。分母包含所有计划的正常场景，超时/回退不能通过缩小分母提高命中率。通过仍不意味着Dialogue质量改善或适合默认启用。

## 操作命令

在仓库根目录执行，Decision服务需已在127.0.0.1:8001启动。输出路径必须不存在。

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe scripts/evaluate_decision_contract.py run `
  --fixtures tests/fixtures/decision_diagnostic_cases.json --split development --repeats 1 `
  --output logs/evaluation/e3b-dev-new

# 开发完成后冻结，然后才能创建绑定该冻结文件的新保留fixture。
.\.venv\Scripts\python.exe scripts/evaluate_decision_contract.py freeze `
  --output logs/evaluation/e3b-new-freeze.json

# 已运行的冻结候选不能重复使用；下面展示参数，不用于反复重测现有保留集。
.\.venv\Scripts\python.exe scripts/evaluate_decision_contract.py run `
  --fixtures tests/fixtures/decision_contract_holdout.json --split holdout --repeats 3 `
  --freeze logs/evaluation/e3b-candidate-freeze-20260923.json `
  --output logs/evaluation/e3b-holdout-new

.\.venv\Scripts\python.exe scripts/validate_decision_contract.py `
  --experiment logs/evaluation/e3b-contract-holdout-20260923 `
  --output logs/evaluation/e3b-contract-holdout-20260923/validation.json
```

校验器检查完整调度、逐次结果、实际请求变更范围、重复请求一致性、原始与解析结果、本机协调、汇总计数及预设门槛。校验器与模型实验源码分开，开发过程中补充校验不会改变冻结候选；每份校验结果另记录校验器哈希。

## 工程验证与结果边界

6项专项及152项完整回归通过，Ruff检查通过，记录 `logs/phase-e3b-final-tests.txt`。覆盖真实转发请求记录、候选变更边界、Safety零调用、冻结/重复保留拒绝、篡改拒绝及门槛统计。生产配置保持规则Decision，E1/E3a基线与E2未填评分原样保留。

## 保留集最终结果

| 组 | 原始策略匹配 | 协调后匹配 | 合法请求 |
|---|---:|---:|---:|
| baseline | 18/30 | 24/30 | 30/30 |
| both | 19/30 | 24/30 | 30/30 |
| contract_v1 | 27/30 | 27/30 | 30/30 |

候选原始匹配率90%、合法率100%，但 `h-help-natural` 三次均失败，未满足预设关键案例全匹配门槛，`screening_gate.status=failed`。没有回退或截断。明确求助、实际结束、澄清各3/3；拒绝建议、他人引用结束、协议操控均3/3且未出现本批退化。两种历史输入均选择倾听，不能据此证明长期状态带来了收益。

冻结输入中 `h-help-explicit` 与 `h-help-natural` 的结构化诉求均为 unknown/unspecified，而新契约三次都能处理较明确的前者，三次都未处理自然询问“从哪一封开始比较合适”的后者。本机协调器也未能补救后者；因此不能把unknown简单解释为用户无诉求，或声称协调器可以补救所有语义失败。

记录位于 `logs/evaluation/e3b-contract-holdout-20260923/`。90次实际请求边界、30个案例×变体组的重复请求一致性、原始/解析/协调和计数均核对通过。报告SHA256：`5561c554e9b14ad9499871d8f03069fb5ae54e53dcaeb22124d5046f7bf26b9e`；manifest SHA256：`1d032019b4520560ef118342f3dc30bb89efc913d0c656cda4181bc8a4e0141e`。

本批合计：开发30＋保留108＝138场景运行，117正式模型请求、21次Safety零调用，另4次预热；全为虚构数据。一次开发筛查和小型内部保留集不能证明对话质量或临床效果。

## 下一批 E3c

在新的开发材料上处理自然诉求与unknown边界：区分明确求助、间接求助、反问/描述/他人引用，以及拒绝建议；记录本机识别、模型原始选择与协调各层的贡献。候选应理解unknown代表估计器未确定，而不能自行推断为同意建议；明确拒绝仍优先。不要只给本批失败句增加一个专用关键词规则。下一版冻结后使用另一套保留检查，本批已曝光结果作为历史失败回归保留，不再称为新保留验证。

候选 `contract_v1` 继续仅供实验，未接入线上。人工评分和真人体验继续后置。
