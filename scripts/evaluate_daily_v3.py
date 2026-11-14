"""Deterministic v2/v3 comparison using explicitly synthetic observations."""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from open_llm_vtuber.mental_health.long_term import (  # noqa: E402
    DailyV3Settings,
    summarize_daily_trend,
    summarize_daily_trend_v3,
)
from open_llm_vtuber.mental_health.schemas import (  # noqa: E402
    DecisionContext,
    PsychologicalState,
    SafetyCheckResult,
)
from open_llm_vtuber.mental_health.decision_client import RuleBasedDecisionClient  # noqa: E402
from open_llm_vtuber.mental_health.decision_coordinator import coordinate_decision  # noqa: E402


def fixture_states(fixture):
    return [
        PsychologicalState(
            timestamp=row["timestamp"],
            estimator_source="user_correction"
            if "correction" in row
            else row["source"],
            observed_dimensions=["stress"],
            emotion={"stress": row.get("correction", row["stress_input"])},
        )
        for row in fixture["records"]
    ]


def scenarios():
    path = ROOT / "tests/fixtures/daily_v3_14_day.json"
    fixture = json.loads(path.read_text("utf8"))
    now = datetime(2026, 11, 15, 4, tzinfo=timezone.utc)

    def row(day, score, source="context_v2"):
        return PsychologicalState(
            timestamp=now - timedelta(days=day),
            estimator_source=source,
            observed_dimensions=["stress"],
            emotion={"stress": score},
        )

    baseline = [row(i, 0.05) for i in range(7, 14)]
    return path, {
        "原14日夹具": (
            fixture_states(fixture),
            datetime.fromisoformat(fixture["trend"]["as_of"].replace("Z", "+00:00")),
        ),
        "缺失": ([], now),
        "单日": ([row(0, 0.8)], now),
        "连续上升": (
            baseline
            + [
                row(6 - i, value)
                for i, value in enumerate([0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4])
            ],
            now,
        ),
        "平稳": ([row(i, 0.4) for i in range(14)], now),
        "来源分歧": (
            [row(i, 0.9) for i in range(7)]
            + [row(i, 0.1, "user_report") for i in range(3)],
            now,
        ),
    }


