export interface ConceptInfo {
  id: number;
  name: string;
  category_id: string;
}

export interface MistakeLabels {
  confirmed: boolean;
  category_id: string | null;
  category_name: string | null;
  concepts: ConceptInfo[];
  error_cause: string | null;
  error_cause_label: string | null;
  confirmed_by: string | null;
}

export interface MistakeSuggestion {
  category_id: string | null;
  category_name: string | null;
  concepts: ConceptInfo[];
  error_cause: string | null;
  error_cause_label: string | null;
}

export interface MistakeDetail {
  id: number;
  status: string;
  source_grading_id: number;
  current_version: number;
  problem_text: string | null;
  student_answer: string | null;
  standard_answer: string | null;
  is_correct: boolean | null;
  labels: MistakeLabels;
  suggestion: MistakeSuggestion;
  created_at: string;
  updated_at: string;
}

export interface MistakeListResponse {
  items: MistakeDetail[];
  total: number;
  limit: number;
  offset: number;
}

export interface ErrorCauseOption {
  id: string;
  label: string;
}

export interface MistakeOptions {
  error_causes: ErrorCauseOption[];
}

export interface TopicInfo {
  id: string;
  name: string;
  subject: string;
  domain: string | null;
  grade: string | null;
  semester: string | null;
  chapter: string | null;
  unaudited: boolean;
  blind_verified: boolean;
}

export interface TopicListResponse {
  items: TopicInfo[];
  total: number;
  limit: number;
  offset: number;
}

export interface Concept {
  id: number;
  name: string;
  category_id: string;
  source: string;
  status: string;
  merged_into_id: number | null;
  aliases: string[];
}

export interface ConceptCreateResponse extends Concept {
  reused: boolean;
}

export interface DueReviewItem {
  schedule_id: number;
  mistake_id: number;
  due_date: string;
  rung: number;
  base_interval_days: number;
  problem_text: string | null;
  primary_topic_id: string | null;
  task: "quiz" | "self_eval" | "redo";
  coverage: "ok" | "thin" | "gap";
  bank_gap: boolean;
  coverage_hint: string | null;
  quiz: QuizQuestionView | null;
}

export type ReviewTask = DueReviewItem["task"];

export interface QuizChoiceView {
  key: string;
  text: string;
  figure: string | null;
}

export interface QuizQuality {
  unaudited: boolean;
  blind_verified: boolean;
  verify_status: "verified" | "unverifiable";
  verify_reason: string | null;
}

export interface QuizQuestionView {
  question_id: string;
  topic_id: string;
  subject: string;
  type: string;
  difficulty: string | null;
  prompt: string;
  choices: QuizChoiceView[];
  figure: string | null;
  mode: "system" | "self_eval";
  seed: number;
  pool_size: number;
  quality: QuizQuality;
}

export interface DueReviewResponse {
  items: DueReviewItem[];
  due_total: number;
  returned: number;
  today_completed: number;
  daily_limit: number;
  exam_today: boolean;
  today: string;
  limit: number;
}

export interface ReviewStateInfo {
  rung: number;
  times_wrong: number;
  trailing_correct: number;
}

export interface ScheduleInfo {
  id: number;
  due_date: string;
  rung: number;
  base_interval_days: number;
}

export interface CompleteReviewResponse {
  mistake_id: number;
  schedule_id: number;
  attempt_id: number;
  graduated: boolean;
  correct: boolean;
  mastery: number;
  interval_days: number | null;
  due_on: string | null;
  state: ReviewStateInfo;
  next_schedule: ScheduleInfo | null;
  source: string;
}

export interface ReviewQuizResponse {
  completion: CompleteReviewResponse;
  question: QuizQuestionView;
  mode: "system" | "self_eval";
  verdict: "correct" | "wrong";
}

export interface QuizTopicInfo {
  topic_id: string;
  name: string;
  subject: string;
  domain: string | null;
  grade: string | null;
  semester: string | null;
  total: number;
  answerable: number;
}

