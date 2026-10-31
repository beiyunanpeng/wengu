export function toISODate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function shiftDays(value: Date, days: number): Date {
  const next = new Date(value);
  next.setDate(next.getDate() + days);
  return next;
}

/** 周一=1 … 周日=7（与 timetable_slots.weekday 一致）。 */
export function weekdayNumber(value: Date): number {
  return ((value.getDay() + 6) % 7) + 1;
}
