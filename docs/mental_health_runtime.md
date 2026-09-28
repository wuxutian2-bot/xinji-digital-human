# 本机运行与验证

## 当前可运行范围

已接入 `D:/models` 的 ORPO 适配器，通过 LLaMA-Factory 加载 Qwen3-4B 基座，采用
bitsandbytes NF4 量化，以适配本机 RTX 5060 8 GB 显存。SFT 适配器提供独立启动模板，
本轮实机对话验证使用 ORPO；两份适配器不要叠加加载。

可用链路：文字输入 → Safety 前置检查 → 心理状态估计、历史状态读取 →
结构化 Decision → ORPO 回复 → Safety 后置检查 → 状态写入 → TTS、Live2D。

- Decision 默认使用本地规则。独立 Decision API 客户端已实现，尚未配置真实决策模型。
- 表情通过 `emo_map` 从 Decision 映射；动作、注视、语音风格、语速、能量作为
  `Actions` 元数据传输。当前上游前端和 TTS 引擎尚未执行这些新增参数。
- 当前 `conf.yaml` 已设置 `asr_config.enabled: true`，使用官方 SenseVoice INT8 CPU 模型。
  固定语音及 WebSocket 协议回放已通过；真人麦克风、网页 VAD 和实际播放打断仍待验收。
  后端 VAD 暂不启用，保留网页内置 VAD；如需只用文字输入，将 enabled 改回 false。
- Edge TTS 需要联网。无系统 FFmpeg/ffprobe 时，音频解码使用 `imageio-ffmpeg`。
- Safety 和状态估计是规则基线，尚未完成代表性数据集上的误报、漏报评估。

## 启动

以下命令均在仓库根目录执行，需要两个 PowerShell 窗口。若服务已运行，无需重复启动。
`conf.yaml` 中的 dialogue key/model 必须与模型服务一致。

窗口 1，启动 ORPO 推理服务：

```powershell
$env:API_HOST = '127.0.0.1'
$env:API_PORT = '8000'
$env:API_MODEL_NAME = 'mental-health-orpo'
$env:API_KEY = '填写与 conf.yaml 中 dialogue.llm_api_key 相同的值'
& 'D:\模型微调\.venv-train\Scripts\llamafactory-cli.exe' api config_templates/mental_health_orpo_api.yaml
```

窗口 2，使用已安装依赖的项目环境启动网页后端：

```powershell
.\.venv\Scripts\python.exe run_server.py
```

