// P5-9 学段作用域三档（6=只小学 / 9=小学+初中 / 16=全部）。
// 这里只做"选项 ↔ 配置值"的纯映射；收窄发生在服务端，前端绝不按它过滤列表。
export const GRADE_SCOPE_OPTIONS = [
  { value: 6, label: "小学" },
  { value: 9, label: "初中" },
  { value: 16, label: "高中" },
] as const;

export type GradeScope = (typeof GRADE_SCOPE_OPTIONS)[number]["value"];

export function parseGradeScope(raw: string): GradeScope | null {
  const option = GRADE_SCOPE_OPTIONS.find((item) => String(item.value) === raw);
  return option ? option.value : null;
}