# Decision 模型接入与开发状态

更新：2026-09-23。B 独立 CPU Decision 已部署，C 已通过本机边界处理已知协议操控误收尾；C2 真实 Agent 10/10 场景策略匹配。主配置仍默认规则 Decision，上下文版本为 2，协同收益尚待 E 对照。实测见 [B 记录](mental_health_phase_b_results.md) 与 [C 记录](mental_health_phase_c_results.md)。

## 当前已实现

- A1/A2 新增用户诉求与本机协调，协议版本默认 2；版本 1 显式兼容旧模型输出。详见 [用户诉求与决策协调](mental_health_intent.md)。模型输出仍是三组 JSON，协调 trace 由本机产生。
- 一次非流式 API 请求返回 strategy、behavior、voice；SDK 不自动重试，总超时默认 15 秒。
- 主策略、辅助策略、avoid、动作、注视和语音风格只接受 schema 中固定取值。策略文本不再允许模型自由填写。
- 提示词从 Pydantic schema 生成，要求三组字段完整；拒绝额外字段、不完整响应、重复 JSON 键、非有限数值、超范围参数、前后夹带正文和被截断的响应。兼容完整的 JSON 代码围栏。
- 每轮把角色 `emo_map` 中可用表情传给 Decision；未知表情回退到 neutral，缺少 neutral 时取首个可用表情。没有表情资源时不发送表情 ID。
- 角色能力表随前端与 TTS 配置进入上下文。当前新前端执行轻点头与注视，Edge TTS 执行语速；style/energy 明确回退。旧前端或不支持的引擎不宣称拥有这些执行能力。真人观感验收后置。
- API 超时、格式错误和服务故障回退规则；取消操作直接向上传播，便于打断。
- 心理状态新增可选 `decision_trace`，记录来源、API/回退耗时、回退原因、表情回退及输出 Safety 覆盖。旧 JSONL 可直接读取。
- trace 由本机产生，不接受模型填写，也不作为后续 Decision 输入。日志不输出响应正文、密钥和异常中的请求详情。
- C1 为明确内部协议命令增加输入副本过滤和本机协调；仅含命令时用本机澄清回复，记录 `output_policy_override`，不冒充模型遵循。Safety 仍读取原文，详见 [C 阶段记录](mental_health_phase_c_results.md)。
- 高风险输入仍在 Agent 的前置 Safety Gate 跳过 Decision 和 Dialogue，记录 `source=safety_gate`。

`latency_ms` 统计模型调用与解析，失败时包含回退时间；纯规则和安全门当前记为 0，不能用于比较它们的实际耗时。trace 仅随完成并保存状态的轮次持久化。

## 配置独立服务

位置：本机 `conf.yaml` → `character_config.agent_config.agent_settings.mental_health_agent.decision`。
现有 SFT、ORPO 是对话模型训练结果，当前未当作独立 Decision 模型使用。

```yaml
decision:
  enabled: true
  base_url: 'http://127.0.0.1:8001/v1'
  model: 'mental-health-decision-qwen2.5-1.5b'
  llm_api_key: 'local-decision'  # 本机 loopback 服务的占位值，不是认证凭据
  temperature: 0
  timeout_seconds: 15
  max_tokens: 300
  response_format: 'llama_json_schema'
  protocol_version: 2
```

默认 `text` 不向接口发送 `response_format` 参数；`json_object` 请求普通 JSON；`llama_json_schema` 显式使用已核对的 llama.cpp schema 扩展，不能假设任意 OpenAI 兼容服务都支持。本机严格校验在三种模式下都强制执行。若服务不支持某模式，该轮回退，不追加第二次请求。若响应因 token 不足被截断，可调整 `max_tokens` 后重新检查，总超时保持 15 秒。

配置独立 endpoint 后，普通轮次会发送当轮文本、当前状态、最近状态及角色能力。联调工具只使用内置虚构样例，不读取用户聊天或状态存储。

## 联调命令

从仓库根目录运行：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe scripts/check_decision.py --rules-only --output logs/decision-rules-new.json
# 配置并启动独立服务后运行：
.\.venv\Scripts\python.exe scripts/run_decision_api.py
# 在另一终端运行评估；--config 指向已开启 Decision 的完整临时配置
.\.venv\Scripts\python.exe scripts/check_decision.py --config private/decision/conf-cpu-schema.yaml --repeats 3 --sample-resources --deployment-manifest private/decision/deployment-cpu.json --output logs/decision-model-new.json
.\.venv\Scripts\python.exe scripts/check_decision_resources.py --output logs/decision-resources-new.json
```

报告默认写入被 Git 忽略的 `logs/decision_check.json`。已有文件时拒绝覆盖，复跑须使用新的 `--output`。默认重复 3 轮，不预热，首轮冷请求计入；顺序固定，不能视为随机交错性能对照。

固定 7 个样例包含问候、工作压力、实际帮助请求、协议注入、倾诉、结束和高风险绕过。输出包括规则基线、提议/最终策略、来源、p50/p95（nearest-rank）、合法率、回退率、模型名、源码/样例/部署清单哈希。请求数指 primary.decide 调用数，SDK 重试为零，由 SDK 契约测试核对一次调用对应一次 HTTP 请求；不把回退计成模型成功。资源为约每 0.5 秒加探测耗时的全机采样峰值，不能当作进程独占资源或精确峰值，不可用读数保留 unknown。

- 退出码 0：规则模式完成，或模型模式所有普通样例获得合法决策。通过仅代表协议可用，不代表决策质量合格。
- 退出码 1：模型模式出现回退；仍保存报告用于检查。
- 退出码 2：配置/资源错误或尚未开启独立 API。
- 高风险样例请求数为 0。所有正常模型样例至多一次请求。
- `quality_review=pending` 始终明确保留人工质量评估待办。

## 下一步

已完成真实 schema 三轮协议集、真实 Agent 联调和取消/恢复检查，C1 三轮复查 18/18 合法，C2 Agent 10/10 策略匹配。协议控制例存在明确本机文本覆盖，不代表模型质量提高；默认继续规则 Decision。下一步 D 长期统计，再进行 E 协同效果对照。
