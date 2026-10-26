const DEFAULT_TIMEOUT_MS = 30_000;

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function detailMessage(detail: unknown): string | null {
  if (typeof detail === "string") {
    return detail;
  }
  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    if (typeof record.message === "string") {
      return typeof record.reason === "string"
        ? `${record.message}（${record.reason}）`
        : record.message;
    }
    if (Array.isArray(record.errors)) {
      const reasons = record.errors
        .map((item) =>
          item && typeof item === "object"
            ? String((item as Record<string, unknown>).reason ?? "")
            : "",
        )
        .filter(Boolean);
      if (reasons.length > 0) {
        return `部分题目处理失败：${reasons.join("；")}`;
      }
    }
  }
  return null;
}

function messageFromBody(body: unknown, status: number): string {
  if (typeof body === "string" && body.trim()) {
    return body;
  }
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    const direct = detailMessage(record.detail);
    if (direct) {
      return direct;
    }
    if (Array.isArray(record.detail)) {
      const messages = record.detail
        .map((item) =>
          item && typeof item === "object"
            ? String((item as Record<string, unknown>).msg ?? "")
            : "",
        )
        .filter(Boolean);
      if (messages.length > 0) {
        return messages.join("；");
      }
    }
    if (typeof record.message === "string") {
      return record.message;
    }
  }
  return `请求失败（HTTP ${status}）`;
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name: unknown }).name === "AbortError"
  );
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, { ...init, signal: controller.signal });
    const text = await response.text();
    let body: unknown = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    }
    if (!response.ok) {
      throw new ApiError(
        response.status,
        messageFromBody(body, response.status),
        body,
      );
    }
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (isAbortError(error)) {
      throw new ApiError(0, "请求超时，请重试", null);
    }
    throw new ApiError(0, "无法连接后端，请确认服务已启动", null);
  } finally {
    clearTimeout(timer);
  }
}

export function requestJson<T>(
  path: string,
  method: string,
  body?: unknown,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  return apiRequest<T>(
    path,
    {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
    timeoutMs,
  );
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "操作失败，请重试";
}
