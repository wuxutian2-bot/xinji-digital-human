import { useRef, useState } from "react";
import { useAiState } from "@/context/ai-state-context";
import { useCompanion } from "./companion-context";
import type { Feedback, Mode } from "./types";

export function CompanionEntry() {
  const c = useCompanion();
  const [dismissed, setDismissed] = useState(false);
  const openedAt = useRef(Date.now());
  const pending = c.actions.find((a) => a.status === "pending");
  const revisit = pending && Date.parse(pending.created_at) < openedAt.current;
  return (
    <div className="xj xj-entry">
      <button
        className="xj-entry-main"
        aria-label="打开我的心迹"
        onClick={() => c.show()}
      >
        <span className="xj-entry-icon" aria-hidden="true">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <path d="M5 4h12a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2V4Z M5 16h14 M9 4v12" />
            <path d="M12 8h4 M12 11h3" />
          </svg>
        </span>
        <span className="xj-entry-copy">
          <strong>我的心迹</strong>
          <small>记下感受，看看最近的自己</small>
        </span>
        <span className="xj-entry-arrow" aria-hidden="true">
          ›
        </span>
      </button>
      {c.profile?.trial_mode && !c.profile.consent?.accepted && (
        <button className="xj-reminder" onClick={() => c.show("trial")}>
          开始前，先了解本次体验
        </button>
      )}
      {revisit && !dismissed && (
        <div className="xj-reminder">
          <button
            onClick={() => {
              c.show("actions");
              setDismissed(true);
            }}
          >
            上次的小步骤，想回顾一下吗？
          </button>
          <button aria-label="稍后回顾" onClick={() => setDismissed(true)}>
            ×
          </button>
        </div>
      )}
    </div>
  );
}
export function SupportChoices() {
  const { mode, selectMode, connected, profile } = useCompanion();
  const { aiState } = useAiState();
  const disabled =
    !connected ||
    !profile ||
    aiState === "thinking-speaking" ||
    aiState === "listening" ||
    (profile?.trial_mode && !profile.consent?.accepted);
  return (
    <div className="xj xj-support" aria-label="你希望我怎么陪你">
      <span>你希望我怎么陪你</span>
      {(
        [
          ["listen", "先听我说"],
          ["clarify", "帮我梳理"],
          ["solve", "一起想办法"],
        ] as [Mode, string][]
      ).map(([key, label]) => (
        <button
          key={key}
          disabled={Boolean(disabled)}
          aria-pressed={mode === key}
          onClick={() => selectMode(mode === key ? null : key)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
export function ReplyControls({
  turnId,
  answer,
}: {
  turnId?: string;
  answer: string;
}) {
  const c = useCompanion();
  const turn = c.turns.find((t) => t.id === turnId);
  const [text, setText] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  if (!turn || !turnId) return null;
  return (
    <div className="xj xj-reply-controls" onClick={(e) => e.stopPropagation()}>
      {(["helpful", "unhelpful"] as Feedback[]).map((value) => (
        <button
          key={value}
          disabled={c.busy}
          aria-pressed={turn.feedback === value}
          onClick={() =>
            void c.mutate(`/turns/${turnId}/feedback`, "PUT", {
              value: turn.feedback === value ? "unspecified" : value,
            })
          }
        >
          {value === "helpful" ? "有帮助" : "没帮助"}
        </button>
      ))}
      {turn.final_strategy === "collaborative_problem_solving" && (
        <button
          onClick={() => {
            setText("");
            dialog.current?.showModal();
          }}
        >
          保存一个小步骤
        </button>
      )}
      <dialog
        className="xj xj-action-dialog"
        ref={dialog}
        aria-labelledby={`action-${turnId}`}
      >
        <h2 id={`action-${turnId}`}>只选你愿意尝试的一小步</h2>
        <p className="xj-muted">
          写下一条适合你的普通生活或学习行动。确认后才会保存。
        </p>
        <details>
          <summary>回看这次回答</summary>
          <p>{answer}</p>
        </details>
        <label>
          我愿意尝试
          <textarea
            autoFocus
            value={text}
            maxLength={300}
            onChange={(e) => setText(e.target.value)}
            placeholder="例如：把明天的复习内容分成两项"
          />
        </label>
        {c.error && (
          <p role="alert" className="xj-danger">
            {c.error}
          </p>
        )}
        <div className="xj-row">
          <button
            className="xj-primary"
            disabled={c.busy || !text.trim()}
            onClick={async () => {
              if (
                await c.mutate("/actions", "POST", {
                  text: text.trim(),
                  turn_id: turnId,
                })
              )
                dialog.current?.close();
            }}
          >
            确认保存
          </button>
          <button onClick={() => dialog.current?.close()}>暂时不用</button>
        </div>
      </dialog>
    </div>
  );
}
