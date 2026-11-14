/** Consecutive calendar days; a missing value stays null, including between points. */
export function calendarDays(
  start: string,
  timeZone: string,
  count = 14,
): string[] {
  const date = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(start));
  const base = Date.parse(`${date}T12:00:00Z`);
  return Array.from({ length: count }, (_, i) =>
    new Date(base + i * 86400000).toISOString().slice(0, 10),
  );
}
export function dailyValues(
  days: string[],
  previous: Record<string, number>,
  current: Record<string, number>,
) {
  const values = { ...previous, ...current };
  return days.map((day) =>
    Object.prototype.hasOwnProperty.call(values, day) ? values[day] : null,
  );
}

export function intervalBands(
  days: string[],
  intervals: Record<string, [number, number]>,
) {
  const runs: { index: number; lower: number; upper: number }[][] = [];
  let run: { index: number; lower: number; upper: number }[] = [];
  days.forEach((day, index) => {
    const bounds = intervals[day];
    if (bounds) run.push({ index, lower: bounds[0], upper: bounds[1] });
    else if (run.length) {
      runs.push(run);
      run = [];
    }
  });
  if (run.length) runs.push(run);
  return runs;
}