export interface QuizTopicListResponse {
  items: QuizTopicInfo[];
  total: number;
  limit: number;
  offset: number;
}

export interface QuizPaperResponse {
  topic_id: string;
  seed: number;
  count: number;
  coverage: "ok" | "thin" | "gap";
  bank_gap: boolean;
  shortfall: boolean;
  answerable_total: number;
  pool_total: number;
  items: QuizQuestionView[];
}

export interface PaperSubmitAnswer {
  question_id: string;
  answer?: string | null;
  correct?: boolean | null;
}

export interface PaperAnswerKeyItem {
  question_id: string;
  mode: "system" | "self_eval";
  answer: string;
  acceptable_answers: string[];
}

export interface PaperAnswerKeyResponse {
  topic_id: string;
  seed: number;
  count: number;
  items: PaperAnswerKeyItem[];
}

export interface PaperAnswerInfo {
  question_id: string;
  mode: "system" | "self_eval";
  status: "correct" | "wrong" | "uncertain" | "skipped";
  attempt_id: number | null;
  replayed: boolean;
}

export interface PaperSubmitResponse {
  topic_id: string;
  seed: number;
  completed_on: string;
  items: PaperAnswerInfo[];
  correct: number;
  wrong: number;
}

export interface InboxInfo {
  path: string;
  channels: string[];
  max_items: number;
  max_body_bytes: number;
}

export interface ImportItemError {
  index: number;
  field: string;
  reason: string;
}

export interface ImportResult {
  batch_id: number;
  status: string;
  duplicate: boolean;
  draft_count: number;
  accepted_count: number;
  dropped_unknown_fields: number;
  errors: ImportItemError[];
}

export interface IntakeSuggestion {
  topic_id: string | null;
  topic_name: string | null;
  error_cause: string | null;
  error_cause_label: string | null;
  source: string | null;
}

export interface IntakeDraft {
  id: number;
  batch_id: number;
  filename: string | null;
  seq: number;
  status: string;
  has_placeholder: boolean;
  is_incomplete: boolean;
  created_at: string;
  subject: string;
  problem_text: string;
  student_answer: string;
  standard_answer: string;
  source_ref: string;
  captured_at: string;
  suggestion: IntakeSuggestion;
  grading_id: number | null;
  mistake_id: number | null;
}

export interface IntakeDraftListResponse {
  items: IntakeDraft[];
  total: number;
  limit: number;
  offset: number;
}

export interface DraftConfirmPayload {
  primary_topic_id?: string | null;
  standard_answer?: string | null;
  error_cause?: string | null;
  concept_ids?: number[];
  question_type?: "objective" | "process";
  actor?: "student" | "parent";
}

export interface DraftConfirmResponse {
  draft_id: number;
  grading_id: number;
  mistake_id: number;
  primary_topic_id: string | null;
  standard_answer: string;
  due_on: string | null;
  already_promoted: boolean;
}

export interface BankChoice {
  key: string;
  text: string;
  figure?: string | null;
}

export interface BankDraft {
  id: number;
  batch_id: number;
  filename: string | null;
  seq: number;
  status: string;
  has_placeholder: boolean;
  created_at: string;
  topic_id: string;
  topic_name: string | null;
  subject: string;
  type: string;
  difficulty: string;
  prompt: string;
  answer: string;
  acceptable: string[];
  unordered: boolean;
  verify: string;
  choices: BankChoice[];
  figure: string | null;
  source_ref: string;
}

export interface BankDraftListResponse {
  items: BankDraft[];
  total: number;
  limit: number;
  offset: number;
}

export interface BankApproveResponse {
  draft_id: number;
  status: string;
  problem_bank_id: number;
  verify_status: string;
}

export interface BankRejectResponse {
  draft_id: number;
  status: string;
}

