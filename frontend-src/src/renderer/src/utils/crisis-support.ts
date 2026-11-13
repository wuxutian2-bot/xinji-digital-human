import type { MessageEvent } from "@/services/websocket-service";

export interface CrisisResource {
  name: string;
  number: string;
  description: string;
  available: string;
}

export interface CrisisNotice {
  id: string | null;
  resources: CrisisResource[];
}

export interface CrisisState {
  active: CrisisNotice | null;
  seenIds: string[];
}

export const initialCrisisState: CrisisState = { active: null, seenIds: [] };

export function receiveCrisis(
  state: CrisisState,
  message: Pick<MessageEvent, "type" | "actions" | "turn_id" | "history_uid">,
  historyUid: string | null,
): CrisisState {
  if (
    !["crisis-support", "audio"].includes(message.type) ||
    message.actions?.strategy?.primary !== "crisis_support" ||
    (message.history_uid && historyUid && message.history_uid !== historyUid)
  )
    return state;
  const id = message.actions.crisis_id ?? message.turn_id ?? null;
  if (id && state.seenIds.includes(id)) return state;
  const incoming = message.actions.crisis_resources;
  const resources = (Array.isArray(incoming) ? incoming : []).filter(
    (r) =>
      r &&
      typeof r.name === "string" &&
      typeof r.description === "string" &&
      typeof r.available === "string" &&
      typeof r.number === "string" &&
      /^\+?[0-9][0-9 -]{1,24}$/.test(r.number),
  );
  return {
    active: { id, resources },
    seenIds: id ? [...state.seenIds, id] : state.seenIds,
  };
}

export function acknowledgeCrisis(
  state: CrisisState,
  notice: CrisisNotice,
): CrisisState {
  // An async acknowledgement of an earlier card must not dismiss a newer one.
  if (state.active !== notice) return state;
  return { ...state, active: null };
}
