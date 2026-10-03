# 心迹：本轮功能与运行入口

版本：`companion-2026-10-01`。本轮沿用 `context_v2 + daily_v2 + 规则 Decision`，没有重训模型。下面的工程验证不代表心理健康干预效果。

## 已实现的体验

聊天侧栏的「我的心迹」可记录压力、焦虑感和低落感，任意维度可跳过。界面 0～10 分映射到既有存储的 0～1；零分有记录，未填写保持未知。最近 14 个日历日分为两个 7 日窗口，按系统估计、自报、纠正分别显示。记录不足或过期时不推断变化，周回顾由统计结果生成。

2026-10-02 界面修订后，日常面板收敛为「记一记／看变化／小步骤」。在「看变化 → 查看与修改记录」中可逐条修改或删除。修改仅覆盖选中的维度，保留其他维度来源；后端重新计算趋势，下一轮对话重新读取。旧回放快照会失效，删除状态不会同时删除聊天文本。

输入框上方的「先听我说／帮我梳理／一起想办法」作用于当前会话。最新明确的自然表达可覆盖按钮选择，安全处理优先。回答下方反馈可取消；当前会话最近一条回答的「没帮助」使下一轮先澄清。旧会话反馈仍保留为历史，不跨会话强制改变偏好。新建或载入聊天清空当前偏好和待播放音频。

明确求助后，回答下方可以手动编辑并确认一个生活或学习行动。每个档案只允许一个待尝试行动；可完成或跳过，完成后可评价帮助程度。下次打开显示一次回顾入口。行动反馈不计入心理状态分数。

演示工作台使用独立地址 `/?view=demo`（例如 `http://localhost:12401/?view=demo`），不占普通用户导航。它展示诉求、历史来源及覆盖、决策提议、协调原因、最终策略、生成状态、已发送参数和浏览器音频回执。规则、独立模型、回退和安全门分别标注。仅文字、发送成功、播放完成是不同事实；不显示模型内部思考。日常界面以「示例体验」和示例记录提示标识合成档案，技术说明保留在工作台与数据设置内。

## 启动现有本机服务

在仓库根目录运行。保持原有对话模型服务已启动，连接参数在本机 `conf.yaml` 中配置。不要将密钥写进公开文档。

本机日常使用地址是 `http://localhost:12393/`，原聊天保存在个人档案中。`12401` 是独立的合成演示服务，不会显示个人历史。刷新网页会恢复当前服务档案内上次选中的有效会话；详见 [历史与日常入口修订](companion_history_fix.md)。

```powershell
# 首次取得前端源码后安装依赖；本机已经安装，不必重复
cd frontend-src
npm ci --ignore-scripts
npm run build:web
cd ..
.\.venv\Scripts\python.exe run_server.py --config conf.yaml
```

配置要求：`system_config.frontend_dir: frontend-src/dist/web`；Agent 选择 `mental_health_agent`，`context_version: 2`，`decision.enabled: false`，`memory.enabled: true`，`memory.mode: local_user`，`memory.trend.version: daily_v2`。本机档案必须只监听 loopback 且禁用 proxy。旧客户端不发送伴随字段时仍可聊天，但没有新操作入口。

## 独立同学体验档案

先停止上一位体验者的网页服务，再创建并启动新配置。复制运行参数，不复制任何个人状态或历史；每份配置有独立用户 ID、聊天配置 ID 和 SQLite 文件。已存在的目录拒绝覆盖。配置可能包含本机模型连接凭证，只存放在 Git 忽略的 `private/trials/`。

```powershell
.\.venv\Scripts\python.exe scripts/create_trial_profile.py --source conf.yaml --output private/trials/P01 --label P01
.\.venv\Scripts\python.exe run_server.py --config private/trials/P01/conf.yaml
```

打开 `http://localhost:12393/?view=demo`，由操作者核对工作台的 P01 标签，再返回日常页面。让本人在首次体验说明中选择是否参加与是否保留聊天文本，之后可通过面板底部「数据与隐私」调整。回访启动同一份配置；换人创建 P02 等新目录，并重启和刷新浏览器。端口可通过创建脚本的 `--port` 指定。前端默认连接当前网页来源，避免新端口连回旧档案。

试用模式关闭内容日志；默认只保存结构化状态、决策事实、手动行动和无原文的操作事件。未另行同意时，聊天原文不写历史文件（包括打断时已听内容）。内存中的当前对话可用于连续交流，重载后不能恢复。撤回文本许可会停止后续落盘；既有聊天可在历史管理中删除。试用模式禁用角色切换、分组和主动发言，身份不接受浏览器传入。

这仍是单机单档案原型，不是多用户认证系统。操作者管理匿名编号对应关系，原始访谈与配置不放进提交包。若配置使用远程对话/识别服务，相关输入会发送给配置的提供商；Edge TTS 会发送待朗读文本。体验前按实际配置说明，离线演示没有这些调用。

## 离线合成演示

不需要对话模型、ASR 或 TTS。使用真实状态存储、规则协调、产品 API、WebSocket 和对话管线，只有文字回复采用固定模板。需先构建 Web 前端，模型素材沿用仓库现有 Live2D 资源。

```powershell
.\.venv\Scripts\python.exe scripts/companion_demo.py --output private/demos/run-01 --serve --port 12401
```

命令先生成并断言三组场景，再在 `http://localhost:12401` 提供合成界面。`cases.json` 保存纠正前后的快照与真实规则决策；脚本没有发送表达音频，因此不填播放完成。每次必须使用新输出目录，连续复现可用 `run-02`、`run-03`。页面内所做操作也属于合成演示，不进入真人报告。关闭后可用相同目录加 `--resume --serve` 重新打开已有合成档案。

## 验证与材料

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m unittest discover -s tests
cd frontend-src
node --test tests/decision-behavior.test.cjs tests/companion-trend.test.cjs tests/history-session.test.cjs
npm run build:web
cd ..
```

本轮验收结果见 [验收记录](companion_acceptance.md)，真人任务和统一问卷见 [试用手册](companion_trial_protocol.md)，复用说明及提交索引见 [提交包索引](companion_submission.md)。保留旧报告的日期和版本，不将旧的 91 项或 157 项基线覆盖为本轮结果。
