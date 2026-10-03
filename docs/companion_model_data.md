# 模型与数据来源卡（本轮整理）

整理日期：2026-10-01。本轮新增的是产品入口、试用与证据工具，没有新增训练。训练资料的计数来自本机已有构建报告，摘要及报告哈希见 [来源摘要](evidence/training-provenance.json)。这不等于本轮重新审阅了训练原文或完成临床认证。

| 组成 | 已有来源与用途 | 本轮状态 |
|---|---|---|
| Dialogue 基座 | Qwen3-4B-Instruct-2507；通过 LLaMA-Factory/OpenAI 兼容服务加载 | 沿用；权重不打入源码包 |
| SFT 适配器 | `qwen4b_large_v1_r1`；普通支持对话微调 | 独立 LoRA，不与 ORPO 叠加 |
| ORPO 适配器 | `qwen4b_orpo_qlora`；偏好优化 | 既有本机运行路线；不宣称优于 SFT |
| Decision | 规则默认；独立模型有既有实验与回退 | 本轮不启用或重训独立模型 |
| ASR / TTS | SenseVoice（本机 CPU）／Edge TTS（网络服务） | 真人麦克风和主观音质待验收 |
| 数字人 | 上游 Live2D 集成与既有 mao_pro 素材 | 按根目录 Live2D 授权说明另行准备 |

SFT 构建报告标明来源 `soulchat_v2_r1`，原候选训练 4096、机器筛选保留 3379、补充目标轮次 44、最终训练 3423、冻结验证 128。报告明确 `deployment_eligible: false`、`safety_training_included: false`；机器过滤不等于人工或临床审查，高风险/诊断材料被分离处理，验证集属于开发验证。

ORPO 构建报告为 640 对，训练 576、验证 64。审核来源为 teacher_approved 553、ai_assisted_approved 87、human_approved 0。不得改写为“640 对经过人工临床审阅”。两类报告的文件哈希被保留，未打包原始语料。

本轮合成演示使用脚本生成的固定状态值和模板回复；测试样例来自仓库 `tests/fixtures/`。它们不能作为真实需求、用户体验改善或模型质量证据。成年同学的自报、访谈和操作记录另存本机独立档案，默认不保留对话原文。

许可方面，源码保留 Open-LLM-VTuber 与前端 LICENSE、`LICENSE-Live2D.md`。基座、数据集和适配器的具体许可需随原模型卡/数据卡核对后再决定是否再分发；本包只提供源码、运行模板、来源摘要与文献，不附加未核对许可的训练数据或权重。

既有 [BibTeX 文献](references/companion-existing.bib) 从 2026-09-26 引用规范版原样汇集，保留 SoulChat、Qwen、QLoRA、ORPO、SenseVoice/FunAudioLLM、LLaMA-Factory 等来源。其历史核验说明仍在原材料目录；本轮未把文献背景当作新增实验或用户需求证据。
