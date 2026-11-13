import { useEffect, useRef } from "react";
import { useCompanion } from "./companion-context";
import type { CrisisNotice } from "@/utils/crisis-support";

export function CrisisCard({
  notice,
  onAcknowledge,
}: {
  notice: CrisisNotice | null;
  onAcknowledge: () => void;
}) {
  if (!notice) return null;
  return (
    <section className="xj-crisis-card">
      <p className="xj-crisis-eyebrow">先照顾好此刻的安全</p>
      <h2 id="crisis-title" tabIndex={-1}>
        你不需要独自面对
      </h2>
      <p id="crisis-description">
        如果你已经受伤，或可能马上伤害自己或他人，请立即联系当地急救服务。
        尽快让一位信任的人来到你身边，远离可能造成伤害的物品，去有人陪伴的安全地点。
      </p>
      {notice.resources.length > 0 && (
        <>
          <p className="xj-muted">
            以下渠道适用于中国大陆；其他地区请联系当地急救或心理援助服务。
          </p>
          <ul className="xj-crisis-resources">
            {notice.resources.map((resource) => (
              <li key={resource.number}>
                <div>
                  <strong>{resource.name}</strong>
                  <p>{resource.description}</p>
                  <span className="xj-muted">{resource.available}</span>
                </div>
                <a href={`tel:${resource.number}`}>{resource.number}</a>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="xj-muted">
        这里无法代替紧急援助。请先联系能来到你身边的人。
      </p>
      <button type="button" className="xj-primary" onClick={onAcknowledge}>
        我现在安全
      </button>
    </section>
  );
}

export function CrisisSupport() {
  const { crisis, acknowledgeCrisis } = useCompanion();
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (crisis && !dialog.current?.open) {
      dialog.current?.showModal();
      // Read the guidance first; do not initially focus a dial/confirm action.
      dialog.current?.querySelector("h2")?.focus();
    }
    if (!crisis && dialog.current?.open) dialog.current?.close();
  }, [crisis]);
  return (
    <dialog
      ref={dialog}
      className="xj xj-crisis-dialog"
      aria-labelledby="crisis-title"
      aria-describedby="crisis-description"
      onCancel={(event) => event.preventDefault()}
    >
      <CrisisCard notice={crisis} onAcknowledge={acknowledgeCrisis} />
    </dialog>
  );
}
