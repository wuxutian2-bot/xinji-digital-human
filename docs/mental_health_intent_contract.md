# E3c 自然诉求与 unknown 边界

更新：2026-09-24。E3c开发与一次保留验证已完成；v2保留集无总体收益且有反问退化，未通过门槛。生产默认仍为规则 Decision。

## 实现

`scripts/decision_intent_contract.py` 增加实验 `contract_v2`，在冻结的 `contract_v1` 基础上仅替换第4段求助判断说明，保留其余策略优先级、输出schema、上下文与生成参数。

- unknown/unspecified 表示本机识别器未确定，不足以否定用户原文中真实的行动请求。
- 向助手询问怎样安排、先做哪项、协助选择，可能构成自然求助，无须包含“建议”等固定词。
- 问号或单个“怎么办”不能单独证明同意建议；需区分当前请求、反问、描述经历和引用他人的问题。
- 明确拒绝建议仍优先；不确定时可以倾听或澄清，不能自动提供步骤。

这是提示策略候选，不是对本机识别器新增关键词规则。没有增加模型请求数：每个正常场景每组一次Decision请求，Safety先拦截。没有更换模型或训练权重，也没有调用Dialogue或回填人工评分。

新增实验入口 `scripts/evaluate_intent_contract.py`，逐例记录本机诉求、规则原始/协调后策略、模型原始/协调后策略，并对unknown项单列统计。`scripts/validate_intent_contract.py` 重算规则与协调，校验完整设计、实际请求变更边界、原始输出、统计和预设门槛。旧E3a/E3b脚本保持原样。

## 开发结果

12个新虚构开发案例，两组各一次：24场景、22正式请求、2Safety零调用，另2次预热。包括自然选择/安排、明确求助、反问、描述、他人引用、拒绝建议、不确定、澄清、结束、协议控制和风险。

| 路径 | 原始策略匹配 | 协调后匹配 | unknown项原始匹配 |
|---|---:|---:|---:|
| 本机规则 | 6/11 | 9/11 | 单独保存在逐例结果 |
| contract_v1 | 8/11 | 9/11 | 5/7 |
| contract_v2 | 11/11 | 11/11 | 7/7 |

自然选择/安排两个案例的本机诉求均为unknown，v2能给出协作解决，规则协调仍为倾听。反问、描述、引用和拒绝建议未出现本批误触发。只有一次筛查，不称为稳定性或临床验证。

目录：`logs/evaluation/e3c-intent-dev-20260924/`，22次请求边界及规则/模型/协调核对通过。报告SHA256：`7c0ff028c10a8c561ba578eb2f3f94ba1caab5776119e467465dd2db5af7a02c`。

## 候选冻结和新保留集

冻结文件：`logs/evaluation/e3c-candidate-freeze-20260924.json`，SHA256 `9584bffa36dc927def1be8b557d0a4c76642391a235449854c8d9d62aaf55a2e`。冻结包含候选、执行器、复用依赖和心理模块源码；随后才编写并绑定 `tests/fixtures/decision_intent_holdout.json`。

保留材料12例（10正常、2Safety），两组各三次，实际72场景、60正式请求全部合法、12Safety零调用，另2预热成功。原始匹配率门槛≥90%、合法率≥95%；自然求助、反问、描述、引用、拒绝建议、不确定与结束关键案例每次必须匹配；所有组风险均须零调用。门槛在模型运行前固定，未用结果调参后覆盖。

候选只可启动一次保留集，三次重复属于同一次预先调度实验。故障/部分完成也留下曝光标记。工具拒绝把标记为holdout的文件通过development参数重新命名为开发集。标记用于本机实验审计，不是防止恶意人为重写文件的安全系统。

这些样例由同一开发流程编写，与开发集部分诉求家族相同，因此属于内部新措辞检查；重复生成不增加独立案例数量，策略匹配不等于对话质量或临床收益。

## 使用

