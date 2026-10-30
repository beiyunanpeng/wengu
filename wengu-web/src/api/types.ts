export type QuestionType = "objective" | "process" | "open";

export interface CaptureCreated {
  capture_id: number;
  status: string;
  duplicate: boolean;
}

export interface SliceItem {
  seq: number;
  stored_path: string;
  bbox: number[];
  anchor_label: string | null;
  status: string;
}

export interface SliceResult {
  capture_id: number;
  status: string;
  already_sliced: boolean;
  header_line_count: number;
  column_split_x: number | null;
  item_count: number;
  items: SliceItem[];
}

export type GateStatus = "ready_for_grading" | "manual_review" | "figure_dependent";

export interface ExtractionInfo {
  id: number;
  seq: number;
  item_id: number | null;
  source_kind: "slice" | "whole_page";
  image_path: string;
  problem_text: string;
  student_answer: string | null;
  confidence: number | null;
  problem_complete: boolean | null;
  gate_status: GateStatus;
  review_reasons: string[];
  figure_keywords: string[];
  prompt_id: string;
  prompt_version: number;
  provider: string;
  model: string;
  created_at: string;
}

export interface ExtractionBatch {
  capture_id: number;
  source_kind: "slice" | "whole_page";
  total: number;
  extracted_count: number;
  skipped_count: number;
  failed_count: number;
  results: ExtractionInfo[];
  errors: { seq: number; reason: string }[];
}

export interface GradingVersionInfo {
  version: number;
  action: string;
  verdict: string;
  source: string;
  confidence: number | null;
  reason: string | null;
  provider: string | null;
  model: string | null;
  prompt_id: string | null;
  prompt_version: number | null;
  sample_verdicts: string[];
  created_at: string;
}

export interface GradingDetail {
  id: number;
  source_kind: string;
  source_id: number;
  problem_bank_id: number | null;
  question_type: string;
  problem_text: string;
  student_answer: string | null;
  standard_answer: string | null;
  acceptable_answers: string[];
  unordered: boolean;
  status: string;
  current_version: number;
  current_verdict: string;
  mistake_id: number | null;
  mistake_status: string | null;
  versions: GradingVersionInfo[];
  created_at: string;
  updated_at: string;
}

export interface CreateGradingPayload {
  source_kind: "problem_extraction" | "ingestion_draft";
  source_id: number;
  question_type: QuestionType;
  problem_bank_id?: number | null;
  answer?: string | null;
  acceptable?: string[];
  unordered?: boolean;
  samples?: number;
}

export interface CreateGradingResponse {
  route: "grading" | "explanation";
  duplicate: boolean;
  grading: GradingDetail | null;
}

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
  total: number;
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

export type ExplainSourceKind = "mistake" | "problem_extraction" | "ingestion_draft";
export type ExplainMode = "auto" | "guide" | "full";
export type FinalExplainMode = "guide" | "full";

export interface ExplanationResponse {
  source_kind: ExplainSourceKind;
  source_id: number;
  entry: "mistake" | "question";
  mode: FinalExplainMode;
  requested_mode: ExplainMode;
  default_mode: FinalExplainMode;
  strategy: string;
  strategy_label: string;
  hint_level: number | null;
  next_hint_level: number | null;
  attempted: boolean;
  soft_gate: boolean;
  answer_shown: boolean;
  leak_flags: string[];
  request_id: string;
  explanation: {
    focus: string;
    steps: string[];
    consolidation: string;
    answer: string | null;
  };
  meta: {
    provider: string;
    model: string;
    prompt_id: string;
    prompt_version: number;
    cache_hit: boolean;
    latency_ms: number;
  };
}

export interface ExplanationAttemptResponse {
  source_kind: ExplainSourceKind;
  source_id: number;
  attempt_id: string;
  recorded: boolean;
  attempted: boolean;
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
