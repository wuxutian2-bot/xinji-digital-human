# 长期状态使用说明

更新：2026-09-22。

本机配置已启用 SQLite：`mental_health_memory/states.sqlite3`，用户标识保存在本机 `conf.yaml` 的 `mental_health_agent.memory.user_id`，由本次配置生成，与角色和聊天历史 ID 无关。同一服务的本机网页连接视为同一个用户。当前没有登录认证，不支持让不同实际用户共用这个配置；工厂拒绝把 local_user 模式用于非回环监听地址或代理模式。

默认模板继续用 history/JSONL 模式。启用长期状态需设置 `memory.mode: local_user`、独立 `user_id`、`sqlite_path`。`memory.enabled: false` 用于不读写心理状态的消融；Safety 始终启用。

状态带 schema_version、estimator_source、confidence、observed_dimensions。关键词估计只是低可信度交互信号，没有匹配不代表心理状态良好。7 天窗口只统计有观测的维度；对比前一个 7 天窗口时，两边各至少 3 个观测才计算变化。重复话题需至少 3 条记录。历史某维度至少 3 个观测且均值达到 0.6 时，规则决策从倾听切换为澄清与情绪反映；当前高风险仍由 Safety 优先处理。这些阈值是工程基线，未经临床验证。

## 管理命令

启动配置启用 `local_user` 时，网页后端额外校验 HTTP Host 和浏览器 Origin，只接受本机服务端口的 localhost、127.0.0.1 或 ::1。外部网页、`null` 来源及其他端口会被拒绝；请使用后端提供的网页地址，Vite 开发页和 file:// 页面不在允许范围。来源为空的本地脚本仍可连接，因此它不是登录认证，不能隔离同一操作系统中的其他程序或用户。修改启动配置后需重启服务以应用边界。

2026-09-22 实机核对：本机 HTTP 200、WebSocket 成功；外部 Origin 与伪装 Host 均为 403。心理状态读取/保存失败和损坏 JSONL 的日志仅记录错误类型及行号，不输出异常中的记录内容。

把下面的 USER_ID 换成本机配置中的用户标识，运行位置为仓库根目录。

```powershell
.\.venv\Scripts\python.exe scripts/manage_psychological_memory.py --user-id USER_ID list
.\.venv\Scripts\python.exe scripts/manage_psychological_memory.py --user-id USER_ID trend
.\.venv\Scripts\python.exe scripts/manage_psychological_memory.py --user-id USER_ID trend --at 2026-09-22T08:00:00+08:00 --output private/trend-20260922.json
.\.venv\Scripts\python.exe scripts/manage_psychological_memory.py --user-id USER_ID correct --id RECORD_ID --changes correction.json
.\.venv\Scripts\python.exe scripts/manage_psychological_memory.py --user-id USER_ID delete --id RECORD_ID
.\.venv\Scripts\python.exe scripts/manage_psychological_memory.py --user-id USER_ID delete --history-scope CONF_UID:HISTORY_UID
.\.venv\Scripts\python.exe scripts/manage_psychological_memory.py --user-id USER_ID delete --all-for-user
.\.venv\Scripts\python.exe scripts/manage_psychological_memory.py --user-id USER_ID import-jsonl --source mental_health_memory/psychological_state.jsonl --scope CONF_UID:HISTORY_UID
```

纠正文件示例：`{"emotion":{"stress":0.2},"summary":"用户纠正：当时压力较小"}`。只允许纠正情绪、观测维度、话题、摘要；保留来源历史和时间，标记为 user_correction。修改前先校验，失败不改变原记录。

`trend` 汇总指定用户全部相关历史的近 14 天记录，不受最近记录条数限制。输出含参考时间、近 7 天观测计数/均值、与前 7 天的变化及重复话题；null 表示未知。`--at` 必须带时区，省略则使用当前时间。`--output` 仅创建新文件，父目录须存在，已有文件不会覆盖；导出不含逐条状态摘要、聊天正文或用户标识，但趋势本身仍是用户数据，应保存在 private 等忽略目录中。数据库路径不存在会报错，避免拼错路径时生成空数据库。

迁移要求逐项明确旧历史属于哪个用户，重复导入同一文件不会重复插入。本轮没有自动迁移旧 JSONL。旧记录缺少观测维度时按未知处理。

A1/A2 增加可选 interaction_intent 与决策协调 trace。纠正文件支持 `{"interaction_feedback":"unhelpful"}`，允许 helpful/unhelpful/unspecified；只纠正反馈时不修改情绪可信度和实际执行 trace。该操作用于历史记录，不自动改变当前聊天偏好。详见 [诉求与协调说明](mental_health_intent.md)。

删除命令只删除当前用户选定的结构化状态；网页删除聊天历史只删原始聊天，两种记录互不联动。JSONL 原件、备份和导出文件需分别管理。SQLite 使用 secure_delete，但不承诺清除 WAL、备份、磁盘恢复数据；停止交互后再进行完整数据清理。目前没有自动过期删除策略。
