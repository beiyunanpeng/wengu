// 打印导出查询：参数解析 + 学科/知识点/错因/日期四标签拼装 + 导出 URL 构造。
// 全部纯函数，不碰 DOM、不依赖 React/Mantine，可被 node --test 直接覆盖（本仓禁 DOM 测试栈）。
//
// 学科(subject)与知识点(category_id)是两个维度：category_id 是知识点 id、不是学科（设计文档 §19-H 第 1 条）。
// 学科标签由 subject 参数直接驱动、绝不从已加载 items 反推——否则某学科 0 道在册时标签会回落撒谎。
// 只转发 subject/category_id/error_cause：q/mastery_state 没有对应页眉标签，转发即制造新的"内容自述与实际不符"。

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export const SUBJECT_FALLBACK = "全部学科";
export const CATEGORY_FALLBACK = "全部知识点";
export const ERROR_FALLBACK = "全部错因";
export const DATE_FALLBACK = "全部日期";

export interface PrintQuery {
  subject: string | null;
  categoryId: string | null;
  errorCause: string | null;
  from: string | null;
  to: string | null;
}

export function cleanPrintDate(value: string | null): string | null {
  return value && DATE_PATTERN.test(value) ? value : null;
}

export function parsePrintQuery(params: URLSearchParams): PrintQuery {
  return {
    subject: params.get("subject"),
    categoryId: params.get("category_id"),
    errorCause: params.get("error_cause"),
    from: cleanPrintDate(params.get("from")),
    to: cleanPrintDate(params.get("to")),
  };
}

export interface PrintLabels {
  subject: string;
  category: string;
  error: string;
  date: string;
}

// resolvedCategoryName / resolvedErrorLabel 是运行时从 items / options 解析出的中文名；
// 解析不到时知识点回退 category_id 本身、错因回退 error_cause 键，与既有页眉口径一致。
export function printLabels(
  query: PrintQuery,
  resolvedCategoryName?: string | null,
  resolvedErrorLabel?: string | null,
): PrintLabels {
  return {
    subject: query.subject ?? SUBJECT_FALLBACK,
    category: query.categoryId
      ? (resolvedCategoryName ?? query.categoryId)
      : CATEGORY_FALLBACK,
    error: resolvedErrorLabel ?? query.errorCause ?? ERROR_FALLBACK,
    date:
      query.from || query.to
        ? `${query.from ?? "最早"} 至 ${query.to ?? "今天"}`
        : DATE_FALLBACK,
  };
}

// 工具栏摘要：裸标签（与既有 categoryLabel/errorLabel/dateLabel 同风格，无前缀）。
export function printToolbarSummary(labels: PrintLabels, count: number): string {
  return `${labels.subject} · ${labels.category} · ${labels.error} · ${labels.date} · ${count} 道`;
}

// 文档头 print-meta：带前缀（学科：/知识点：/错因：/日期：），与既有打印稿口径一致。
export function printDocMeta(labels: PrintLabels, groupCount: number): string {
  const base = `学科：${labels.subject} · 知识点：${labels.category} · 错因：${labels.error} · 日期：${labels.date}`;
  return groupCount > 0 ? `${base} · 共 ${groupCount} 个知识点页组` : base;
}

export interface PrintExportFilters {
  subject?: string | null;
  categoryId?: string | null;
  errorCause?: string | null;
}

// 导出按钮构造打印 URL 查询串：与 MistakesPage 既有 category_id/error_cause 同段，补 subject。
// 入参只含这三项，结构上杜绝顺手转发 q/mastery_state。中文经 URLSearchParams 百分号编码、可原样解回。
export function buildPrintMistakesQuery(filters: PrintExportFilters): string {
  const params = new URLSearchParams();
  if (filters.categoryId) {
    params.set("category_id", filters.categoryId);
  }
  if (filters.errorCause) {
    params.set("error_cause", filters.errorCause);
  }
  if (filters.subject) {
    params.set("subject", filters.subject);
  }
  return params.toString();
}