async def evaluate(output):
    fixture, cases = scenarios()
    results = {}
    client = RuleBasedDecisionClient()
    for name, (rows, now) in cases.items():
        v2 = summarize_daily_trend(rows, now)
        v3 = summarize_daily_trend_v3(rows, now)
        decisions = {}
        for trend in (v2, v3):
            context = DecisionContext(
                user_text="合成普通发言",
                current_state=PsychologicalState(),
                safety=SafetyCheckResult(action="allow"),
                long_term_trend=trend.model_dump(mode="json"),
            )
            result = coordinate_decision(await client.decide(context), context)
            decisions[trend.version] = {
                "strategy": result.strategy.primary,
                "winner_role": result.trace.coordination.winner_role,
                "reason_codes": result.trace.coordination.reason_codes,
            }
        results[name] = dict(
            as_of=now.isoformat(),
            decisions=decisions,
            preferred_source=v3.preferred_sources["stress"],
            dimensions={
                source: {
                    "v2": v2.sources[source]
                    .dimensions["stress"]
                    .model_dump(mode="json"),
                    "v3": v3.sources[source]
                    .dimensions["stress"]
                    .model_dump(mode="json"),
                }
                for source in v3.sources
            },
        )
    data = {
        "synthetic": True,
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "parameters": DailyV3Settings().model_dump(),
        "scenarios": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf8"
    )

    def score(value):
        return "null" if value is None else f"{value:.3f}"

    lines = [
        "# 日趋势 v3 对照",
        "",
        "2026-11-15。以下来自原 14 日虚构夹具和五类确定性合成场景。所有决策经过实际规则客户端及协调器。",
        "",
        "| 场景 | v2 最终策略 | v3 最终策略 | v3 历史参考来源 |",
        "|---|---|---|---|",
    ]
    for name, r in results.items():
        lines.append(
            f"| {name} | {r['decisions']['daily_v2']['strategy']} | {r['decisions']['daily_v3']['strategy']} | {r['preferred_source'] or '证据不足'} |"
        )
    lines += [
        "",
        "| 场景 | 来源 | 观测日 | v2 日均值 | v3 平滑值 | 80%区间 | 上升起点 | 来源分歧 |",
        "|---|---|---:|---:|---:|---|---|---|",
    ]
    for name, r in results.items():
        for source, versions in r["dimensions"].items():
            a, b = versions["v2"], versions["v3"]
            interval = (
                "null"
                if b["interval80"] is None
                else "～".join(score(x) for x in b["interval80"])
            )
            lines.append(
                f"| {name} | {source} | {b['observed_days']} | {score(a['mean'])} | {score(b['weighted_mean'])} | {interval} | {b['alert_started_at'] or 'null'} | {'有' if b['source_disagreement'] else '无'} |"
            )
    lines += [
        "",
        "原夹具中的三条 correction 按修改后的值归入 user_correction。测试逐项核对原夹具的整份 daily_v2 快照。缺失日期保持空白，原始记录条数仅作诊断。",
        "",
        "## 算法与配置",
        "",
        "daily_v3 先复用 v2 的自然日、来源、去重与新鲜度判定，再对每个来源和维度独立计算。半衰期默认 3 天，日权重为 2 的负日龄除以半衰期次幂，平滑值为当前 7 个自然日内有效日均值的加权平均。",
        "",
        "80%区间采用固定随机种子 0、默认 1000 次按日成对重采样，保留每个样本的日龄权重，取加权均值分布的第10和90百分位。至少需3个观测日，并同时满足 min_observed_days。区间是工程展示用的重采样范围。序列相关性、小样本覆盖率和真实用户适用性仍需验证。[SciPy 的 percentile bootstrap 定义](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)",
        "",
        "单侧 CUSUM 以同来源、同维度前一周至少3个有效日的均值为基线。当前周按自然日递推 S=max(0,S+日均值−基线−k)，默认 k=0.03，阈值 h=0.35。最后连续3个相邻观测日的偏差须为正，且 S 严格超过阈值才给出 rising。缺失一天即重置当前累计和与连续日计数，缺证据或已过期时返回 null。起点为当前累计和最近从零转正的观测日期。参数在0～1原始分值尺度上设定，属于工程默认值。[NIST 的单侧 CUSUM 递推](https://www.itl.nist.gov/div898/software/dataplot/refman1/auxillar/cusum.htm)",
        "",
        "本周同日系统估计与自报相差严格超过0.3时，标记来源分歧，该维度的历史判断选择自报。比较沿用 v2 日均值保留三位小数的精度。若自报天数不足或过期，该维度暂不参与历史推断。没有分歧时按系统估计、自报、用户修改的顺序选择有效来源。来源分数分别保存。",
        "",
        "模型投影仅暴露被选中且有效来源的平滑值、区间与告警，其余来源数值屏蔽。独立决策模型和对话模型均使用该投影，recent_states 的逐条旧均值不会重新进入 v3 模型上下文。当前安全、明确诉求和建议偏好继续由既有协调优先级处理。",
        "",
        "## 启用与复测",
        "",
        "默认模板仍使用 daily_v2。将 mental_health_agent.memory.trend.version 设为 daily_v3 即可选择新版。本机当前配置沿用既有版本。",
        "",
        "```yaml",
        "trend:",
        "  version: daily_v3",
        "  timezone: Asia/Shanghai",
        "  min_observed_days: 3",
        "  daily_v3:",
        "    half_life_days: 3.0",
        "    bootstrap_samples: 1000",
        "    cusum_k: 0.03",
        "    cusum_threshold: 0.35",
        "    cusum_min_run_days: 3",
        "```",
        "",
        "```powershell",
        ".\\.venv\\Scripts\\python.exe scripts/evaluate_daily_v3.py",
        "```",
        "",
        "## 实施验证（2026-11-15）",
        "",
        "后端 unittest 全量 215 项通过，前端 node:test 全量 23 项通过，生产网页构建成功。Ruff 检查与格式检查通过。新增 9 项后端测试覆盖确定性重采样、缺失与单日、CUSUM 连续与中断、来源分歧与模型投影、当前诉求和安全优先级、SQLite 入口及原 v2 完整快照；前端新增 4 项测试覆盖区间带、断点、上升提示与 v2 呈现兼容。",
        "",
        "使用独立虚构档案及实际趋势 API 检查浏览器：1440×1080 和 390×844 均显示区间带、上升标记、来源分歧和自报优先提示。手机视口与文档宽度均为390像素。截图见 [桌面界面](evidence/task5-daily-v3.png) 和 [手机界面](evidence/task5-daily-v3-mobile.png)。未使用真实心理档案。",
        "",
        "全量 TypeScript 检查仍有585项既有错误，与任务四基线逐行对照一致。页面重载仍出现既有 Live2D 初始化控制台异常，随后头像正常显示；本任务未处理 SDK 问题。统计区间覆盖率与 CUSUM 参数尚未用真实配对数据校准。",
        "",
    ]
    output.write_text("\n".join(lines), "utf8")
    print("6 synthetic scenarios evaluated")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/mental_health_daily_v3.md"
    )
    asyncio.run(evaluate(parser.parse_args().output))
