import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { useWebSocket } from "@/context/websocket-context";
import { useChatHistory } from "@/context/chat-history-context";
import { wsService } from "@/services/websocket-service";
import type {
  ActionItem,
  Mode,
  Profile,
  StateRecord,
  Trend,
  Turn,
} from "./types";
import "./companion.css";
import { toaster } from "@/components/ui/toaster";

type Tab = "overview" | "trend" | "records" | "actions" | "replay" | "trial";
interface CompanionContextValue {
  profile: Profile | null;
  records: StateRecord[];
  trend: Trend | null;
  review: string[];
  turns: Turn[];
  actions: ActionItem[];
  mode: Mode;
  tab: Tab;
  open: boolean;
  demoView: boolean;
  busy: boolean;
  error: string;
  loading: boolean;
  connected: boolean;
  show: (tab?: Tab) => void;
  close: () => void;
  setTab: (tab: Tab) => void;
  refresh: () => Promise<void>;
  selectMode: (mode: Mode) => void;
  mutate: (path: string, method: string, body?: unknown) => Promise<boolean>;
}
const Context = createContext<CompanionContextValue | null>(null);
export function useCompanion() {
  const value = useContext(Context);
  if (!value) throw new Error("CompanionProvider missing");
  return value;
}
export function CompanionProvider({ children }: { children: React.ReactNode }) {
  const { baseUrl, sendMessage } = useWebSocket();
  const { currentHistoryUid } = useChatHistory();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [records, setRecords] = useState<StateRecord[]>([]);
  const [trend, setTrend] = useState<Trend | null>(null);
  const [review, setReview] = useState<string[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [mode, setMode] = useState<Mode>(null);
  const [demoView] = useState(
    () => new URLSearchParams(window.location.search).get("view") === "demo",
  );
  const [tab, setTab] = useState<Tab>(demoView ? "replay" : "overview");
  const [open, setOpen] = useState(demoView);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [connected, setConnected] = useState(
    wsService.getCurrentState() === "OPEN",
  );
  const generation = useRef(0);
  const introducedProfile = useRef<string | null>(null);
  const historyRef = useRef(currentHistoryUid);
  historyRef.current = currentHistoryUid;
  const api = useCallback(
    async <T,>(path: string, method = "GET", body?: unknown): Promise<T> => {
      const response = await fetch(`${baseUrl}/api/companion${path}`, {
        method,
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(
          typeof detail?.detail === "string"
            ? detail.detail
            : "操作未完成，请检查输入或服务连接。",
        );
      }
      return response.json();
    },
    [baseUrl],
  );
  const refresh = useCallback(async () => {
    const revision = ++generation.current;
    setLoading(true);
    try {
      const [p, r, t, ts, a] = await Promise.all([
        api<Profile>("/profile"),
        api<StateRecord[]>("/states"),
        api<{ trend: Trend; review: string[] }>("/trend"),
        api<Turn[]>("/turns"),
        api<ActionItem[]>("/actions"),
      ]);
      if (revision !== generation.current) return;
      setProfile(p);
      setRecords(r);
      setTrend(t.trend);
      setReview(t.review);
      setTurns(ts);
      setActions(a);
      setError("");
    } catch (e) {
      if (revision === generation.current)
        setError(e instanceof Error ? e.message : "连接失败");
    } finally {
      if (revision === generation.current) setLoading(false);
    }
  }, [api]);
  useEffect(() => {
    setProfile(null);
    setRecords([]);
    setTurns([]);
    setActions([]);
    setTrend(null);
    void refresh();
    return () => {
      generation.current += 1;
    };
  }, [refresh]);
  useEffect(() => {
    setMode(null);
  }, [currentHistoryUid]);
  useEffect(() => {
    if (
      !demoView &&
      profile?.trial_mode &&
      !profile.consent?.accepted &&
      introducedProfile.current !== profile.label
    ) {
      introducedProfile.current = profile.label;
      setTab("trial");
      setOpen(true);
    }
  }, [profile, demoView]);
  useEffect(() => {
    const messages = wsService.onMessage((message) => {
      if (
        message.type === "companion-mode" &&
        message.history_uid === historyRef.current
      )
        setMode(message.mode ?? null);
      if (message.type === "companion-turn" && message.turn) {
        const turn = message.turn;
        setTurns((prev) => [turn, ...prev.filter((t) => t.id !== turn.id)]);
        if (turn.scope.endsWith(`:${historyRef.current}`))
          setMode(turn.support_mode);
      }
      if (
        [
          "companion-refresh",
          "new-history-created",
          "history-data",
          "config-switched",
        ].includes(message.type)
      ) {
        if (message.type !== "companion-refresh") setMode(null);
        void refresh();
      }
    });
    const connection = wsService.onStateChange((state) => {
      setConnected(state === "OPEN");
      if (state === "OPEN") void refresh();
      else {
        setMode(null);
        generation.current += 1;
        setProfile(null);
        setTurns([]);
        setRecords([]);
        setTrend(null);
        setActions([]);
      }
    });
    return () => {
      messages.unsubscribe();
      connection.unsubscribe();
    };
  }, [refresh]);
  const mutate = useCallback(
    async (path: string, method: string, body?: unknown) => {
      setBusy(true);
      setError("");
      try {
        await api(path, method, body);
        await refresh();
        return true;
      } catch (e) {
        const message = e instanceof Error ? e.message : "操作失败";
        setError(message);
        toaster.create({ title: message, type: "error", duration: 5000 });
        return false;
      } finally {
        setBusy(false);
      }
    },
    [api, refresh],
  );
  const selectMode = (next: Mode) =>
    sendMessage({
      type: "companion-mode",
      mode: next,
      history_uid: currentHistoryUid,
    });
  const show = (next: Tab = "overview") => {
    setTab(
      profile?.trial_mode && !profile.consent?.accepted && next !== "replay"
        ? "trial"
        : next,
    );
    setOpen(true);
    void refresh();
  };
  return (
    <Context.Provider
      value={{
        profile,
        records,
        trend,
        review,
        turns,
        actions,
        mode,
        tab,
        open,
        demoView,
        busy,
        error,
        loading,
        connected,
        show,
        close: () => setOpen(false),
        setTab,
        refresh,
        selectMode,
        mutate,
      }}
    >
      {children}
    </Context.Provider>
  );
}
