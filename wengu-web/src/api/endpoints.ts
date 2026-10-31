import { apiRequest, requestJson } from "./client";
import type {
  AttemptListResponse,
  BankApproveResponse,
  BankChoice,
  BankDraftListResponse,
  BankItemCreated,
  BankItemEditPayload,
  BankItemInfo,
  BankItemListResponse,
  BankItemStatusResponse,
  BankRejectResponse,
  CalendarEvent,
  CalendarEventsResponse,
  CalendarKind,
  CompleteReviewResponse,
  Concept,
  ConceptCreateResponse,
  DashboardResponse,
  DraftConfirmPayload,
  DraftConfirmResponse,
  DueReviewResponse,
  ImportResult,
  InboxInfo,
  IntakeDraftListResponse,
  LocalTopicCreatePayload,
  LocalTopicDeleteResponse,
  LocalTopicInfo,
  LocalTopicList,
  LocalTopicUpdatePayload,
  MistakeDetail,
  MistakeListResponse,
  MistakeOptions,
  PaperSubmitAnswer,
  PaperSubmitResponse,
  PaperAnswerKeyResponse,
  PomodoroResponse,
  PracticeListResponse,
  PracticeStartResponse,
  PracticeSubmitItem,
  PracticeSubmitResponse,
  QuizPaperResponse,
  QuizTopicListResponse,
  ReviewQuizResponse,
  SessionStatus,
  TimetableResponse,
  TimetableSlot,
  TopicListResponse,
} from "./types";

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

export function voidMistake(
  mistakeId: number,
  payload: { actor?: "student" | "parent"; reason?: string | null } = {},
): Promise<MistakeDetail> {
  return requestJson<MistakeDetail>(
    `/api/mistakes/${mistakeId}/void`,
    "POST",
    payload,
  );
}