打开 [本地网页](http://localhost:12393)，输入文字。网页应显示完整回复，播放结束后回到
“空闲”。首次使用浏览器可能需要点击页面以允许音频播放。

从新环境安装时：先安装 `requirements.txt`，并运行 `git submodule update --init frontend`
取得与仓库绑定的前端构建产物。本机这两步已经完成；不要覆盖现有 `conf.yaml`。

## 开启独立 Decision API

在 `character_config.agent_config.agent_settings.mental_health_agent` 下填写：

```yaml
decision:
  enabled: true
  base_url: '填写决策服务的 OpenAI 兼容地址，包含 /v1'
  model: '填写决策服务公开的模型名'
  llm_api_key: '填写决策服务的密钥'
  timeout_seconds: 15
  max_tokens: 300
  temperature: 0.2
```

每轮至多一次决策请求，同时返回 `strategy`、`behavior`、`voice`。超时、连接失败、缺失字段、
非法 JSON 或越界参数会回退本地规则。高风险输入直接走固定安全回应，跳过两个模型。
不要把 SFT、ORPO 两套对话适配器自动解释为已经训练好的 Decision 模型。

## 存储与测试

`mental_health_memory/psychological_state.jsonl` 保存非诊断性的结构化状态，独立于
`chat_history` 原始聊天记录。当前按 `conf_uid:history_uid` 隔离；重新打开同一历史可以继续
读取状态，新建历史会使用另一作用域。跨历史的稳定用户身份与统一长期档案尚未实现。

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\uv.exe lock --check --offline
```

回归覆盖 Safety 拦截、状态隔离、历史切换、Decision JSON/超时回退、表情来源、
语音发送顺序与立即播放回执，以及关闭 ASR 后的输入行为。

2026-09-22 本机验证结果：25 项测试通过，Ruff 检查通过，`pip check` 无依赖冲突，
`uv lock --check --offline` 通过。ORPO 模型列表和前端首页均返回 HTTP 200，
此前关闭 ASR 时返回预期的 HTTP 503；本轮启用后真实 WAV 识别返回 200。网页普通对话完整显示并从播放状态恢复空闲；
高风险测试跳过对话模型，并写入 `critical / crisis_support` 状态。已看到 Live2D
角色正常显示；语音验证依据为音频生成、前端播放状态及播放完成回执，未做主观音质评测。

上述为早期基线记录。表达执行与长期状态现已实现，最新回归为 66 项后端、5 项前端专项测试通过。真人麦克风和表达观感验收后置；独立 Decision 模型尚待部署。

## 语音输入安装、检查与验收（2026-09-22 更新）

官方资源说明：[Sherpa-ONNX SenseVoice 模型](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html)。
下载脚本固定官方压缩包的 SHA256，校验后仅提取模型、词表、许可证和中文样例。
本机已经下载完毕并成功加载，无需重复安装。

```powershell
.\.venv\Scripts\python.exe scripts/prepare_sensevoice.py
.\.venv\Scripts\python.exe scripts/check_mental_health.py
```

ASR 配置位于 `character_config.asr_config`：

```yaml
enabled: true
asr_model: sherpa_onnx_asr
sherpa_onnx_asr:
  model_type: sense_voice
  sense_voice: './models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/model.int8.onnx'
  tokens: './models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/tokens.txt'
  num_threads: 4
  use_itn: true
  provider: cpu
```

不要把未下载完整的旧压缩包当作模型。输入限制为每段 60 秒；上传支持 8～48 kHz、
单/双声道 PCM16 WAV，自动转为 16 kHz 单声道；WebSocket 输入应为 16 kHz、[-1,1]
归一化浮点数据。空音频、静音、损坏音频和空识别结果会提示重试，不发送给对话模型。

真实后端协议验证（会创建测试聊天历史，使用合成播放回执）：

```powershell
.\.venv\Scripts\python.exe scripts/smoke_voice_pipeline.py models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/test_wavs/zh.wav
.\.venv\Scripts\python.exe scripts/smoke_voice_recovery.py
```

真人验收：浏览器允许麦克风 → 连续说三句话 → 核对识别文字 → 等待每轮播报恢复空闲 →
播放途中点举手打断 → 再说一句，确认旧回复停止且新回复正常。可使用普通问候和工作压力等
虚构示例，不需要提供个人经历。摄像头不参与本次验收。

## Decision 接入补充（2026-09-22）

真人麦克风验收按用户要求后置。Decision 固定协议、角色能力约束、回退与来源记录已完成开发，独立服务尚未部署，本机继续使用规则决策。
配置与联调命令见 [Decision 接入说明](mental_health_decision.md)；规则样例可运行 `.venv\Scripts\python.exe scripts/check_decision.py --rules-only`。
任务 3、4 后已重启服务并加载新构建 `frontend-src/dist/web` 与 local_user SQLite 模式。旧配置备份位于本机忽略目录 `private/baselines/conf-before-tasks345.yaml`。独立 Decision 仍保持关闭。

## 任务 3～5 的启动与资料

模型启动可使用 `.venv\Scripts\python.exe scripts/run_dialogue_api.py --adapter orpo`，网页仍使用 `.venv\Scripts\python.exe run_server.py`。若服务因终端关闭而退出，按这两个命令重新启动；不得同时重复启动占用相同端口的服务。

新前端构建：进入 `frontend-src` 执行 `npm ci --ignore-scripts` 和 `npm run build:web`。原 `frontend` 子模块构建保留；将 `system_config.frontend_dir` 改回 `frontend` 可回退界面，动作与注视扩展将不再执行。

长期状态管理见 [长期状态说明](mental_health_long_term.md)，评估命令和演示步骤见 [评估说明](mental_health_evaluation.md)，本轮模型回答与消融对照见 [比较报告](mental_health_comparison.md)。

顺序复跑结果见 [顺序模型对照](mental_health_sequential_comparison.md)。`local_user` 模式请从后端地址 `http://localhost:12393` 打开页面；HTTP/WS 来源校验会拒绝其他网站、file:// 和不同端口的开发页面。本地脚本仍可使用无 Origin 连接，这不是多用户认证。