在仓库根目录运行，Decision服务须在127.0.0.1:8001启动。使用新目录，旧目录拒绝覆盖。

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe scripts/evaluate_intent_contract.py run `
  --fixtures tests/fixtures/decision_intent_development.json --split development --repeats 1 `
  --output logs/evaluation/e3c-dev-new
.\.venv\Scripts\python.exe scripts/evaluate_intent_contract.py freeze `
  --output logs/evaluation/e3c-new-freeze.json
# 冻结后编写绑定该freeze SHA256的新holdout文件；holdout强制三次重复，禁止重复曝光。
.\.venv\Scripts\python.exe scripts/validate_intent_contract.py `
  --experiment logs/evaluation/e3c-intent-holdout-20260924 `
  --output logs/evaluation/e3c-intent-holdout-20260924/validation.json
```

## 验证

5项新增专项与157项完整回归通过，Ruff通过。测试覆盖仅系统提示变化、实际转发记录、unknown原文不被篡改、Safety零调用、截断/回退不算命中、冻结/三次重复/曝光保护、规则与原始输出篡改拒绝，以及关键失败不能被总分掩盖。

测试日志：`logs/phase-e3c-tests.txt`。没有修改生产客户端、规则识别器、协调器或默认配置。

保留过程中已发现两类不同失败：`n-priority` 的行动优先级询问被选成倾听；`n-rhetorical` 的反问/抱怨被选成 `validate_and_ground`。后一项是偏离本批倾听/澄清标签的安抚稳定策略，不应写成“已经给出实际建议”——本实验没有生成Dialogue回答。门槛主要评价primary策略，JSON合法也不代表avoid、声音或表达计划的语义质量都已合格。

## 保留集最终结果

| 路径 | 原始策略匹配 | 协调后匹配 | unknown项原始匹配 |
|---|---:|---:|---:|
| 本机规则 | 15/30 | 21/30 | 可查逐例 |
| contract_v1 | 24/30 | 24/30 | 15/21 |
| contract_v2 | 24/30 | 24/30 | 15/21 |

v2在 `n-arrange` 上新增3次命中，`n-rhetorical` 相对v1退化3次；`n-priority` 两版均错3次。候选原始匹配80%，低于90%，且有6次关键案例失败，筛查结果为failed。其余本批描述、引用、拒绝建议、不确定、澄清和结束均符合标签。两版没有格式错误、截断或回退。

因此，**当前这项提示改动不能作为总体收益交付或推入生产**。新措辞开发全中没有在保留集延续，不能通过重复调参把同一保留集“刷过”。本次两版在同一个保留集上的结果可以比较；不能与E3b另一套保留集的27/30直接计算升降。

目录 `logs/evaluation/e3c-intent-holdout-20260924/`。60次实际请求边界、20个案例×变体组重复输入、全部本机诉求/规则/原始提议/协调及计数均校验通过。报告SHA256 `b081ccea5f4695e13f97037b6ee95c7f6bb0ef351361d5a215a261651229e02c`；manifest SHA256 `9730c268738e291072c9a1df7815776ef0ff44ae76ab128659cb18008b931d47`。

本批总计：24开发＋72保留＝96场景，82次正式模型请求、14次Safety零调用，另4次预热。均为虚构材料，人工质量评分未填写。

## 历史设想 E3d：有限诉求分类与原文证据协议

2026-09-24 收尾修订：用户已停止继续扩展。以下为当时设想，E3d 未开始且不属于当前开发任务。

下一批先实现实验协议和本机校验：同一次Decision响应同时返回有限诉求分类、当前原文中的简短逐字引用与策略，不增加额外模型轮次。分类区分行动求助、倾诉/拒绝建议、反问、转述、描述及不确定；不能让模型生成的分类覆盖本机明确拒绝或Safety约束。引用校验只能验证来源，不能证明语义正确，仍需成对正负例及新保留验证。

第一批只交付schema、来源/缺失/冲突校验和明确回退规则的工程实现；随后再冻结完整候选做真实模型对照。已有E3b/E3c失败材料只作历史回归，不再称作新保留集；两版提示和当前报告保留。E2人工评阅继续后置。
