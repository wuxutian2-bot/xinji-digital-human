# 心迹提交包索引

本轮版本：`companion-2026-10-01`。所有成果的版本由归档内 `MANIFEST.json` 的源码哈希标识；工作区已有未提交改动，不能只用 Git HEAD 代表本轮代码。

| 材料 | 入口 | 证据性质 |
|---|---|---|
| 四组功能与启动 | [使用说明](companion_product.md) | 可运行产品功能 |
| 本轮验收 | [验收记录](companion_acceptance.md) | 工程测试与合成界面操作 |
| 需求与应用体验 | [试用手册](companion_trial_protocol.md) | 空白执行材料，等待真实数据 |
| 三组合成演示 | `scripts/companion_demo.py` | 固定文字＋实际规则协调，不是模型效果 |
| 状态建模 | [长期状态说明](mental_health_long_term.md) | 分来源、覆盖和过期规则 |
| 诉求协调 | [诉求说明](mental_health_intent.md)、[协议](mental_health_intent_contract.md) | 可解释协调与受限接口 |
| 决策与失败案例 | [协同实验](mental_health_coordination_results.md)、[单来源评分说明](mental_health_single_review_recovery.md) | 历史探索结果，保留限制 |
| 本轮模型和数据卡 | [来源卡](companion_model_data.md) | 原有训练报告摘要、来源与许可边界 |
| 模型运行及来源 | [运行记录](mental_health_runtime.md)、[模型使用](mental_health_phase1_usage.md) | 含历史配置，当前产品配置以本轮说明为准 |
| 冻结评测 | `tests/fixtures/`、`scripts/evaluate_coordination.py` | 合成样例及复现代码 |
| 前端来源 | [UPSTREAM](../frontend-src/UPSTREAM.md) | 上游版本与复用边界 |

## 复用与自研边界

复用 Open-LLM-VTuber 的服务骨架、WebSocket、对话流、语音接口、聊天历史、React/Electron 前端、Live2D 集成。保留根目录和前端许可证、Live2D 单独授权说明，不把上游完整功能计作自研。

自研部分包括 `mental_health/` 下的安全与状态规则、SQLite 档案、daily_v2 分来源统计、诉求估计和决策协调、独立 Decision 合约/回退，以及本轮产品 API、支持偏好与反馈、行动卡、真实执行回放、试用隔离和证据工具。前端本轮入口位于 `components/companion/`，并对聊天、音频回执和布局做集成。

SFT/ORPO 是基于 Qwen3-4B 基座的独立 LoRA 适配器。基座、训练工具、语料和适配器的来源及授权沿用既有训练资料，本轮未新增训练。独立 Decision 仍默认关闭；已有模型实验不能证明其优于规则。本提交包不附带本机模型权重或未获再分发许可的训练数据。

## 冻结与打包

```powershell
.\.venv\Scripts\python.exe scripts/build_companion_submission.py --output output/AIC2026/companion-source.zip
```

工具从 Git 可见的源码及文档构造允许列表，逐文件记录 SHA256，写完后校验 ZIP 和所有哈希；输出名已存在时拒绝覆盖。排除个人配置、数据库、聊天、日志、私有试用资料、环境和模型权重。归档包含运行入口、依赖锁、上游许可证与新功能源码；Live2D 素材和模型按原项目安装流程另行取得。不要直接压缩整个工作目录。

2026-10-02 修订打包清单：加入启动入口依赖的 `upgrade_codes/`、`web_tool/` 及默认背景、头像和说明图片，并在打包前检查关键文件是否齐全。随后完成 [用户界面修订](plans/2026-10-02-companion-user-layout.md) 和 [日常入口与历史修订](companion_history_fix.md)。当前优先使用 `companion-source-20261002-personal.zip`；此前归档保留其各自版本。

### 在新目录复现

归档是源码交付，未包含已安装的环境、构建产物或 Live2D 模型。先从 [Open-LLM-VTuber 上游](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) 取得 `MANIFEST.json` 中 `base_commit` 对应的原始资源，按 `LICENSE-Live2D.md` 的条件保留并使用 `live2d-models/`，再将本归档解压到该目录。不要覆盖正在使用的个人项目。

安装 Python 3.10～3.12 与 uv 后，在新目录执行 `uv sync --frozen`；进入 `frontend-src/` 执行 `npm ci --ignore-scripts` 和 `npm run build:web`。先运行 `uv run run_server.py --help` 检查入口，再依照 [离线合成演示](companion_product.md#离线合成演示) 启动演示。实际模型和语音体验需要额外按运行说明配置对应服务；源码解包检查不代表这些服务已经验证。

本次解包检查使用当前机器已安装的 Python 依赖，在全新解包目录验证入口导入和三组离线案例；没有声称在全新机器上重新安装过全部依赖。检查记录与修订归档同放于 `output/AIC2026/`。

## 参考与表述边界

参考文献采用现有技术方案中的原始来源清单，并复核作者、标题、年份、URL/DOI、访问时间与许可证。模型卡、数据来源和授权未核对的部分明确标待补，不用“开源”代替具体许可。现有技术报告中的文献与训练资料不能当作同学需求调研。

旧报告的 91 项、实施前的 157 项及本轮新增后的测试数量分别保留日期与版本；330 条单来源探索评分不能写成双人独立评阅，也不能写成真人使用成效。新的需求分析、问卷图表、回访率和演示录屏只能在实际收集完成后加入最终参赛材料。
