import { useEffect, useRef, useState } from "react";
import { useCompanion } from "./companion-context";
import { dimensions, sources, strategyLabels } from "./types";
import type { Dimension, Feedback, Source, StateRecord, Turn } from "./types";
import { calendarDays, dailyValues } from "@/utils/companion-trend";

const date = (value: string) =>
  new Date(value).toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
  });
const feedbackLabel: Record<Feedback, string> = {
  helpful: "有帮助",
  unhelpful: "没帮助",
  unspecified: "未评价",
};
const sourceLabel = (value: string) =>
  sources[value as Source] ||
  { keyword_v1: "系统估计", context_v2: "系统估计", legacy: "来源未知" }[
    value
  ] ||
  value;
const reasonLabels: Record<string, string> = {
  safety_priority: "安全优先",
  explicit_closure: "用户明确结束",
  advice_declined: "用户拒绝建议",
  listen_requested: "用户希望倾诉",
  advice_requested: "用户主动求助",
  clarification_requested: "用户希望梳理",
  negative_feedback: "回应没有帮助",
  output_safety_override: "输出安全调整",
  protocol_control_ignored: "忽略协议操控",
  protocol_boundary_response: "采用边界澄清回复",
};

function Scores({
  values,
  setValues,
}: {
  values: Partial<Record<Dimension, number>>;
  setValues: (v: Partial<Record<Dimension, number>>) => void;
}) {
  return (
    <div className="xj-scores">
      {Object.entries(dimensions).map(([key, label]) => {
        const dim = key as Dimension;
        const active = values[dim] !== undefined;
        return (
          <div className="xj-score" key={dim}>
            <label>
              <input
                type="checkbox"
                checked={active}
                onChange={(e) => {
                  const next = { ...values };
                  if (e.target.checked) next[dim] = 0.5;
                  else delete next[dim];
                  setValues(next);
                }}
              />
              {label}
            </label>
            {active ? (
              <>
                <input
                  aria-label={`${label}分数`}
                  type="range"
                  min="0"
                  max="10"
                  step="1"
                  value={(values[dim] ?? 0) * 10}
                  onChange={(e) =>
                    setValues({ ...values, [dim]: Number(e.target.value) / 10 })
                  }
                />
                <output>{((values[dim] ?? 0) * 10).toFixed(0)} / 10</output>
              </>
            ) : (
              <span className="xj-muted">暂不记录</span>
            )}
          </div>
        );
      })}
      <p className="xj-muted">
        0 表示没有这种感受，10 表示非常强烈。勾选想记录的感受，也可以留空。
      </p>
    </div>
  );
}

function Overview() {
  const { records, profile, setTab, mutate, busy } = useCompanion();
  const [values, setValues] = useState<Partial<Record<Dimension, number>>>({});
  const [notice, setNotice] = useState("");
  return (
    <>
      <section className="xj-card xj-checkin">
        <div className="xj-checkin-heading">
          <h3>现在，感觉怎么样？</h3>
          <p className="xj-muted">不必整理好心情，只记下你愿意记录的部分。</p>
        </div>
        <Scores values={values} setValues={setValues} />
        <button
          className="xj-primary"
          disabled={busy || Object.keys(values).length === 0}
          onClick={async () => {
            if (
              await mutate("/states", "POST", {
                timestamp: new Date().toISOString(),
                emotion: values,
              })
            ) {
              setValues({});
              setNotice("已记下你此刻的感受。");
            }
          }}
        >
          记下这一刻
        </button>
        <span role="status" className="xj-success">
          {notice}
        </span>
      </section>
      <button className="xj-history-link" onClick={() => setTab("trend")}>
        <span>
          <strong>看看最近的自己</strong>
          <small>
            {profile?.synthetic_demo
              ? "这里的历史是示例，你可以先熟悉一下"
              : records.length
                ? "回顾感受的变化，也可以修改过去的记录"
                : "慢慢积累记录，变化会在这里留下痕迹"}
          </small>
        </span>
        <span aria-hidden="true">→</span>
      </button>
    </>
  );
}