export interface BankItemCreated {
  problem_bank_id: number;
  external_id: string;
  verify_status: string;
}

export interface AttemptInfo {
  id: number;
  mistake_id: number | null;
  kind: string;
  source: string;
  problem_bank_id: number | null;
  answer_text: string | null;
  is_correct: boolean;
  problem_text: string | null;
  question_id: string | null;
  topic_id: string | null;
  created_at: string;
}

export interface AttemptListResponse {
  items: AttemptInfo[];
  total: number;
  limit: number;
  offset: number;
}

export interface PracticeRecordInfo {
  id: number;
  source_mistake_id: number | null;
  problem_bank_id: number | null;
  kind: string;
  problem_text: string;
  student_answer: string | null;
  is_correct: boolean | null;
  created_at: string;
}

export interface PracticeListResponse {
  items: PracticeRecordInfo[];
  total: number;
  limit: number;
  offset: number;
}

export interface DashboardTopicWeakness {
  topic_id: string;
  name: string | null;
  subject: string | null;
  active_mistakes: number;
}

export interface DashboardSubjectWeakness {
  subject: string;
  active_mistakes: number;
}

export interface DashboardConceptMastery {
  concept_id: number;
  name: string;
  category_id: string;
  category_name: string | null;
  mastery: number;
}

export interface DashboardCurvePoint {
  date: string;
  mastery: number;
}

export interface DashboardInventory {
  active: number;
  voided: number;
  unassigned_active: number;
}

export interface DashboardMastery {
  overall: number;
  concepts: DashboardConceptMastery[];
  curve: DashboardCurvePoint[];
  curve_days: number;
}

export interface DashboardDue {
  today: number;
  overdue: number;
  total: number;
}

export interface DashboardCompletion {
  reviews_this_week: number;
  graduated_total: number;
  graduated_this_week: number;
}

export interface DashboardBankGapTopic {
  topic_id: string;
  name: string | null;
  subject: string | null;
  active_mistakes: number;
  open_schedules: number;
}

export interface DashboardBankGap {
  topics: DashboardBankGapTopic[];
  unassigned_open: number;
}

export interface DashboardGovernance {
  appeal_count: number;
  appealed_gradings: number;
  void_events: number;
  reactivate_events: number;
}

export interface DashboardEventStats {
  total_events: number;
  by_type: Record<string, number>;
  attempts_correct: number;
  attempts_wrong: number;
  attempt_accuracy: number | null;
}

export interface DashboardStreakDay {
  date: string;
  done: boolean;
}

export interface DashboardStreak {
  today_done: boolean;
  current_streak: number;
  longest_streak: number;
  learning_days_total: number;
  recent_days: DashboardStreakDay[];
}

export interface DashboardResponse {
  today: string;
  week_start: string;
  inventory: DashboardInventory;
  weak_topics: DashboardTopicWeakness[];
  weak_subjects: DashboardSubjectWeakness[];
  mastery: DashboardMastery;
  due: DashboardDue;
  completion: DashboardCompletion;
  bank_gap: DashboardBankGap;
  governance: DashboardGovernance;
  event_stats: DashboardEventStats;
  streak: DashboardStreak;
  pomodoros_today: number;
  focus_minutes_this_week: number;
}

export interface SessionStatus {
  pin_set: boolean;
  parent_unlocked: boolean;
}

export type CalendarKind = "exam" | "competition" | "leave" | "other";

export interface TimetableSlot {
  id: number;
  weekday: number;
  period: number;
  subject: string;
  note: string | null;
}

export interface TimetableResponse {
  items: TimetableSlot[];
}

export interface CalendarEvent {
  id: number;
  date: string;
  title: string;
  kind: CalendarKind;
  subject: string | null;
  note: string | null;
}

export interface CalendarEventsResponse {
  items: CalendarEvent[];
}

export interface PomodoroResponse {
  id: number;
  duration_minutes: number;
}
