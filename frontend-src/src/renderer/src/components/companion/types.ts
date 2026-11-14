export type Mode = "listen" | "clarify" | "solve" | null;
export type Feedback = "helpful" | "unhelpful" | "unspecified";
export type AgentRole =
  | "safety"
  | "state"
  | "intent"
  | "feedback"
  | "history"
  | "decision_model";
export interface AgentProposal {
  role: AgentRole;
  suggested_strategy: string | null;
  evidence_codes: string[];
  confidence: "low" | "medium" | "high" | null;
}
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
  weighted_mean?: number | null;
  weighted_change?: number | null;
  interval80?: [number, number] | null;
  daily_smoothed?: Record<string, number>;
  daily_intervals?: Record<string, [number, number]>;
  alert?: "rising" | null;
  alert_started_at?: string | null;
  source_disagreement?: boolean;
  disagreement_days?: string[];
}
export interface Trend {
  version?: "daily_v2" | "daily_v3";
  as_of: string;
  settings: { timezone: string };
  previous_window: { start: string };
  current_window: { start: string };
  sources: Record<Source, { dimensions: Record<Dimension, Metric> }>;
  preferred_sources?: Record<Dimension, Source | null>;
  source_disagreement?: Record<Dimension, string[]>;
}
export interface StateRecord {
  id: string;
  state: {
    timestamp: string;
    observed_dimensions: Dimension[];
    emotion: Record<Dimension, number | null>;
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
  state_estimate?: {
    risk_level: string;
    estimator_source: string;
    observed_dimensions: Dimension[];
    emotion: Record<Dimension, number | null>;
    fallback_reason: string | null;
  };
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
    late_output_flag?: boolean;
    coordination: {
      proposed_strategy: string;
      final_strategy?: string;
      reason_codes: string[];
      proposals?: AgentProposal[];
      winner_role?: AgentRole | null;
    } | null;
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

export const roleLabels: Record<AgentRole, string> = {
  safety: "安全",
  state: "状态",
  intent: "意图",
  feedback: "反馈",
  history: "历史",
  decision_model: "决策提议",
};
export const reasonLabels: Record<string, string> = {
  safety_priority: "安全优先",
  input_safety_clear: "未触发即时风险升级",
  input_boundary_response: "采用固定边界回复",
  state_elevated: "当前困扰信号较强",
  state_unobserved: "当前维度未观测",
  state_observed: "有当前状态观测",
  observed_stress: "观测到压力",
  observed_anxiety: "观测到焦虑感",
  observed_low_mood: "观测到低落感",
  explicit_closure: "用户明确结束",
  advice_declined: "用户拒绝建议",
  listen_requested: "用户希望倾诉",
  advice_requested: "用户主动求助",
  clarification_requested: "用户希望梳理",
  intent_unspecified: "诉求未明确",
  negative_feedback: "回应没有帮助",
  feedback_unspecified: "本轮没有负面反馈提议",
  history_distress: "有效历史中有持续困扰信号",
  history_rising: "有效近期记录出现持续上升信号",
  source_disagreement: "系统估计与自报存在分歧，优先参考自报",
  history_insufficient: "历史未形成调整提议",
  decision_model_proposal: "模型给出策略提议",
  rule_proposal: "规则给出策略提议",
  model_fallback: "决策模型失败后使用规则",
  output_safety_override: "输出安全调整",
  output_safety_block_midstream: "生成中途已阻断",
  protocol_control_ignored: "忽略协议操控",
  protocol_boundary_response: "采用边界澄清回复",
};
export const intentLabels: Record<string, string> = {
  venting: "倾诉",
  seeking_clarification: "梳理问题",
  seeking_practical_help: "寻求办法",
  ending: "结束交流",
  small_talk: "闲聊",
  seeking_information: "了解信息",
  unknown: "未明确",
};
export const preferenceLabels: Record<string, string> = {
  requested: "希望建议",
  declined: "拒绝建议",
  unspecified: "未指定",
};
export function responseExplanation(turn?: Turn): string {
  if (!turn) return "这条回复的具体处理依据未记录。";
  if (turn.trace.output_safety_override)
    return "生成的内容触发了安全检查，我采用了安全调整后的回复。";
  if (turn.trace.output_policy_override)
    return "这次包含内部设置请求，我把话题引回你希望获得的支持。";
  const c = turn.trace.coordination;
  const explanations: Record<string, string> = {
    explicit_closure: "你表示想先结束交流，所以我先温和收尾。",
    advice_declined: "你表示暂时不想听建议，所以我先听你说。",
    listen_requested: "你想先倾诉，所以我先听你说。",
    advice_requested: "你希望得到具体建议，所以我陪你想一个可以开始的小步骤。",
    clarification_requested: "你希望先理清问题，所以我陪你梳理。",
    negative_feedback: "你表示前面的回应没有帮助，所以我先重新理解你的需要。",
    protocol_control_ignored:
      "我先关注你希望获得的支持，并遵循本轮的安全边界。",
  };
  const code = c?.reason_codes.find((value) => explanations[value]);
  if (code === "protocol_control_ignored") return explanations[code];
  if (
    c?.winner_role === "safety" ||
    turn.trace.source === "safety_gate" ||
    c?.reason_codes.includes("safety_priority")
  )
    return turn.final_strategy === "crisis_support"
      ? "这次的话语触发了安全支持，我先回应眼前的安全需要。"
      : "这次涉及安全边界，我先给出相应支持。";
  if (code) return explanations[code];
  if (c?.winner_role === "history")
    return turn.history_invalidated
      ? "这条回复当时参考的历史已被修改，请以当前记录为准。"
      : c.reason_codes.includes("history_rising")
        ? "近期连续记录出现了上升信号，所以我先陪你梳理近况。"
        : "可参考的近期记录提示你可能持续感到困扰，所以我先陪你理清近况。";
  if (c?.winner_role === "state")
    return "本轮的压力或情绪困扰信号较强，所以我先回应你的感受。";
  if (c?.winner_role === "decision_model")
    return "我结合本轮可用的信息，选择了当前的回应方式。";
  return "这条历史回复没有保存具体的仲裁依据。";
}
