import { apiRequest, requestJson } from "./client";
import type {
  CaptureCreated,
  CompleteReviewResponse,
  Concept,
  ConceptCreateResponse,
  CreateGradingPayload,
  CreateGradingResponse,
  DueReviewResponse,
  ExplainMode,
  ExplainSourceKind,
  ExplanationAttemptResponse,
  ExplanationResponse,
  ExtractionBatch,
  GradingDetail,
  MistakeDetail,
  MistakeListResponse,
  MistakeOptions,
  QuestionType,
  SliceResult,
  TopicListResponse,
} from "./types";

export function uploadCapture(file: File): Promise<CaptureCreated> {
  const form = new FormData();
  form.append("file", file);
  return apiRequest<CaptureCreated>(
    "/api/captures",
    { method: "POST", body: form },
    60_000,
  );
}

export function sliceCapture(
  captureId: number,
  force = false,
): Promise<SliceResult> {
  const query = force ? "?force=true" : "";
  return apiRequest<SliceResult>(
    `/api/captures/${captureId}/slice${query}`,
    { method: "POST" },
    120_000,
  );
}

export function extractCapture(
  captureId: number,
  force = false,
): Promise<ExtractionBatch> {
  const query = force ? "?force=true" : "";
  return apiRequest<ExtractionBatch>(
    `/api/captures/${captureId}/extract${query}`,
    { method: "POST" },
    300_000,
  );
}

export function listExtractions(captureId: number): Promise<ExtractionBatch> {
  return apiRequest<ExtractionBatch>(`/api/captures/${captureId}/extractions`);
}

export function createGrading(
  payload: CreateGradingPayload,
): Promise<CreateGradingResponse> {
  return requestJson<CreateGradingResponse>("/api/gradings", "POST", payload, 180_000);
}

export function getGrading(gradingId: number): Promise<GradingDetail> {
  return apiRequest<GradingDetail>(`/api/gradings/${gradingId}`);
}

export interface GradingDecisionPayload {
  base_version: number;
  verdict: "correct" | "wrong";
  category_id?: string | null;
  actor?: "student" | "parent";
}

export function confirmGrading(
  gradingId: number,
  payload: GradingDecisionPayload,
): Promise<GradingDetail> {
  return requestJson<GradingDetail>(
    `/api/gradings/${gradingId}/confirm`,
    "POST",
    payload,
    60_000,
  );
}

export function appealGrading(
  gradingId: number,
  payload: GradingDecisionPayload & { reason?: string | null },
): Promise<GradingDetail> {
  return requestJson<GradingDetail>(
    `/api/gradings/${gradingId}/appeal`,
    "POST",
    payload,
    60_000,
  );
}

export interface MistakeFilters {
  status?: "active" | "voided" | "all";
  categoryId?: string | null;
  errorCause?: string | null;
  limit?: number;
  offset?: number;
}

export function listMistakes(
  filters: MistakeFilters = {},
): Promise<MistakeListResponse> {
  const params = new URLSearchParams();
  params.set("status", filters.status ?? "active");
  if (filters.categoryId) {
    params.set("category_id", filters.categoryId);
  }
  if (filters.errorCause) {
    params.set("error_cause", filters.errorCause);
  }
  params.set("limit", String(filters.limit ?? 20));
  params.set("offset", String(filters.offset ?? 0));
  return apiRequest<MistakeListResponse>(`/api/mistakes?${params.toString()}`);
}

export function getMistake(mistakeId: number): Promise<MistakeDetail> {
  return apiRequest<MistakeDetail>(`/api/mistakes/${mistakeId}`);
}

export function getMistakeOptions(): Promise<MistakeOptions> {
  return apiRequest<MistakeOptions>("/api/mistakes/options");
}

export interface MistakeLabelPayload {
  base_version: number;
  category_id: string | null;
  concept_ids: number[];
  error_cause: string | null;
  actor?: "student" | "parent";
}

export function updateMistakeLabels(
  mistakeId: number,
  payload: MistakeLabelPayload,
): Promise<MistakeDetail> {
  return requestJson<MistakeDetail>(
    `/api/mistakes/${mistakeId}/labels`,
    "POST",
    payload,
  );
}

export function searchTopics(
  q: string,
  limit = 20,
  subject?: string,
): Promise<TopicListResponse> {
  const params = new URLSearchParams();
  if (q.trim()) {
    params.set("q", q.trim());
  }
  if (subject) {
    params.set("subject", subject);
  }
  params.set("limit", String(limit));
  return apiRequest<TopicListResponse>(
    `/api/seed/topics?${params.toString()}`,
  );
}

export interface ConceptFilters {
  categoryId?: string | null;
  q?: string;
  limit?: number;
}

export function listConcepts(filters: ConceptFilters = {}): Promise<{
  items: Concept[];
}> {
  const params = new URLSearchParams();
  if (filters.categoryId) {
    params.set("category_id", filters.categoryId);
  }
  if (filters.q?.trim()) {
    params.set("q", filters.q.trim());
  }
  params.set("limit", String(filters.limit ?? 100));
  return apiRequest<{ items: Concept[] }>(`/api/concepts?${params.toString()}`);
}

export function createConcept(payload: {
  name: string;
  category_id: string;
  aliases?: string[];
  actor?: "student" | "parent";
}): Promise<ConceptCreateResponse> {
  return requestJson<ConceptCreateResponse>("/api/concepts", "POST", {
    aliases: [],
    actor: "student",
    ...payload,
  });
}

export function getDueReviews(today?: string): Promise<DueReviewResponse> {
  const params = new URLSearchParams();
  if (today) {
    params.set("today", today);
  }
  const query = params.toString();
  return apiRequest<DueReviewResponse>(
    `/api/reviews/due${query ? `?${query}` : ""}`,
  );
}

export function completeReview(
  mistakeId: number,
  payload: {
    schedule_id: number;
    correct: boolean;
    completed_on?: string;
    actor?: "student" | "parent";
  },
): Promise<CompleteReviewResponse> {
  return requestJson<CompleteReviewResponse>(
    `/api/reviews/${mistakeId}/complete`,
    "POST",
    { actor: "student", ...payload },
  );
}

export interface CreateExplanationPayload {
  source_kind: ExplainSourceKind;
  source_id: number;
  mode: ExplainMode;
  hint_level: number;
  request_id: string;
}

export function createExplanation(
  payload: CreateExplanationPayload,
): Promise<ExplanationResponse> {
  return requestJson<ExplanationResponse>(
    "/api/explanations",
    "POST",
    payload,
    180_000,
  );
}

export function recordExplanationAttempt(payload: {
  source_kind: ExplainSourceKind;
  source_id: number;
  attempt_id: string;
  mode: "guide" | "full";
  hint_level: number;
}): Promise<ExplanationAttemptResponse> {
  return requestJson<ExplanationAttemptResponse>(
    "/api/explanations/attempts",
    "POST",
    payload,
  );
}

export const QUESTION_TYPE_LABELS: Record<QuestionType, string> = {
  objective: "客观题",
  process: "过程题",
  open: "开放题",
};
