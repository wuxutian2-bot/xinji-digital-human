export type Mode = "listen" | "clarify" | "solve" | null;
export type Feedback = "helpful" | "unhelpful" | "unspecified";
export const dimensions = {
  stress: "压力",
  anxiety: "焦虑感",
  low_mood: "低落感",
};
export type Dimension = keyof typeof dimensions;
export const sources = {
  system_estimate: "系统估计",
  user_report: "我的记录",
  user_correction: "我的修改",
};
export type Source = keyof typeof sources;
export interface Metric {
  mean: number | null;
  change: number | null;
  observed_days: number;
  previous_observed_days: number;
  coverage: number;
  stale: boolean;
  eligible_for_decision: boolean;
  daily_means: Record<string, number>;
  previous_daily_means: Record<string, number>;
}
export interface Trend {
  as_of: string;
  settings: { timezone: string };
  previous_window: { start: string };
  current_window: { start: string };
  sources: Record<Source, { dimensions: Record<Dimension, Metric> }>;
}
export interface StateRecord {
  id: string;
  state: {
    timestamp: string;
    observed_dimensions: Dimension[];
    emotion: Record<Dimension, number>;
    estimator_source: string;
    dimension_sources?: Partial<Record<Dimension, string>>;
  };
}
export interface Turn {
  id: string;
  timestamp: string;
  scope: string;
  synthetic: boolean;
  final_strategy: string;
  support_mode: Mode;
  feedback: Feedback;
  history_invalidated: boolean;
  history_context: {
    sources: Record<
      string,
      Record<
        string,
        { mean: number | null; observed_days: number; status: string }
      >
    >;
  } | null;
  intent: {
    primary: string;
    advice_preference: string;
    feedback: string;
    source: string;
  };
  trace: {
    source: string;
    fallback_reason: string | null;
    output_safety_override: boolean;
    output_policy_override: boolean;
    coordination: { proposed_strategy: string; reason_codes: string[] } | null;
  };
  playback: string;
  generation: string;
  sent_segments: {
    id: number;
    sent: boolean;
    has_audio: boolean;
    playback: string;
    tts_error: boolean;
    actions: {
      motion?: string;
      gaze?: string;
      voice_applied?: { speed: number; fallback: string[] };
    } | null;
  }[];
}
export interface ActionItem {
  id: string;
  text: string;
  turn_id: string;
  created_at: string;
  status: "pending" | "completed" | "skipped";
  feedback: Feedback;
}
export interface Profile {
  label: string;
  trial_mode: boolean;
  synthetic_demo: boolean;
  consent: { accepted: boolean; retain_conversation: boolean } | null;
}
export const strategyLabels: Record<string, string> = {
  supportive_listening: "支持性倾听",
  reflect_and_clarify: "反映与澄清",
  collaborative_problem_solving: "一起解决问题",
  validate_and_ground: "确认感受与稳定支持",
  close_supportively: "温和结束",
  crisis_support: "安全支持",
  ensure_immediate_safety: "优先确保安全",
};
