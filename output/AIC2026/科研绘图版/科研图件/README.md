# 心迹技术方案科研图件

本包包含技术方案中的 7 组图、可编辑 SVG、矢量 PDF、600 dpi PNG、作图数据 CSV 和 Python 脚本。图件采用 Nature 风格的白底、克制配色、多面板及直接标注；版面按竞赛报告 150 mm 正文宽度嵌入。

| 编号 | 图件 | 证据与解释 |
|---|---|---|
| 1 | 系统架构 | 项目认知、决策、表达和安全分支的结构示意 |
| 2 | 按日统计算法 | daily_v2 的日历窗口、来源分层、有效日和新鲜度门槛 |
| 3 | 聚合机制对照 | 6 组合成回放中的频次差异、来源分层与重复不变性 |
| 4 | 数据构建与组成 | SFT 数据筛选计数及 ORPO 全部偏好对类别 |
| 5 | 训练与验证曲线 | 两次独立训练的原始 trainer_state.json 日志点 |
| 6 | 时延与资源 | 18 次实际协议请求和 158 次整机资源采样 |
| 7 | 机制消融 | 固定合成场景的策略变化及固定文本 TTS 时长 |

## 文件使用

- SVG 的文字保留为可编辑文本；需要安装 Arial 和 Microsoft YaHei。PDF 保留矢量线条并嵌入字体。
- `source_data/` 保存全部定量绘图数据；`source_manifest.json` 记录原始文件位置和 SHA-256。
- `figure_contract.json` 记录每幅图的结论、结构、统计范围与输出要求。
- `make_figures.py` 读取项目和模型训练目录，生成 6 幅定制图、源数据及训练曲线 VisualSpec。
- `training_sciplot_verified/` 是图 5 的独立 SciPlot 项目，包含冻结 CSV、VisualSpec、渲染入口与通过的 QA 报告。
- `*-vector-qa.json` 与 `vector_qa_summary.json` 记录 7 幅图的 SVG/PDF 矢量检查结果。

## 重绘

在原项目根目录使用 Python 3.14 运行 `make_figures.py`。本机独立解释器位于 `tmp/aic_figures/plot-env/Scripts/python.exe`。脚本也可接受第一个参数作为项目根目录；模型日志默认读取 `D:/模型微调`。

图 5 由已安装的 `sciplot-figure-skill/scripts/sciplot.py` 生成，命令参数为：

```text
run --profile standard --spec <本包>/training_sciplot/visualspec.json --out-dir <新的输出目录> --outputs png,svg,pdf --claim manuscript --json
```

也可以使用 `training_sciplot_verified/visualspec.json` 及其同级冻结 input 文件，独立重绘训练曲线。输出目录使用新目录，避免覆盖已交付的校验结果。

## 核验记录

图 5 通过 SciPlot standard 工作流的数据映射、数据与图形语义、画布及矢量输出检查，无自动可读性警告。其余图按项目数据定制绘制，经过边界检查、原始数值核对、SVG/PDF 检查及人工视觉检查；不把定制图的矢量检查描述为完整语义验证。

报告逐页检查了 22 页，核对 7 个图题、13 张三线表、目录和 PDF 大小。图件明确区分算法示意、合成输入实验与真实服务测量。曲线保留原始日志点，每条适配路线仅一次训练；未添加额外随机种子、显著性符号或临床效果数据。

设计与工具依据为已安装的 [nature-figure](https://github.com/jing1312/nature-figure-skill) 和 [sciplot-figure-skill](https://github.com/peterbruce716-art/sciplot-figure-skill)。图件用于本次 AIC 技术方案，未进行 Nature 期刊投稿合规认证。
