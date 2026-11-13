# 任务 1：危机支持实施与验证记录

实施日期：2026-11-13。分支：`xinji-main`。

状态：代码与自动化回归已完成；用户已提供 2026-11-13 的四项号码人工核实记录，已同步到资源文件。功能提交 `f56a031` 已推送至 `xinji/main`；未执行部署，真实服务的 1 秒显示指标仍待验收。任务 2～7 尚未实施。

## 实现

- 资源表统一放在后端，固定中文危机回复及输出阻断回复引用同一份联系方式；英文回复继续提示当地急救服务。
- 危机轮次第一句的 `Actions` 包含 `crisis_resources` 和随机 `crisis_id`；普通轮次不包含。关闭表情/语音控制也不关闭安全界面。高风险输入仍然绕过 Dialogue 和 Decision 模型。
- `process_agent_output()` 在翻译和 TTS 前先发送 `crisis-support` WebSocket 通知。第一句音频仍携带同样的 Actions，兼容音频消息驱动的显示。相同 `crisis_id` 去重，避免确认后因迟到音频重新打开卡片，或旧音频覆盖新卡片。
- 独立 `CrisisProvider` 位于 WebSocketHandler 外层，让输入控制和 CompanionProvider 共用安全状态。资源卡片使用原生 modal dialog；普通消息、切换聊天、断线都不会自动关闭已显示的卡片。确认前暂停普通输入和麦克风自动开启，Escape 不视作确认。
- 确认立即关闭卡片，并向 `/api/companion/events` POST `{"name":"crisis_ack"}`。请求失败会明确提示记录未保存。该事件只表示用户点击确认，不代表临床安全判断，也不会降低或清除后端风险等级。
- UI 不保存原话，不把安全状态放入 localStorage。事件仍受现有档案隔离和试用同意规则约束。

## 改动文件

| 范围 | 文件（相对仓库根目录） |
| --- | --- |
| 资源与回复 | `src/open_llm_vtuber/mental_health/crisis_resources.py`（新增）、`safety_guard.py` |
| Agent 与下发 | `src/open_llm_vtuber/agent/output_types.py`、`src/open_llm_vtuber/agent/agents/mental_health_agent.py`、`src/open_llm_vtuber/conversations/conversation_utils.py` |
| 事件 API | `src/open_llm_vtuber/mental_health/product_routes.py` |
| 前端安全状态 | `frontend-src/src/renderer/src/utils/crisis-support.ts`（新增）、`components/companion/crisis-context.tsx`（新增） |
| 前端卡片 | `frontend-src/src/renderer/src/components/companion/crisis-card.tsx`（新增）、同目录 `companion-context.tsx`、`companion.css` |
| 前端接入 | `frontend-src/src/renderer/src/App.tsx`、`services/websocket-handler.tsx`、`services/websocket-service.tsx` |
| 测试 | `tests/test_crisis_support.py`（新增）、`frontend-src/tests/crisis-card.test.cjs`（新增） |
| 测试依赖 | `frontend-src/package.json`、`package-lock.json`：React 18 对应的 `react-test-renderer@18.3.1`，仅开发依赖；lock 同步已有 package 版本 1.2.1 |
| 基线格式修正 | `src/open_llm_vtuber/mental_health/schemas.py`、`tests/test_protocol_boundary.py`：仅 Ruff 换行/引号调整，无行为变更 |
| 交接记录 | 本文及 `docs/plans/2026-11-13-交接执行手册.md` 的进度注记 |

## 新增测试

后端新增 7 项：

1. 危机回复含手册指定号码，第一句有资源；后续句子没有；表情开关两种情况都不调用 Dialogue/Decision。
2. 普通对话不携带危机元数据。
3. 输出阻断回复含联系方式，英文输入保持当地急救提示。
4. Actions 可 JSON 序列化，修改单轮 payload 不会污染资源常量。
5. 通知先于翻译/TTS；即使 TTS 抛错，资源通知已发出。
6. 普通回复不新增危机 WebSocket 通知。
7. `crisis_ack` 只记录在当前档案，不降级风险，不接受原文扩展字段，仍遵守试用同意限制。

