import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useChatHistory } from "@/context/chat-history-context";
import { wsService } from "@/services/websocket-service";
import {
  acknowledgeCrisis,
  initialCrisisState,
  receiveCrisis,
} from "@/utils/crisis-support";
import type { CrisisNotice } from "@/utils/crisis-support";

const Context = createContext<{
  crisis: CrisisNotice | null;
  dismiss: (notice: CrisisNotice) => void;
} | null>(null);

export function useCrisis() {
  const value = useContext(Context);
  if (!value) throw new Error("CrisisProvider missing");
  return value;
}

export function CrisisProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState(initialCrisisState);
  const { currentHistoryUid } = useChatHistory();
  const history = useRef(currentHistoryUid);
  history.current = currentHistoryUid;
  useEffect(() => {
    const subscription = wsService.onMessage((message) => {
      setState((previous) => receiveCrisis(previous, message, history.current));
    });
    return () => subscription.unsubscribe();
  }, []);
  return (
    <Context.Provider
      value={{
        crisis: state.active,
        dismiss: (notice) =>
          setState((previous) => acknowledgeCrisis(previous, notice)),
      }}
    >
      {children}
    </Context.Provider>
  );
}
