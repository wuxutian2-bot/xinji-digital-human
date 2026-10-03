/** Restore only an ID returned for the current server-side profile. */
export function initialHistoryRequest(
  histories: { uid: string }[],
  preferred: string | null,
) {
  const selected =
    histories.find((history) => history.uid === preferred) || histories[0];
  return selected
    ? { type: "fetch-and-set-history", history_uid: selected.uid }
    : { type: "create-new-history" };
}

export function historySelectionKey(server: string, profile: string) {
  return `xj-history:${JSON.stringify([server, profile])}`;
}