前端新增 5 项，用 node:test + TypeScript 转译 + React renderer 运行实际 Provider、消息订阅、卡片和点击回调：

1. 策略到达后渲染卡片与 tel 链接，普通消息不关闭；确认关闭并 POST 事件；重复音频不重开，新危机可重开。
2. 旧危机音频不覆盖较新的卡片。
3. 其他聊天的消息不弹卡片；不合法的拨号链接不渲染，缺资源时仍显示通用求助提示。
4. 事件保存失败时仍可关闭，并明确告知未保存。
5. 旧确认请求尚未返回时，新危机通知仍能保持可见。

## 实际验证结果

每个 PowerShell 进程先按项目 AGENTS.md 激活共享工具环境；Python 使用项目 `.venv`。

```text
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m unittest discover -s tests
Ran 181 tests
OK

.\.venv\Scripts\ruff.exe check src/open_llm_vtuber tests scripts
All checks passed!

.\.venv\Scripts\ruff.exe format --check src/open_llm_vtuber/mental_health tests
45 files already formatted

node --test frontend-src/tests/*.test.cjs
tests 15
pass 15
fail 0

npm --prefix frontend-src run build:web
2572 modules transformed.
✓ built in 6.72s

git diff --check
退出码 0
```

原手册的 `node --test tests/` 在当前 Node v24.22.1 下返回 `MODULE_NOT_FOUND`；显式指定 `*.test.cjs` 后执行全部前端测试。开始修改前后端基线 174 项通过，前端基线 10 项通过。开始时格式检查有两处差异，本次已仅作格式修正。

额外执行了 `npm run typecheck:web`，退出码 2。报告包含未修改的 WebSDK 空值/初始化错误，以及 `chat-history-panel.tsx`、`live2d-config-context.tsx`、`use-audio-task.ts` 的未使用声明；新增危机文件和本次修改的前端文件未列出错误。本任务没有修复整仓库 TypeScript 问题。构建仍有 CJS API、onnxruntime eval 和大包体积警告。

浏览器检查使用真实 Vite 前端，注入模拟 `crisis-support` 协议事件，并模拟事件 API 返回 201；已查看桌面及 390×844 窄屏、Escape 保留卡片、点击确认关闭与事件请求。未拨打任何电话。截图留在忽略目录 `output/playwright/crisis-desktop.png`、`output/playwright/crisis-mobile.png`，不加入提交。

本次浏览器检查没有连接真实对话服务，不能当作输入到卡片显示小于 1 秒的端到端测量。后端测试仅证实通知不等待翻译/TTS。

## 人工核实与上线门槛

用户已提供以下人工核实结果，四项号码均标记为已核实。核实日期、核实人标记与官方来源按用户提供的内容记录；这不是 AI 独立完成的官方核实。此前查询工具返回的地区不匹配，未被用作中国资源的证明。

本次提供的记录没有具体服务时段和出处 URL，因此不补造链接、不推定全天服务。资源文件已写明来源与核实日期；卡片的 `available` 文案更新为“接听时段以服务方公布为准”。

| 手册资源 | 官方来源 | 人工核实日期/人 | 状态 |
| --- | --- | --- | --- |
| 全国统一心理援助热线 | 国家卫生健康委（号码：12356） | 2026-11-13 / 人工核实 | 已核实 |
| 希望24热线 | 希望24热线官网（号码：400-161-9995） | 2026-11-13 / 人工核实 | 已核实 |
| 急救 | 国家卫健委《院前医疗急救管理办法》（号码：120） | 2026-11-13 / 人工核实 | 已核实 |
| 报警 | 公安部（号码：110） | 2026-11-13 / 人工核实 | 已核实 |

号码人工核实事项已完成。仍需用实际服务执行手册的风险输入验收，记录从输入提交到卡片出现的时间，并确认真实事件入库和语音播报。下一开发项为任务 2（流式输出与逐句安全检查）。
