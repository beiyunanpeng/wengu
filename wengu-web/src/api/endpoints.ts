import { apiRequest, requestJson } from "./client";
import type {
  AttemptListResponse,
  CaptureCreated,
  CompleteReviewResponse,
  Concept,
  ConceptCreateResponse,
  CreateGradingPayload,
  CreateGradingResponse,
  DraftConfirmPayload,
  DraftConfirmResponse,
  DueReviewResponse,
  ExplainMode,
  ExplainSourceKind,
  ExplanationAttemptResponse,
  ExplanationResponse,
  ExtractionBatch,
  GradingDetail,
  ImportResult,
  InboxInfo,
  IntakeDraftListResponse,
  MistakeDetail,
  MistakeListResponse,
  MistakeOptions,
  PaperSubmitAnswer,
  PaperSubmitResponse,
  PracticeListResponse,
  QuestionType,
  QuizPaperResponse,
  QuizTopicListResponse,
  ReviewQuizResponse,
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
    { actor: "student", source: "student_self", ...payload },
  );
}

export function submitReviewQuiz(
  mistakeId: number,
  payload: {
    schedule_id: number;
    question_id?: string | null;
    answer?: string | null;
    correct?: boolean | null;
    completed_on?: string;
    actor?: "student" | "parent";
  },
): Promise<ReviewQuizResponse> {
  return requestJson<ReviewQuizResponse>(
    `/api/reviews/${mistakeId}/quiz`,
    "POST",
    { actor: "student", ...payload },
  );
}

export function getInboxInfo(): Promise<InboxInfo> {
  return apiRequest<InboxInfo>("/api/imports/inbox");
}

export interface TranscribeItem {
  subject?: string;
  problem_text: string;
  student_answer?: string;
  standard_answer?: string;
  source_ref?: string;
  captured_at?: string;
}

export function importTranscribe(
  items: TranscribeItem[],
): Promise<ImportResult> {
  return requestJson<ImportResult>(
    "/api/imports",
    "POST",
    { channel: "agent_transcribe_v1", items },
    60_000,
  );
}

export function listQuizTopics(filters: {
  subject?: string;
  q?: string;
  limit?: number;
}): Promise<QuizTopicListResponse> {
  const params = new URLSearchParams();
  if (filters.subject) {
    params.set("subject", filters.subject);
  }
  if (filters.q?.trim()) {
    params.set("q", filters.q.trim());
  }
  params.set("limit", String(filters.limit ?? 100));
  return apiRequest<QuizTopicListResponse>(
    `/api/quizzes/topics?${params.toString()}`,
  );
}

export function getQuizPaper(filters: {
  topicId: string;
  count: number;
  seed?: number;
}): Promise<QuizPaperResponse> {
  const params = new URLSearchParams();
  params.set("topic_id", filters.topicId);
  params.set("count", String(filters.count));
  if (filters.seed !== undefined) {
    params.set("seed", String(filters.seed));
  }
  return apiRequest<QuizPaperResponse>(
    `/api/quizzes/paper?${params.toString()}`,
  );
}

export function submitQuizPaper(payload: {
  topic_id: string;
  seed: number;
  count: number;
  answers: PaperSubmitAnswer[];
  completed_on?: string;
  actor?: "student" | "parent";
}): Promise<PaperSubmitResponse> {
  return requestJson<PaperSubmitResponse>("/api/quizzes/paper/submit", "POST", {
    actor: "student",
    ...payload,
  });
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

export interface IntakeDraftFilters {
  status?: "draft" | "promoted" | "all";
  limit?: number;
  offset?: number;
}

export function listIntakeDrafts(
  filters: IntakeDraftFilters = {},
): Promise<IntakeDraftListResponse> {
  const params = new URLSearchParams();
  params.set("status", filters.status ?? "draft");
  params.set("limit", String(filters.limit ?? 50));
  params.set("offset", String(filters.offset ?? 0));
  return apiRequest<IntakeDraftListResponse>(
    `/api/imports/drafts?${params.toString()}`,
  );
}

export function confirmIntakeDraft(
  draftId: number,
  payload: DraftConfirmPayload,
): Promise<DraftConfirmResponse> {
  return requestJson<DraftConfirmResponse>(
    `/api/imports/drafts/${draftId}/confirm`,
    "POST",
    { actor: "student", question_type: "objective", ...payload },
    60_000,
  );
}

export interface AttemptFilters {
  source?: "manual" | "student_self" | "system_quiz";
  mistakeId?: number | null;
  limit?: number;
  offset?: number;
}

export function listAttempts(
  filters: AttemptFilters = {},
): Promise<AttemptListResponse> {
  const params = new URLSearchParams();
  if (filters.source) {
    params.set("source", filters.source);
  }
  if (filters.mistakeId) {
    params.set("mistake_id", String(filters.mistakeId));
  }
  params.set("limit", String(filters.limit ?? 50));
  params.set("offset", String(filters.offset ?? 0));
  return apiRequest<AttemptListResponse>(`/api/attempts?${params.toString()}`);
}

export interface PracticeFilters {
  kind?: "variant" | "extra";
  sourceMistakeId?: number;
  limit?: number;
  offset?: number;
}

export function listPracticeRecords(
  filters: PracticeFilters = {},
): Promise<PracticeListResponse> {
  const params = new URLSearchParams();
  if (filters.kind) {
    params.set("kind", filters.kind);
  }
  if (filters.sourceMistakeId) {
    params.set("source_mistake_id", String(filters.sourceMistakeId));
  }
  params.set("limit", String(filters.limit ?? 50));
  params.set("offset", String(filters.offset ?? 0));
  return apiRequest<PracticeListResponse>(
    `/api/practice-records?${params.toString()}`,
  );
}
