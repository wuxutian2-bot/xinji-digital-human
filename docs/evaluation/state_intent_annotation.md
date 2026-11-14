# 状态与意图独立标注

每位评阅人领取一份 Excel 工作簿，共 312 条虚构发言。“填写说明”页提供标签解释，“标注”页黄色单元格供填写。请独立填写五列，保留原 ID 和原文。先完成自己的表，再与另一位评阅人核对。可分批保存并继续填写，完成后交回同名 xlsx 文件。

| 列 | 如何填写 |
|---|---|
| stress | 用户在说自己此刻的压力或负担有多重 |
| anxiety | 用户在说自己此刻的担心、紧张或害怕有多强 |
| low_mood | 用户在说自己此刻的失落、低沉或提不起劲有多强 |
| intent | 填写本轮希望对话如何继续，选下表中的一个英文值 |
| advice_preference | 明确想要建议填 requested，明确拒绝填 declined，其余填 unspecified |

三个维度独立填写。没有表达这一维就填字面值 `null`。明示当前本人有该感受时，按文字证据估计 0 到 1 的强度，可以用 0.25、0.5、0.75 作为轻、中、强的参考。0 仅用于明确描述当前该感受为零。对“没有很紧张”这类修饰语要看整句；仅引用他人、讲过去、谈虚构人物，以及名称碰巧含有关键词，都不足以证明本人当下有该感受。空白表示尚未填写。

| intent 值 | 本轮诉求 |
|---|---|
| venting | 希望表达感受、有人听 |
| seeking_practical_help | 希望得到可执行的做法、建议或话术 |
| seeking_clarification | 希望弄清问题、区分感受或理解原因 |
| ending | 告别或明确结束本次谈话 |
| small_talk | 打招呼、寒暄 |
| other | 其他或没有明确以上意图 |

例句“今天被催了好多次，我有点透不过气。你先听我讲就好。”可标为 stress 0.5，另两维 null，意图 venting，建议偏好 declined。实际标注时请按自己的判断，不确定之处可写在 notes 栏。

回收时逐 ID 对比原文、维度的有无与强度、诉求和偏好。两人共同确认分歧后另存裁定版 CSV，保留原始两份。评测脚本读取裁定版的 id、text 和五个标签字段。Excel 中 numeric 0 与 null 含义不同，转换时按原值保存。原始 CSV 也可填写，文件采用 UTF-8 编码，保存格式选 CSV UTF-8。候选草案、模型预测和开发集划分均不出现在评阅表中。

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_state_intent.py --adjudicated private/reviews/state-intent/裁定.csv --db mental_health_memory/states.sqlite3
```

回收后若两份标签仍有强度分歧，可以先对同一批预测分别计分。将两份原始人工标签各导出为 CSV 后，运行以下命令。报告中的标签状态会标为 `independent_reviewers`，第二份标签的指标与逐题预测也写入 JSON。双方确认分歧后再用裁定版运行正式评测。

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_state_intent.py --adjudicated private/reviews/state-intent/回收/人工标签-甲.csv --reference private/reviews/state-intent/回收/人工标签-乙.csv --output docs/mental_health_state_intent_human_eval.md --db mental_health_memory/states.sqlite3
```
