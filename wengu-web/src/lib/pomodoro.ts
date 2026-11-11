export const MIN_FOCUS_MINUTES = 5;
export const MAX_FOCUS_MINUTES = 120;
export const DEFAULT_FOCUS_MINUTES = 25;

/**
 * 提前完成记实际分钟。服务端新端点严格 5–120，不足下限的按 5 记
 * （与旧打点端点的钳制结果一致），超过计划时长的按计划时长记。
 */
export function focusMinutes(
  plannedMinutes: number,
  remainingSeconds: number,
): number {
  const elapsed = Math.round((plannedMinutes * 60 - remainingSeconds) / 60);
  return Math.min(plannedMinutes, Math.max(MIN_FOCUS_MINUTES, elapsed));
}