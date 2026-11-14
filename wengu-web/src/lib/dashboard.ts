export function reviewCta(dueTotal: number): { label: string; to: string } {
  return {
    label: dueTotal === 0 ? "今天没有到期复习" : "开始今日复习",
    to: "/review",
  };
}

export function mistakesSubjectHref(subject: string): string {
  return `/mistakes?${new URLSearchParams({ subject }).toString()}`;
}