export interface ExtractionExplainContext {
  problemText: string;
  studentAnswer: string | null;
}

const PREFIX = "wengu:explain:extraction:";

function key(extractionId: number): string {
  return `${PREFIX}${extractionId}`;
}

export function saveExtractionContext(
  extractionId: number,
  context: ExtractionExplainContext,
): void {
  try {
    sessionStorage.setItem(key(extractionId), JSON.stringify(context));
  } catch {
    // 浏览器禁用存储时只影响刷新后的讲解回显，不阻断主流程
  }
}

export function readExtractionContext(
  extractionId: number,
): ExtractionExplainContext | null {
  try {
    const raw = sessionStorage.getItem(key(extractionId));
    if (!raw) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === "object" &&
      typeof (parsed as Record<string, unknown>).problemText === "string"
    ) {
      const record = parsed as Record<string, unknown>;
      return {
        problemText: record.problemText as string,
        studentAnswer:
          typeof record.studentAnswer === "string" ? record.studentAnswer : null,
      };
    }
  } catch {
    return null;
  }
  return null;
}
