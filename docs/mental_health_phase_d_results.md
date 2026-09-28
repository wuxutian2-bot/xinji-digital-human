# D 阶段：长期统计改进

更新：2026-09-23。工程实现完成；本阶段是确定性统计与接入改进，不是心理状态测量效度或模型质量结论。主计划为 [认知与协同决策升级计划](plans/2026-09-22-心迹认知与协同决策升级计划.md)。

## 1. 统计口径

本机 `memory.mode=local_user`，显式选择 `memory.trend.version=daily_v2`、`timezone=Asia/Shanghai`。新配置模板同样列出这些设置，但模板默认 history 模式不产生跨历史统计。旧配置缺少 trend 字段时仍用 rolling_v1；CLI trend 默认 daily_v2，支持 `--version rolling_v1` 明确复算旧口径。旧文件不重写，已有报告不改标签。

| 项目 | daily_v2 规则 |
|---|---|
| 当前窗口 | 参考日及之前 6 个本地日历日；只纳入时间戳 ≤ as_of 的记录 |
| 前期窗口 | 紧接当前窗口之前的 7 个本地日历日 |
| 边界 | 每窗口 start 含、end_exclusive 不含；报告另给 as_of，参考日实际截止到该时刻（含） |
| 日均与窗口均值 | 同来源、同维度先计算每日均值，再对有效日等权；计算完成后展示值四舍五入至 3 位 |
| 重复 | 同来源/维度/时间戳/分数重复只计一次；不同时间的真实观测参与当日日均，不增加有效日数 |
| 变化 | 当前与前期都至少 min_observed_days=3 日才输出；否则 null |
| 话题 | 同来源至少 min_topic_days=3 个不同日期出现才列为 recurring；单条和同日重复都不增加天数 |
| 覆盖 | 每维度 observed_days / 7；分别报告前期天数与覆盖；无观测与明确自报 0 分不同 |
| 新鲜度 | 同来源、同维度最近有效时间 last_observed_at；age_days 是本地日期差，默认 >7 天 stale |
| 来源 | system_estimate、user_report、user_correction 独立汇总；未知 legacy 来源不计有效日 |
| 时间缺失 | 无时区、timestamp_known=false 的记录不聚合；导入缺 timestamp 的 JSONL 明确标未知，不把导入时间当观测时间 |

阈值是工程假设，可在配置或 CLI 调整，随报告保存。日历窗口始终是 7 日；上海跨午夜、纽约春季 167 小时/秋季 169 小时的 7 日窗口均有测试。Windows 使用固定依赖 tzdata 2025.2，更新时区库时需复跑边界测试。

`sources` 是完整报告的权威来源分层数据。为兼容查看工具，顶层 means/changes/recurring_topics 仅投影 system_estimate，不表示三种来源合并。sample_count/previous_sample_count 是窗口内来源和时间可用的原始记录行数，仅供诊断，不能作为充分性门槛。重复行可以改变原始行数，不改变 sources 内的均值、天数和话题阈值。

## 2. 纠正、自报和用户隔离

- 新增 UserStateReport 和 self-report CLI：必须明确给出带时区 timestamp 和至少一个 0～1 分数；拒绝空分数、未知维度、越界/非有限分数、未来时间。只有传入维度才标 observed，未给出的维度保持未知。这不是临床量表。
- 自报记录使用 schema v4、estimator_source=user_report、confidence=user_reported；不从闲聊自动生成自报。
- 新增可选 dimension_sources/topics_source。修正一个维度时，其余已观测维度保留原来源；仅改 summary 不把所有分数变成用户评分。旧 user_correction 数据若没有逐维来源，无法恢复修正前来源，按现存整体来源读取并保留此限制。
- 纠正仍保留 id、原 timestamp、history_scope、Decision trace 和上下文证据；feedback=helpful/unhelpful 独立于数值分数。校验失败回滚事务。
- 读取、纠正、删除均受服务端 user_id 隔离；跨历史读取同一用户。每次直接重算，没有长期统计缓存；删除后不返回已删除记录的趋势。
- SQLite 按用户和参考时刻查询，逐行读取历史，以便保留窗口之外最近一次有效观测；时间复杂度为该用户历史行数 O(n)，大量历史尚未做性能容量评价。聚合只保留两个窗口的数据和每维最近时间。
- 新导入缺失日期可准确标未知；对于此前已被旧版本补上默认时间的历史行，无法仅凭现有字段判断真实日期。没有自动猜测或迁移。

## 3. Decision 与 Dialogue 接入

