import {
  dimensions,
  intentLabels,
  preferenceLabels,
  reasonLabels,
  roleLabels,
  strategyLabels,
  responseExplanation,
  sources,
} from "./types";
import type { Turn } from "./types";

export function ResponseReason({ turn }: { turn?: Turn }) {
  return (
    <details className="xj-response-reason">
      <summary>为什么这样回应</summary>
      <p>{responseExplanation(turn)}</p>
      {turn?.trace.late_output_flag && (
        <p>完整回复检查记录了跨句风险，已发出的文字仍保留在本轮记录中。</p>
      )}
    </details>
  );
}

export function ArbitrationSteps({ turn }: { turn: Turn }) {
  const trace = turn.trace.coordination;
  const state = turn.state_estimate;
  const risk = state
    ? {
        low: "低风险",
        elevated: "困扰信号升高",
        high: "高风险",
        critical: "即时危险",
      }[state.risk_level] || state.risk_level
    : "本轮风险级别未记录";
  const winner = trace?.winner_role;
  return (
    <>
      <li>
        <b>输入</b>
        <span>本轮请求已接收</span>
      </li>
      <li>
        <b>安全检查</b>
        <span>{risk}</span>
        {turn.trace.source === "safety_gate" && (
          <small>采用生成前固定回复</small>
        )}
        {turn.trace.output_safety_override && <small>输出已执行安全调整</small>}
        {turn.trace.late_output_flag && <small>整段复查发现跨句风险</small>}
      </li>
      <li>
        <b>意图与状态</b>
        <span>
          {intentLabels[turn.intent.primary] || turn.intent.primary} ·{" "}
          {preferenceLabels[turn.intent.advice_preference] ||
            turn.intent.advice_preference}
        </span>
        <small>
          {state
            ? Object.entries(dimensions)
                .map(([key, label]) => {
                  const value = state.emotion[key as keyof typeof dimensions];
                  return state.observed_dimensions.includes(
                    key as keyof typeof dimensions,
                  ) && value !== null
                    ? `${label} ${value}/1`
                    : `${label} 未观测`;
                })
                .join(" · ")
            : "本轮状态快照未记录"}
        </small>
        {state?.fallback_reason && (
          <small>状态提取回退到规则 · {state.fallback_reason}</small>
        )}
      </li>
      <li>
        <b>各角色提议</b>
        {trace?.proposals?.length ? (
          <ul className="xj-proposals">
            {trace.proposals.map((proposal, index) => (
              <li key={`${proposal.role}-${index}`}>
                <strong>
                  {roleLabels[proposal.role]}
                  {proposal.evidence_codes.includes("rule_proposal")
                    ? "（规则）"
                    : proposal.evidence_codes.includes("model_fallback")
                      ? "（规则回退）"
                      : ""}
                </strong>
                <span>
                  {proposal.suggested_strategy
                    ? strategyLabels[proposal.suggested_strategy] ||
                      proposal.suggested_strategy
                    : "未提出策略调整"}
                </span>
                <small>
                  {proposal.evidence_codes
                    .map((code) => reasonLabels[code] || code)
                    .join("、")}
                  {proposal.confidence &&
                    ` · 把握程度 ${{ low: "低", medium: "中", high: "高" }[proposal.confidence]}`}
                </small>
              </li>
            ))}
          </ul>
        ) : (
          <span>该历史记录未保存角色提议</span>
        )}
        {turn.history_invalidated && (
          <small>记录已纠正或删除，旧历史快照已失效</small>
        )}
        {!turn.history_invalidated && turn.history_context && (
          <details>
            <summary>历史来源与覆盖</summary>
            {Object.entries(turn.history_context.sources).map(
              ([source, metrics]) => (
                <p key={source}>
                  {sources[source as keyof typeof sources] || source} ·{" "}
                  {Object.entries(metrics)
                    .map(
                      ([dim, metric]) =>
                        `${dimensions[dim as keyof typeof dimensions] || dim} ${metric.observed_days}天（${metric.status === "usable" ? "可参考" : metric.status === "stale" ? "过期" : "不足"}）`,
                    )
                    .join("、")}
                </p>
              ),
            )}
          </details>
        )}
      </li>
      <li>
        <b>仲裁胜出</b>
        <span>{winner ? roleLabels[winner] : "胜出角色未记录"}</span>
        <small>
          {trace?.reason_codes
            .map((code) => reasonLabels[code] || code)
            .join("、") || (winner ? "采用当前提议" : "仲裁依据未记录")}
        </small>
        {turn.trace.fallback_reason && (
          <small>决策回退 · {turn.trace.fallback_reason}</small>
        )}
      </li>
      <li>
        <b>最终策略</b>
        <span>
          {strategyLabels[turn.final_strategy] || turn.final_strategy}
        </span>
        {trace?.proposed_strategy && (
          <small>
            初始提议 ·{" "}
            {strategyLabels[trace.proposed_strategy] || trace.proposed_strategy}
          </small>
        )}
      </li>
    </>
  );
}