function Trends() {
  const { trend, setTab, profile } = useCompanion();
  const [dimension, setDimension] = useState<Dimension>("stress");
  const days = trend
    ? calendarDays(trend.previous_window.start, trend.settings.timezone)
    : [];
  const colors: Record<Source, string> = {
    system_estimate: "#82918b",
    user_report: "#236d59",
    user_correction: "#bd7941",
  };
  return (
    <>
      {profile?.synthetic_demo && (
        <p className="xj-muted">这里展示的是示例记录，不是你的真实状态。</p>
      )}
      <section className="xj-card">
        <div className="xj-section-head">
          <h3>最近两周</h3>
          <select
            aria-label="趋势维度"
            value={dimension}
            onChange={(e) => setDimension(e.target.value as Dimension)}
          >
            {Object.entries(dimensions).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="xj-legend">
          {Object.entries(sources).map(([key, label]) => (
            <span key={key}>
              <i style={{ background: colors[key as Source] }} />
              {label}
            </span>
          ))}
        </div>
        {!trend ? (
          <p className="xj-muted">连接后显示你的记录。</p>
        ) : (
          <>
            <svg
              className="xj-chart"
              viewBox="0 0 660 190"
              role="img"
              aria-label={`${dimensions[dimension]}近14天趋势。空白为没有记录，详细数值见下表。`}
            >
              {[0, 5, 10].map((value) => (
                <g key={value}>
                  <line
                    x1="38"
                    x2="640"
                    y1={145 - value * 12}
                    y2={145 - value * 12}
                    stroke="#e4e9e4"
                  />
                  <text x="10" y={149 - value * 12}>
                    {value}
                  </text>
                </g>
              ))}
              <line
                x1="338"
                x2="338"
                y1="15"
                y2="150"
                stroke="#bdc9c0"
                strokeDasharray="4 5"
              />
              <text x="150" y="182">
                前一周
              </text>
              <text x="465" y="182">
                本周
              </text>
              {Object.keys(sources).map((key) => {
                const s = key as Source,
                  metric = trend.sources[s].dimensions[dimension];
                const vals = dailyValues(
                  days,
                  metric.previous_daily_means,
                  metric.daily_means,
                );
                return (
                  <g key={s}>
                    {vals.map((value, i) =>
                      value === null ? null : (
                        <g key={days[i]}>
                          {i > 0 && vals[i - 1] !== null && (
                            <line
                              x1={40 + (i - 1) * 46}
                              y1={145 - vals[i - 1]! * 120}
                              x2={40 + i * 46}
                              y2={145 - value * 120}
                              stroke={colors[s]}
                              strokeWidth="2"
                            />
                          )}
                          <circle
                            cx={40 + i * 46}
                            cy={145 - value * 120}
                            r="4"
                            fill={colors[s]}
                          >
                            <title>
                              {days[i]} {sources[s]} {value * 10}/10
                            </title>
                          </circle>
                        </g>
                      ),
                    )}
                  </g>
                );
              })}
            </svg>
            <div className="xj-metrics">
              {Object.entries(sources).map(([key, label]) => {
                const metric =
                  trend.sources[key as Source].dimensions[dimension];
                return (
                  <div key={key}>
                    <span>{label}</span>
                    <strong>
                      {metric.observed_days}
                      <small> / 7 天</small>
                    </strong>
                    <span>
                      {metric.stale
                        ? "最近没有新记录"
                        : metric.eligible_for_decision
                          ? "可以看看这一周的变化"
                          : "再多记录几天，慢慢看变化"}
                    </span>
                  </div>
                );
              })}
            </div>
            <details>
              <summary>查看逐日数值</summary>
              <div className="xj-table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>日期</th>
                      {Object.values(sources).map((label) => (
                        <th key={label}>{label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {days.map((day, i) => (
                      <tr key={day}>
                        <td>{day}</td>
                        {Object.keys(sources).map((source) => {
                          const metric =
                            trend.sources[source as Source].dimensions[
                              dimension
                            ];
                          const value = dailyValues(
                            days,
                            metric.previous_daily_means,
                            metric.daily_means,
                          )[i];
                          return (
                            <td key={source}>
                              {value === null
                                ? "未记录"
                                : `${(value * 10).toFixed(1)} / 10`}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        )}
      </section>
      <button className="xj-history-link" onClick={() => setTab("records")}>
        <span>
          <strong>查看与修改记录</strong>
          <small>如果记录不符合你的感受，随时可以调整或删除</small>
        </span>
        <span aria-hidden="true">→</span>
      </button>
      <section className="xj-card">
        <h3>这一周，慢慢看</h3>
        <p className="xj-muted">
          你的记录和聊天中的系统估计分开呈现；以你的感受为准。
        </p>
        {trend ? (
          Object.entries(sources).map(([source, label]) => {
            const metric =
              trend.sources[source as Source].dimensions[dimension];
            return (
              <p className="xj-week-note" key={source}>
                <strong>{label}</strong>
                <span>
                  {metric.observed_days === 0
                    ? "这一周还没有记录。"
                    : `这一周有 ${metric.observed_days} 天${dimensions[dimension]}记录。`}
                  {metric.observed_days > 0 &&
                    (metric.stale
                      ? "最近没有新记录，先不判断变化。"
                      : !metric.eligible_for_decision || metric.mean === null
                        ? "再多记录几天，就能更好地回顾。"
                        : `按每天的平均分计算，本周平均 ${(metric.mean * 10).toFixed(1)} 分（满分 10 分）。`)}
                  {metric.eligible_for_decision &&
                    metric.change !== null &&
                    `与前一周相比${Math.abs(metric.change * 10) < 0.05 ? "基本持平。" : `${metric.change > 0 ? "高" : "低"}了 ${Math.abs(metric.change * 10).toFixed(1)} 分。`}`}
                </span>
              </p>
            );
          })
        ) : (
          <p className="xj-muted">记录一些感受后，再回来看看。</p>
        )}
      </section>
    </>
  );
}

function RecordCard({ record }: { record: StateRecord }) {
  const { mutate, busy } = useCompanion();
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [values, setValues] = useState<Partial<Record<Dimension, number>>>({});
  return (
    <article className="xj-card">
      <div className="xj-section-head">
        <time>{date(record.state.timestamp)}</time>
        <span className="xj-tag">
          {sourceLabel(record.state.estimator_source)}
        </span>
      </div>
      <div className="xj-record-values">
        {Object.entries(dimensions).map(([key, label]) => {
          const dim = key as Dimension,
            observed = record.state.observed_dimensions.includes(dim);
          return (
            <span key={key}>
              {label}{" "}
              <b>
                {observed
                  ? `${(record.state.emotion[dim] * 10).toFixed(1)}/10`
                  : "—"}
              </b>
              <small>
                {observed
                  ? sourceLabel(
                      record.state.dimension_sources?.[dim] ||
                        record.state.estimator_source,
                    )
                  : "未记录"}
              </small>
            </span>
          );
        })}
      </div>
      {editing && (
        <>
          <p>选择想调整的感受，其他记录会保留。</p>
          <Scores values={values} setValues={setValues} />
          <button
            className="xj-primary"
            disabled={busy || !Object.keys(values).length}
            onClick={async () => {
              if (
                await mutate(`/states/${record.id}`, "PATCH", {
                  emotion: values,
                })
              ) {
                setEditing(false);
                setValues({});
              }
            }}
          >
            保存修改
          </button>
        </>
      )}
      <div className="xj-row">
        <button onClick={() => setEditing(!editing)}>
          {editing ? "取消修改" : "修改这条记录"}
        </button>
        <button className="xj-danger" onClick={() => setDeleting(!deleting)}>
          删除记录
        </button>
      </div>
      {deleting && (
        <div className="xj-confirm">
          <p>确定删除这条感受记录吗？变化图会随之更新，聊天内容会保留。</p>
          <button
            disabled={busy}
            className="xj-danger"
            onClick={() => void mutate(`/states/${record.id}`, "DELETE")}
          >
            确认删除这条记录
          </button>
          <button onClick={() => setDeleting(false)}>保留</button>
        </div>
      )}
    </article>
  );
}

function Actions() {
  const { actions, mutate, busy } = useCompanion();
  return (
    <>
      <p className="xj-muted">
        一次只保留一个待尝试的小步骤。你可以完成它，也可以跳过；不需要解释。
      </p>
      {!actions.length && (
        <div className="xj-empty">
          从“一起想办法”开始。回答下方可以保存你愿意尝试的一小步。
        </div>
      )}
      {actions.map((action) => (
        <article key={action.id} className="xj-card">
          <span className="xj-tag">
            {
              { pending: "待尝试", completed: "已完成", skipped: "已跳过" }[
                action.status
              ]
            }
          </span>
          <h3>{action.text}</h3>
          <p className="xj-muted">{date(action.created_at)}</p>
          {action.status === "pending" ? (
            <div className="xj-row">
              <button
                className="xj-primary"
                disabled={busy}
                onClick={() =>
                  void mutate(`/actions/${action.id}`, "PATCH", {
                    status: "completed",
                  })
                }
              >
                我完成了
              </button>
              <button
                disabled={busy}
                onClick={() =>
                  void mutate(`/actions/${action.id}`, "PATCH", {
                    status: "skipped",
                  })
                }
              >
                这次跳过
              </button>
            </div>
          ) : (
            action.status === "completed" && (
              <div className="xj-row">
                {(["helpful", "unhelpful"] as Feedback[]).map((value) => (
                  <button
                    key={value}
                    aria-pressed={action.feedback === value}
                    disabled={busy}
                    onClick={() =>
                      void mutate(`/actions/${action.id}`, "PATCH", {
                        status: "completed",
                        feedback:
                          action.feedback === value ? "unspecified" : value,
                      })
                    }
                  >
                    {feedbackLabel[value]}
                  </button>
                ))}
              </div>
            )
          )}
        </article>
      ))}
    </>
  );
}

function Replay({ turn }: { turn: Turn }) {
  const origin =
    {
      rules: "规则决策",
      model: "独立模型",
      fallback: "规则回退",
      safety_gate: "安全门",
      not_run: "尚未执行决策",
    }[turn.trace.source] || turn.trace.source;
  return (
    <article className="xj-card">
      <div className="xj-section-head">
        <time>{date(turn.timestamp)}</time>
        <span className="xj-tag">
          {turn.synthetic ? "合成演示" : "本机实际交互"} · {origin}
        </span>
      </div>
      <ol className="xj-flow">
        <li>
          <b>用户诉求</b>
          <span>
            {{
              venting: "倾诉",
              seeking_clarification: "梳理问题",
              seeking_practical_help: "寻求办法",
              ending: "结束交流",
              small_talk: "闲聊",
              seeking_information: "了解信息",
              unknown: "未明确",
            }[turn.intent.primary] || turn.intent.primary}{" "}
            · 偏好：
            {{
              requested: "希望建议",
              declined: "拒绝建议",
              unspecified: "未指定",
            }[turn.intent.advice_preference] || turn.intent.advice_preference}
          </span>
        </li>
        <li>
          <b>历史依据</b>
          <span>
            {turn.history_invalidated
              ? "记录已纠正或删除，旧快照已失效"
              : turn.history_context
                ? "按来源、有效天数与新鲜度读取"
                : "本轮未读取历史"}
          </span>
          {turn.history_context && (
            <details>
              <summary>查看来源与覆盖</summary>
              {Object.entries(turn.history_context.sources).map(
                ([source, metrics]) => (
                  <p key={source}>
                    {sourceLabel(source)}：
                    {Object.entries(metrics)
                      .map(
                        ([dim, m]) =>
                          `${dimensions[dim as Dimension] || dim} ${m.observed_days}天（${m.status === "usable" ? "可参考" : m.status === "stale" ? "过期" : "不足"}）`,
                      )
                      .join("；")}
                  </p>
                ),
              )}
            </details>
          )}
        </li>
        <li>
          <b>决策与协调</b>
          <span>
            {strategyLabels[turn.trace.coordination?.proposed_strategy || ""] ||
              "未记录提议"}{" "}
            → {strategyLabels[turn.final_strategy] || turn.final_strategy}
          </span>
          <small>
            {turn.trace.coordination?.reason_codes
              .map((r) => reasonLabels[r] || r)
              .join("、") || "保留原提议"}
            {turn.trace.fallback_reason &&
              `；回退原因：${turn.trace.fallback_reason}`}
          </small>
        </li>
        <li>
          <b>生成状态</b>
          <span>
            {{ completed: "已生成", pending: "尚未完成", failed: "生成失败" }[
              turn.generation
            ] || turn.generation}
          </span>
        </li>
        <li>
          <b>表达执行</b>
          <span>
            已发送 {turn.sent_segments.filter((s) => s.sent).length} 段 · 播放：
            {{
              completed: "浏览器回执完成",
              failed: "失败",
              interrupted: "被打断",
              unconfirmed: "未确认",
            }[turn.playback] || turn.playback}
          </span>
          {turn.sent_segments.map((s) => (
            <small key={s.id}>
              第 {s.id + 1} 段：{s.has_audio ? "有音频" : "仅文字"}
              {s.tts_error ? "（语音生成失败）" : ""}；语速{" "}
              {s.actions?.voice_applied?.speed ?? "未确认"}；动作{" "}
              {s.actions?.motion || "无新动作"}；未执行的语音参数{" "}
              {s.actions?.voice_applied?.fallback?.join("、") || "无记录"}
            </small>
          ))}
        </li>
      </ol>
      <p className="xj-muted">
        这里显示执行记录。音频回执不代表主观音质、表达自然度或心理效果已得到验证。
      </p>
    </article>
  );
}

function Trial() {
  const { profile, mutate, busy, setTab } = useCompanion();
  const [accepted, setAccepted] = useState(profile?.consent?.accepted ?? false);
  const [retain, setRetain] = useState(
    profile?.consent?.retain_conversation ?? false,
  );
  return (
    <section className="xj-card">
      <h3>由你决定，保留什么</h3>
      <p>
        你可以跳过不想回答的问题，也可以随时离开。心迹陪你整理日常感受，不做诊断。
      </p>
      <p>
        感受记录、保存的小步骤和操作记录留在当前电脑。
        {profile?.synthetic_demo
          ? "现在是示例体验：预置历史为虚构，回复使用固定内容，不调用对话模型或语音服务。"
          : "若使用在线对话或语音服务，相关文字或音频会发送给对应服务商；体验前可以向组织者了解具体配置。"}
      </p>
      {profile?.trial_mode ? (
        <>
          <label className="xj-check">
            <input
              type="checkbox"
              checked={accepted}
              onChange={(e) => setAccepted(e.target.checked)}
            />
            我已成年，了解说明并自愿参加本次体验
          </label>
          <label className="xj-check">
            <input
              type="checkbox"
              checked={retain}
              onChange={(e) => setRetain(e.target.checked)}
            />
            另行同意保留之后的聊天文本，供本次项目复核（可不选）
          </label>
          <p className="xj-muted">
            不保留文本时，关闭会话后不能恢复原对话。取消保留只影响之后的消息；已有文本可在聊天历史中删除。
          </p>
          <button
            className="xj-primary"
            disabled={busy}
            onClick={async () => {
              if (
                (await mutate("/consent", "PUT", {
                  accepted,
                  retain_conversation: accepted && retain,
                })) &&
                accepted
              )
                setTab("overview");
            }}
          >
            {accepted ? "保存选择，开始体验" : "保存我的选择"}
          </button>
          <p role="status">
            当前状态：
            {profile.consent?.accepted ? "已同意体验" : "尚未同意体验"}；
            {profile.consent?.retain_conversation
              ? "保留之后的聊天文本"
              : "不保留之后的聊天文本"}
          </p>
        </>
      ) : (
        <p className="xj-muted">
          当前是个人档案。你可以在聊天历史中删除对话，在“看变化”中查看、修改或删除感受记录。
        </p>
      )}
      <hr />
      <h3>需要现实中的支持</h3>
      <p>
        可以联系你信任的人或学校心理咨询中心。如有紧迫安全风险，请联系当地急救服务。心迹不会自动替你联系任何人。
      </p>
    </section>
  );
}

export function CompanionPanel() {
  const c = useCompanion();
  const dialog = useRef<HTMLDialogElement>(null);
  const body = useRef<HTMLElement>(null);
  const replay = c.tab === "replay";
  const secondary = c.tab === "records" || c.tab === "trial";
  const needsConsent = c.profile?.trial_mode && !c.profile.consent?.accepted;
  const close = () => {
    if (c.demoView) window.location.assign(window.location.pathname);
    else c.close();
  };
  useEffect(() => {
    if (body.current) body.current.scrollTop = 0;
  }, [c.tab, c.open]);
  useEffect(() => {
    if (c.open && !dialog.current?.open) dialog.current?.showModal();
    else if (!c.open && dialog.current?.open) dialog.current.close();
  }, [c.open]);
  return (
    <dialog
      ref={dialog}
      className={`xj-panel xj${replay ? " xj-demo-panel" : ""}`}
      aria-labelledby="xj-title"
      onCancel={close}
      onClose={c.close}
    >
      <header className="xj-header">
        <div className="xj-header-copy">
          {secondary && (
            <button
              className="xj-back"
              onClick={() =>
                c.setTab(c.tab === "records" ? "trend" : "overview")
              }
            >
              ← {c.tab === "records" ? "返回看变化" : "返回我的心迹"}
            </button>
          )}
          {replay && (
            <span className="xj-eyebrow">
              演示工作台 · {c.profile?.label || "连接中"}
            </span>
          )}
          <div className="xj-title-row">
            <h2 id="xj-title">
              {replay
                ? "这次，为什么这样回应"
                : c.tab === "records"
                  ? "过去的记录"
                  : c.tab === "trial"
                    ? "数据与隐私"
                    : "我的心迹"}
            </h2>
            {!replay && c.profile?.synthetic_demo && (
              <span className="xj-sample-tag">示例体验</span>
            )}
          </div>
          <p>
            {replay
              ? "查看实际发生的决策与执行，供演示和复核使用。"
              : c.tab === "records"
                ? "感受由你定义，不准确的地方可以随时修改。"
                : c.tab === "trial"
                  ? "开始之前，先了解你的选择。"
                  : "留一点时间，照顾自己的感受。"}
          </p>
        </div>
        <button
          aria-label={replay ? "返回日常使用" : "关闭我的心迹"}
          className="xj-close"
          onClick={close}
        >
          ×
        </button>
      </header>
      {!secondary && !replay && (
        <nav className="xj-tabs" aria-label="我的心迹功能">
          {(
            [
              ["overview", "记一记"],
              ["trend", "看变化"],
              ["actions", "小步骤"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              aria-current={c.tab === key ? "page" : undefined}
              onClick={() => c.setTab(key)}
            >
              {label}
            </button>
          ))}
        </nav>
      )}
      <main ref={body} className="xj-body">
        {c.error && (
          <div className="xj-alert" role="alert">
            {c.error}
            <button onClick={() => void c.refresh()}>重新连接</button>
          </div>
        )}
        {c.loading && (
          <p className="xj-muted" role="status">
            正在更新记录…
          </p>
        )}
        {needsConsent && c.tab !== "trial" && !replay ? (
          <div className="xj-empty">
            体验开始前，请先阅读说明并选择是否参加。
            <button className="xj-primary" onClick={() => c.setTab("trial")}>
              查看体验说明
            </button>
          </div>
        ) : (
          <>
            {c.tab === "overview" && <Overview />}
            {c.tab === "trend" && <Trends />}
            {c.tab === "records" && (
              <>
                {c.profile?.synthetic_demo && (
                  <p className="xj-muted">以下是示例记录，可以试着修改。</p>
                )}
                {c.records.length ? (
                  c.records.map((r) => <RecordCard key={r.id} record={r} />)
                ) : (
                  <div className="xj-empty">
                    还没有感受记录。
                    <button onClick={() => c.setTab("overview")}>
                      记下此刻的感受
                    </button>
                  </div>
                )}
                {c.records.length > 0 && (
                  <p className="xj-muted">
                    显示最近 {c.records.length} 条记录（最多 100 条）。
                  </p>
                )}
              </>
            )}
            {c.tab === "actions" && <Actions />}
            {replay && (
              <>
                {c.profile?.synthetic_demo && (
                  <div className="xj-notice">
                    合成演示档案 · 所有预置历史均为虚构，不计入真实体验结果。
                  </div>
                )}
                {c.turns.length ? (
                  c.turns.map((t) => <Replay key={t.id} turn={t} />)
                ) : (
                  <div className="xj-empty">
                    完成一次对话后，这里会出现决策记录。
                  </div>
                )}
                <details className="xj-card">
                  <summary>组织者工具：记录到访与回访</summary>
                  <p className="xj-muted">
                    按实际发生情况记录；合成档案中的事件不计入真人试用。
                  </p>
                  <div className="xj-row">
                    <button
                      disabled={c.busy || !!needsConsent}
                      onClick={() =>
                        void c.mutate("/events", "POST", { name: "visit" })
                      }
                    >
                      记录本次到访
                    </button>
                    <button
                      disabled={c.busy || !!needsConsent}
                      onClick={() =>
                        void c.mutate("/events", "POST", {
                          name: "return_visit",
                        })
                      }
                    >
                      记录一次回访
                    </button>
                  </div>
                </details>
              </>
            )}
          </>
        )}
        {c.tab === "trial" && <Trial key={c.profile?.label} />}
      </main>
      <footer className="xj-panel-footer">
        {replay ? (
          <span>规则、模型提议与最终执行分别呈现。</span>
        ) : c.tab === "trial" ? (
          <span>你的选择可以随时调整。</span>
        ) : (
          <button className="xj-text-button" onClick={() => c.setTab("trial")}>
            数据与隐私
          </button>
        )}
        <button
          className="xj-text-button"
          disabled={c.loading}
          onClick={() => void c.refresh()}
        >
          刷新记录
        </button>
      </footer>
    </dialog>
  );
}