规则 Decision 对每一来源/维度单独检查足够观测日与新鲜度；只有 eligible_for_decision=true 的历史均值才可能触发 reflect_and_clarify。三种来源分别使用现有 0.6 工程阈值，不混算。当前情绪和 Safety 分支先执行；用户诉求协调层仍可覆盖历史提议。

独立 Decision 和 Dialogue 使用精简 trend_for_model 投影：保留版本、时区/阈值、窗口、各来源均值/变化、有效日数、覆盖、新鲜度状态及合格话题。过期或不足的均值/变化置 null。daily_v2 下不额外传最近几条记录的平均值，也不把 raw recent_states 传给独立 Decision，防止绕过日期和来源门槛。当前状态、原对话历史与本轮诉求保持原用途；这些处理不能保证生成模型永远正确解释历史。

本机独立 Decision 仍默认关闭。此批以真实配置加载、SQLite、规则决策、捕获模型请求的契约测试验证接入；未追加真实双模型对话质量实验。E 阶段再对 R0～R4 做实际消融。

## 4. 可复跑证据

新增 10 项 daily 测试和 1 项 CLI 测试，完整后端 **120 项通过**；Ruff 通过，uv lock --check --offline 通过。完整日志 `logs/phase-d-tests.txt`；冻结时以最新完整日志为准。

`scripts/compare_daily_trends.py` 固定生成 6 组虚构记录，保存输入、统计配置、源码 SHA256、v1/v2 完整输出和精确重放不变性。最终报告 `logs/phase-d-daily-comparison-final.json`；不读取用户库，不请求模型。初次报告保留，其后只修正脚本导入的 Ruff 标记，最终报告重新绑定源码哈希。

网页进程已重启加载新配置；本机 HTTP 200、外部 Origin 403，启动检查 0 项失败，ORPO API 可达。独立 Decision 服务仍在本机，但主配置未启用。本批没有执行真人麦克风/主观体验验收。

| 合成案例 | rolling_v1 | daily_v2 |
|---|---|---|
| 一日 30 个高分观测，另两日各 1 个零分 | stress=0.938 | stress=0.333，3 个有效日等权 |
| 同日 100 个观测 | 认为样本足够、work 重复话题 | 只有 1 日，不足；无跨日重复话题 |
| 系统 3 日 0.8，自报 3 日 0 | 混合均值 0.4 | system=0.8、user_report=0，分别展示 |
| 距参考时刻 6/7/8 天 | 当前 2 条、前期 1 条 | 当前 1 日、前期 2 日 |
| legacy 未知来源 | 可以给出 0.8 | 系统均值 null，不虚构观测来源 |
| 30 日前最后观测 | 当前均值 null，无新鲜度字段 | 当前均值 null、age_days=30、stale=true |

6 组均通过追加 100 次完全相同记录后 sources 统计不变检查。专项测试另覆盖未来同日记录排除、分维缺失/零分、来源纠正与删除后重算、用户隔离、时区转换、春秋夏令时、配置阈值和即时 Safety 优先。

## 5. 使用方式

从仓库根目录运行；将 PROFILE_ID 换成受信的本机配置 user_id。以下自报 JSON 是格式示例，使用时填写实际自述时间；命令写入本机结构化状态库。

```json
{
  "timestamp": "2026-09-23T09:00:00+08:00",
  "emotion": {"stress": 0.3, "anxiety": 0.0},
  "topics": ["work"]
}
```

```powershell
.\.venv\Scripts\python.exe scripts/manage_psychological_memory.py --user-id PROFILE_ID self-report --input private/self-report.json --history-scope manual
.\.venv\Scripts\python.exe scripts/manage_psychological_memory.py --user-id PROFILE_ID trend --version daily_v2 --timezone Asia/Shanghai --output private/trend-daily-new.json
.\.venv\Scripts\python.exe scripts/manage_psychological_memory.py --user-id PROFILE_ID trend --version rolling_v1 --output private/trend-rolling-new.json
# 对照报告只使用虚构数据；输出必须是不存在的新文件。
.\.venv\Scripts\python.exe scripts/compare_daily_trends.py --output logs/daily-comparison-new.json
```

程序不会自动把示例数据写入真实库。trend 输出拒绝覆盖文件；纠正/删除沿用既有 CLI。本阶段没有新增前端自报表单、自动临床评估或自动迁移旧记录。

## 6. 后续

下一步 **E1：协同效果对照**。冻结配置/提示词/样例，准备 R0～R4 可追溯实验与重复运行、轨迹导出，再生成初始为空的人工评阅表。E2 质量评阅、真人语音与数字人体验按用户安排后置。C 阶段剩余语义误报/漏观测依然是已知限制。
