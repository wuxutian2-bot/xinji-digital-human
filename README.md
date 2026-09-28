# 心迹——基于长期心理状态建模与多智能体决策的智能数字人

AIC 2026 第八届全球校园人工智能算法精英大赛 · 算法主题赛 AI+心理健康
参赛编号：AIC-2026-73805008 · 团队：小马珍珠

心迹面向成年人日常心理陪伴，构建融合长期心理状态建模、多智能体协同决策与 Live2D 数字人表达的智能支持原型。本项目为非诊断性支持工具，不替代专业心理咨询或医疗服务。

## 核心链路

```
文字/语音输入 → Safety 前置检查 → Intent 诉求识别 → 心理状态估计 + 长期状态读取
→ Decision 结构化决策 → Coordinator 诉求优先协调 → ORPO 对话模型
→ Safety 后置检查 → 状态写入 → TTS / Live2D 表达
```

- 安全门：高风险输入直接进入固定危机支持路径，不调用模型。
- 诉求优先协调：用户拒绝建议、请求建议、给出负反馈时，协调器改写决策提议并记录原因码。
- 长期状态：SQLite 存储，daily_v2 按日等权聚合，系统估计 / 用户自报 / 用户纠正分层汇总。
- 对话模型：Qwen3-4B + SFT / ORPO QLoRA 适配器，经 LLaMA-Factory 提供 OpenAI 兼容接口。

## 目录

| 路径 | 内容 |
| --- | --- |
| `src/open_llm_vtuber/mental_health/` | 安全、诉求、状态、决策、协调、长期记忆等核心模块 |
| `src/open_llm_vtuber/agent/agents/mental_health_agent.py` | 心理支持智能体主流程 |
| `scripts/` | 服务启动、评测、回放、消融与记忆管理脚本 |
| `tests/` | 回归测试与固定场景用例 |
| `docs/` | 设计、运行与各阶段结果说明 |
| `config_templates/` | 配置模板（含 ORPO/SFT/Decision 服务模板） |
| `frontend-src/` | 前端源码（含点头、注视等本地改动） |
| `output/AIC2026/科研绘图版/科研图件/` | 技术方案图件、绘图脚本与源数据 CSV |

## 运行

详见 [docs/mental_health_runtime.md](docs/mental_health_runtime.md)。简要步骤：

1. 安装依赖：`pip install -r requirements.txt`，并执行 `git submodule update --init frontend`。
2. 复制 `config_templates/conf.ZH.default.yaml` 为 `conf.yaml`，按模板填写模型服务地址与密钥。
3. 用 LLaMA-Factory 加载 Qwen3-4B 基座与 ORPO 适配器（`config_templates/mental_health_orpo_api.yaml`）。
4. 运行 `python run_server.py`，打开 http://localhost:12393 。

测试：`python -m pytest tests`

## 未包含的内容

模型权重与适配器、本机配置、运行日志与评测原始输出、用户对话记录与记忆数据库均未上传。

## 致谢与许可

本项目基于 [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) 二次开发，原项目说明见 [README.Open-LLM-VTuber.md](README.Open-LLM-VTuber.md)。代码遵循原项目 [MIT License](LICENSE)；Live2D 模型与 Cubism SDK 遵循 [LICENSE-Live2D.md](LICENSE-Live2D.md) 及其各自许可。
