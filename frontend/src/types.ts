export type QuestionType =
  "single" | "multiple" | "short" | "project" | "system_design" | "code";
export type AttemptStatus =
  "reviewing" | "in_progress" | "submitted" | "grading" | "completed";
export interface Choice {
  key: string;
  text: string;
}
export interface Question {
  id: number;
  stem: string;
  type: QuestionType;
  domain: string;
  tags: string[];
  difficulty: "基础" | "实战" | "深挖";
  choices?: Choice[];
  answer?: unknown;
  explanation?: string;
  scoring_points?: string[];
  visible_tests?: string[];
  hidden_tests?: string[];
  source_url?: string;
  code_template?: string;
  examples?: { input: string; output: string }[];
  enabled?: boolean;
}
export interface Answer {
  question_id: number;
  value: string | string[];
  flagged: boolean;
  saved_at?: string;
  code_result?: CodeResult;
}
export interface ReviewCard {
  id: number;
  title: string;
  domain: string;
  summary: string;
  pitfalls: string[];
  checked?: boolean;
}
export interface Attempt {
  id: number;
  title: string;
  mode: string;
  status: AttemptStatus;
  duration_seconds: number;
  started_at?: string;
  expires_at?: string;
  current_index: number;
  checkpoint: number;
  questions: Question[];
  answers: Record<number, Answer>;
  review_cards: ReviewCard[];
}
export interface Dashboard {
  interview_date: string;
  days_left: number;
  due_count: number;
  weak_domains: Ability[];
  recent_score: number | null;
  streak: number;
  active_attempt?: {
    id: number;
    title: string;
    progress: number;
    remaining_seconds: number;
  };
  today: {
    title: string;
    description: string;
    question_count: number;
    estimated_minutes: number;
  };
}
export interface Ability {
  name: string;
  score: number;
  answered: number;
  trend: number;
}
export interface GradeItem {
  question_id: number;
  position: number;
  question_stem: string;
  domain: string;
  type: QuestionType;
  candidate_answer: string | string[];
  score: number;
  max_score: number;
  status: string;
  hits: string[];
  omissions: string[];
  errors: string[];
  improved_answer: string;
  confidence: number;
  manual_score?: number;
}
export interface ReviewResult {
  attempt_id: number;
  total_score: number;
  objective_score: number;
  pending_count: number;
  grades: GradeItem[];
  domain_scores: Ability[];
}
export interface CodeResult {
  passed: number;
  total: number;
  stdout: string;
  stderr: string;
  timed_out: boolean;
  duration_ms: number;
}
export interface Settings {
  interview_date: string;
  llm_model: string;
  llm_configured: boolean;
  grading_concurrency: number;
  max_grading_batch: number;
  autosave_delay_ms: number;
}
export interface ResumeData {
  id: number;
  filename: string;
  status: string;
  source: string;
  error: string | null;
  structured: Record<string, unknown>;
  job_description: string;
  raw_preview: string;
  created_at?: string;
}
export interface PlanDomain {
  domain: string;
  count: number;
  difficulty: { basic: number; practical: number; deep: number };
}
export interface QuestionPlan {
  id: number;
  resume_id: number;
  status: string; // pending | confirming | generating | done | failed
  total: number;
  generated_count: number;
  error: string | null;
  plan: { domains?: PlanDomain[]; rationale?: string } | null;
  created_at?: string;
}
export interface InterviewBlueprintItem {
  type: string;
  question: string;
  focus: string;
  category?: string;
}
export interface InterviewSession {
  id: number;
  resume_id: number;
  status: string; // active | ended
  stage: string;
  current_index: number;
  follow_up_count: number;
  blueprint: { questions?: InterviewBlueprintItem[]; rationale?: string };
  weak_areas: string[];
  created_at?: string;
  started_at?: string;
  ended_at?: string;
}
export interface InterviewMessageItem {
  id: number;
  role: string; // interviewer | user
  content: string;
  created_at?: string;
}
export interface InterviewReportQuestion {
  question: string;
  user_answer: string;
  score: number;
  max_score: number;
  corrections?: string[];
  recommended_answer?: string;
  principle?: string;
}
export interface InterviewReportItem {
  id: number;
  session_id: number;
  summary_text: string;
  score: number;
  questions: InterviewReportQuestion[];
  created_at?: string;
}
export interface LlmProvider {
  display_name: string;
  base_url: string;
  api_key: string;
  model: string;
  configured: boolean;
  active: boolean;
}
