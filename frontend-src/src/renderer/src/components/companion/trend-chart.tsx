import { dimensions, sources } from "./types";
import type { Dimension, Source, Trend } from "./types";
import {
  calendarDays,
  dailyValues,
  intervalBands,
} from "@/utils/companion-trend";

const colors: Record<Source, string> = {
  system_estimate: "#82918b",
  user_report: "#236d59",
  user_correction: "#bd7941",
};

export function TrendChart({
  trend,
  dimension,
}: {
  trend: Trend;
  dimension: Dimension;
}) {
  const days = calendarDays(
    trend.previous_window.start,
    trend.settings.timezone,
  );
  const v3 = trend.version === "daily_v3";
  return (
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
      {(Object.keys(sources) as Source[]).map((source) => {
        const metric = trend.sources[source].dimensions[dimension];
        const raw = dailyValues(
          days,
          metric.previous_daily_means,
          metric.daily_means,
        );
        const smooth = v3
          ? dailyValues(days, {}, metric.daily_smoothed || {})
          : raw;
        const bands = v3
          ? intervalBands(days, metric.daily_intervals || {})
          : [];
        const alertIndex =
          v3 && metric.alert === "rising"
            ? days.indexOf(metric.alert_started_at || "")
            : -1;
        return (
          <g key={source}>
            {bands.map((run, index) =>
              run.length > 1 ? (
                <polygon
                  key={index}
                  aria-label={`${sources[source]}80%重采样区间`}
                  points={[
                    ...run.map(
                      (p) => `${40 + p.index * 46},${145 - p.upper * 120}`,
                    ),
                    ...[...run]
                      .reverse()
                      .map(
                        (p) => `${40 + p.index * 46},${145 - p.lower * 120}`,
                      ),
                  ].join(" ")}
                  fill={colors[source]}
                  fillOpacity=".14"
                >
                  <title>{sources[source]} 80%重采样区间</title>
                </polygon>
              ) : (
                <line
                  key={index}
                  x1={40 + run[0].index * 46}
                  x2={40 + run[0].index * 46}
                  y1={145 - run[0].upper * 120}
                  y2={145 - run[0].lower * 120}
                  stroke={colors[source]}
                  strokeWidth="4"
                  opacity=".3"
                >
                  <title>{sources[source]} 单日位置的重采样区间</title>
                </line>
              ),
            )}
            {smooth.map((value, i) =>
              value !== null && i > 0 && smooth[i - 1] !== null ? (
                <line
                  key={days[i]}
                  x1={40 + (i - 1) * 46}
                  y1={145 - smooth[i - 1]! * 120}
                  x2={40 + i * 46}
                  y2={145 - value * 120}
                  stroke={colors[source]}
                  strokeWidth="2"
                />
              ) : null,
            )}
            {raw.map((value, i) =>
              value === null ? null : (
                <circle
                  key={days[i]}
                  cx={40 + i * 46}
                  cy={145 - value * 120}
                  r="4"
                  fill={colors[source]}
                >
                  <title>
                    {days[i]} {sources[source]}{" "}
                    {Number((value * 10).toFixed(2))}/10
                  </title>
                </circle>
              ),
            )}
            {alertIndex >= 0 && (
              <g aria-label={`${sources[source]}连续上升信号`}>
                <line
                  x1={40 + alertIndex * 46}
                  x2={40 + alertIndex * 46}
                  y1="17"
                  y2="150"
                  stroke={colors[source]}
                  strokeDasharray="3 4"
                />
                <text x={35 + alertIndex * 46} y="13" fill={colors[source]}>
                  ↑
                </text>
                <title>
                  {sources[source]} 连续上升信号起点 {metric.alert_started_at}
                </title>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}

export function TrendSignals({
  trend,
  dimension,
}: {
  trend: Trend;
  dimension: Dimension;
}) {
  if (trend.version !== "daily_v3") return null;
  const conflicts = trend.source_disagreement?.[dimension] || [];
  const selected = trend.preferred_sources?.[dimension];
  return (
    <div className="xj-trend-signals">
      <p className="xj-muted">
        圆点为日记录，线为按日平滑值，半透明带为80%重采样区间。缺失日期留空，少于3个观测日时不绘制区间。
      </p>
      {conflicts.length > 0 && (
        <p className="xj-notice" role="status">
          本周有{conflicts.length}
          天的系统估计与你的记录相差超过3分（满分10分），本维度优先参考你的自报。
          {!trend.sources.user_report.dimensions[dimension]
            .eligible_for_decision &&
            "自报天数不足或记录已过期，暂不据此推断趋势。"}
        </p>
      )}
      {(Object.keys(sources) as Source[]).map((source) => {
        const metric = trend.sources[source].dimensions[dimension];
        return metric.alert === "rising" ? (
          <p key={source} className="xj-notice" role="status">
            {sources[source]}的{dimensions[dimension]}
            记录出现连续上升信号，起点为{metric.alert_started_at}。
            {selected !== source && "本次历史决策优先参考其他来源。"}
          </p>
        ) : null;
      })}
    </div>
  );
}