export function unvoidMistake(
  mistakeId: number,
  payload: { actor?: "student" | "parent" } = {},
): Promise<MistakeDetail> {
  return requestJson<MistakeDetail>(
    `/api/mistakes/${mistakeId}/unvoid`,
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

export function recordPomodoro(payload: {
  mistake_id?: number | null;
  duration_minutes: number;
  started_at: string;
  completed_on: string;
  actor?: "student" | "parent";
}): Promise<PomodoroResponse> {
  return requestJson<PomodoroResponse>("/api/pomodoros", "POST", {
    actor: "student",
    ...payload,
  });
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

export function getPaperAnswers(filters: {
  topicId: string;
  count: number;
  seed: number;
}): Promise<PaperAnswerKeyResponse> {
  const params = new URLSearchParams();
  params.set("topic_id", filters.topicId);
  params.set("count", String(filters.count));
  params.set("seed", String(filters.seed));
  return apiRequest<PaperAnswerKeyResponse>(
    `/api/quizzes/paper/answers?${params.toString()}`,
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

export interface BankDraftFilters {
  status?: "draft" | "approved" | "rejected" | "all";
  limit?: number;
  offset?: number;
}

export function listBankDrafts(
  filters: BankDraftFilters = {},
): Promise<BankDraftListResponse> {
  const params = new URLSearchParams();
  params.set("status", filters.status ?? "draft");
  params.set("limit", String(filters.limit ?? 50));
  params.set("offset", String(filters.offset ?? 0));
  return apiRequest<BankDraftListResponse>(
    `/api/bank/drafts?${params.toString()}`,
  );
}

export interface BankApprovePayload {
  prompt?: string;
  answer?: string;
  acceptable?: string[];
  unordered?: boolean;
  verify?: string;
  topic_id?: string;
  difficulty?: string;
  source_ref?: string;
  choices?: BankChoice[];
  figure?: string | null;
  hide_choice_text?: boolean;
  percent?: boolean;
}

export function approveBankDraft(
  draftId: number,
  payload: BankApprovePayload,
): Promise<BankApproveResponse> {
  return requestJson<BankApproveResponse>(
    `/api/bank/drafts/${draftId}/approve`,
    "POST",
    payload,
  );
}

export function rejectBankDraft(draftId: number): Promise<BankRejectResponse> {
  return requestJson<BankRejectResponse>(
    `/api/bank/drafts/${draftId}/reject`,
    "POST",
    {},
  );
}

export interface BankManualItemPayload {
  topic_id: string;
  type: "choice" | "numeric" | "short" | "self";
  difficulty?: string;
  prompt: string;
  answer: string;
  acceptable?: string[];
  unordered?: boolean;
  verify?: string;
  choices?: BankChoice[];
  figure?: string | null;
  source_ref?: string;
  hide_choice_text?: boolean;
  percent?: boolean;
}

export function createBankItem(
  payload: BankManualItemPayload,
): Promise<BankItemCreated> {
  return requestJson<BankItemCreated>("/api/bank/items", "POST", {
    difficulty: "",
    acceptable: [],
    unordered: false,
    verify: "",
    choices: [],
    source_ref: "",
    hide_choice_text: false,
    percent: false,
    ...payload,
  });
}

export interface BankItemFilters {
  status?: "active" | "voided" | "all";
  topic_id?: string;
  subject?: string;
  limit?: number;
  offset?: number;
}

export function listBankItems(
  filters: BankItemFilters = {},
): Promise<BankItemListResponse> {
  const params = new URLSearchParams();
  params.set("status", filters.status ?? "active");
  params.set("limit", String(filters.limit ?? 100));
  params.set("offset", String(filters.offset ?? 0));
  if (filters.topic_id) {
    params.set("topic_id", filters.topic_id);
  }
  if (filters.subject) {
    params.set("subject", filters.subject);
  }
  return apiRequest<BankItemListResponse>(
    `/api/bank/items?${params.toString()}`,
  );
}

export function updateBankItem(
  itemId: number,
  payload: BankItemEditPayload,
): Promise<BankItemInfo> {
  return requestJson<BankItemInfo>(`/api/bank/items/${itemId}`, "PATCH", payload);
}

export function voidBankItem(
  itemId: number,
): Promise<BankItemStatusResponse> {
  return requestJson<BankItemStatusResponse>(
    `/api/bank/items/${itemId}/void`,
    "POST",
    {},
  );
}

export function unvoidBankItem(
  itemId: number,
): Promise<BankItemStatusResponse> {
  return requestJson<BankItemStatusResponse>(
    `/api/bank/items/${itemId}/unvoid`,
    "POST",
    {},
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

export function listPractice(
  filters: PracticeFilters = {},
): Promise<PracticeListResponse> {
  const params = new URLSearchParams();
  if (filters.kind) {
    params.set("kind", filters.kind);
  }
  if (filters.sourceMistakeId) {
    params.set("mistake_id", String(filters.sourceMistakeId));
  }
  params.set("limit", String(filters.limit ?? 50));
  params.set("offset", String(filters.offset ?? 0));
  return apiRequest<PracticeListResponse>(
    `/api/practice?${params.toString()}`,
  );
}

export interface PracticeStartFilters {
  mistakeId?: number;
  topicId?: string;
  count?: number;
  seed?: number;
}

export function startPractice(
  filters: PracticeStartFilters = {},
): Promise<PracticeStartResponse> {
  const payload: Record<string, number | string> = {
    count: filters.count ?? 3,
  };
  if (filters.mistakeId !== undefined) {
    payload.mistake_id = filters.mistakeId;
  }
  if (filters.topicId) {
    payload.topic_id = filters.topicId;
  }
  if (filters.seed !== undefined) {
    payload.seed = filters.seed;
  }
  return requestJson<PracticeStartResponse>(
    "/api/practice/start",
    "POST",
    payload,
  );
}

export function submitPractice(payload: {
  topic_id: string;
  seed: number;
  count: number;
  mistake_id?: number;
  items: PracticeSubmitItem[];
}): Promise<PracticeSubmitResponse> {
  return requestJson<PracticeSubmitResponse>(
    "/api/practice/submit",
    "POST",
    payload,
  );
}

export function clearPractice(): Promise<{ deleted: number }> {
  return requestJson<{ deleted: number }>("/api/practice", "DELETE");
}

export function getDashboard(
  params: { today?: string; curveDays?: number } = {},
): Promise<DashboardResponse> {
  const search = new URLSearchParams();
  if (params.today) {
    search.set("today", params.today);
  }
  if (params.curveDays) {
    search.set("curve_days", String(params.curveDays));
  }
  const query = search.toString();
  return apiRequest<DashboardResponse>(
    `/api/dashboard${query ? `?${query}` : ""}`,
  );
}

export function listLocalTopics(subject?: string): Promise<LocalTopicList> {
  const params = new URLSearchParams();
  if (subject) {
    params.set("subject", subject);
  }
  const query = params.toString();
  return apiRequest<LocalTopicList>(
    `/api/local-seed/topics${query ? `?${query}` : ""}`,
  );
}

export function createLocalTopic(
  payload: LocalTopicCreatePayload,
): Promise<LocalTopicInfo> {
  return requestJson<LocalTopicInfo>("/api/local-seed/topics", "POST", payload);
}

export function updateLocalTopic(
  topicId: string,
  payload: LocalTopicUpdatePayload,
): Promise<LocalTopicInfo> {
  return requestJson<LocalTopicInfo>(
    `/api/local-seed/topics/${encodeURIComponent(topicId)}`,
    "PATCH",
    payload,
  );
}

export function deleteLocalTopic(
  topicId: string,
): Promise<LocalTopicDeleteResponse> {
  return requestJson<LocalTopicDeleteResponse>(
    `/api/local-seed/topics/${encodeURIComponent(topicId)}`,
    "DELETE",
  );
}

export function getSessionStatus(): Promise<SessionStatus> {
  return apiRequest<SessionStatus>("/api/session/status");
}

export function setParentPin(pin: string): Promise<SessionStatus> {
  return requestJson<SessionStatus>("/api/session/pin/set", "POST", { pin });
}

export function unlockParent(pin: string): Promise<SessionStatus> {
  return requestJson<SessionStatus>("/api/session/unlock", "POST", { pin });
}

export function lockParent(): Promise<SessionStatus> {
  return requestJson<SessionStatus>("/api/session/lock", "POST", {});
}

export function getTimetable(): Promise<TimetableResponse> {
  return apiRequest<TimetableResponse>("/api/timetable");
}

export interface TimetableSlotPayload {
  weekday: number;
  period: number;
  subject: string;
  note?: string | null;
}

export function createTimetableSlot(
  payload: TimetableSlotPayload,
): Promise<TimetableSlot> {
  return requestJson<TimetableSlot>("/api/timetable/slots", "POST", payload);
}

export function deleteTimetableSlot(
  slotId: number,
): Promise<{ deleted: number }> {
  return requestJson<{ deleted: number }>(
    `/api/timetable/slots/${slotId}`,
    "DELETE",
  );
}

export function getCalendarEvents(
  filters: { from?: string; to?: string } = {},
): Promise<CalendarEventsResponse> {
  const params = new URLSearchParams();
  if (filters.from) {
    params.set("from", filters.from);
  }
  if (filters.to) {
    params.set("to", filters.to);
  }
  const query = params.toString();
  return apiRequest<CalendarEventsResponse>(
    `/api/calendar/events${query ? `?${query}` : ""}`,
  );
}

export interface CalendarEventPayload {
  date: string;
  title: string;
  kind: CalendarKind;
  subject?: string | null;
  note?: string | null;
}

export function createCalendarEvent(
  payload: CalendarEventPayload,
): Promise<CalendarEvent> {
  return requestJson<CalendarEvent>("/api/calendar/events", "POST", payload);
}

export function deleteCalendarEvent(
  eventId: number,
): Promise<{ deleted: number }> {
  return requestJson<{ deleted: number }>(
    `/api/calendar/events/${eventId}`,
    "DELETE",
  );
}
