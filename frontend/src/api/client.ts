import axios from "axios";
import type {
  Ability,
  Attempt,
  Candidate,
  CodeResult,
  Dashboard,
  InterviewMessageItem,
  InterviewReportItem,
  InterviewSession,
  LlmProvider,
  Question,
  QuestionPlan,
  ResumeData,
  ReviewCard,
  ReviewResult,
  Settings,
} from "../types";

const http = axios.create({ baseURL: "/api", timeout: 30000 });
const body = <T>(promise: Promise<{ data: T }>) =>
  promise.then((response) => response.data);
type RawQuestion = {
  id: number;
  type: string;
  difficulty: string;
  category: string;
  stem: string;
  options?: string[];
  tags?: string[];
  source_url?: string;
  correct_answer?: unknown;
  explanation?: string;
  scoring_points?: string[];
  visible_tests?: string[];
  hidden_tests?: string[];
  enabled?: boolean;
};
type RawGrade = {
  score: number;
  max_score: number;
  matched_points: string[];
  missing_points: string[];
  incorrect_claims: string[];
  improved_answer: string;
  confidence: number;
  source: string;
};
type RawReviewCard = {
  id: number;
  title: string;
  content: string;
  category: string;
  tags?: string[];
};
type RawAttempt = {
  id: number;
  mode: string;
  status: string;
  started_at?: string;
  deadline_at?: string;
  duration_minutes: number;
  questions: { position: number; weight: number; question: RawQuestion }[];
  answers: {
    question_id: number;
    answer: string | string[];
    flagged: boolean;
    updated_at?: string;
    grading?: RawGrade | null;
    grading_status?: string | null;
  }[];
  checkpoints: { number: number }[];
  review_cards?: RawReviewCard[];
  domain_scores?: Ability[];
};

function question(raw: RawQuestion): Question {
  const correct = raw.correct_answer;
  const multi = Array.isArray(correct);
  const type =
    raw.type === "choice"
      ? multi
        ? "multiple"
        : "single"
      : raw.type === "short_answer"
        ? "short"
        : raw.type;
  return {
    id: raw.id,
    stem: raw.stem,
    type: type as Question["type"],
    domain: raw.category,
    tags: raw.tags ?? [],
    difficulty:
      raw.difficulty === "basic"
        ? "基础"
        : raw.difficulty === "deep"
          ? "深挖"
          : "实战",
    choices: (raw.options ?? []).map((text, index) => ({
      key: String.fromCharCode(65 + index),
      text,
    })),
    answer: correct,
    explanation: raw.explanation,
    scoring_points: raw.scoring_points ?? [],
    visible_tests: raw.visible_tests ?? [],
    hidden_tests: raw.hidden_tests ?? [],
    source_url: raw.source_url,
    enabled: raw.enabled ?? true,
  };
}
function reviewCard(raw: RawReviewCard): ReviewCard {
  return {
    id: raw.id,
    title: raw.title,
    domain: raw.category,
    summary: raw.content,
    pitfalls: raw.tags ?? [],
  };
}
function attempt(raw: RawAttempt): Attempt {
  const answers = Object.fromEntries(
    (raw.answers ?? []).map((item) => [
      item.question_id,
      {
        question_id: item.question_id,
        value: item.answer,
        flagged: item.flagged,
        saved_at: item.updated_at,
      },
    ]),
  );
  const titles: Record<string, string> = {
    formal: "100 题全真模拟",
    quick: "10 题快速练习",
    expression: "表达训练",
    mistakes: "错题重考",
    code: "Python 思路题",
  };
  return {
    id: raw.id,
    title: titles[raw.mode] ?? "专项练习",
    mode: raw.mode,
    status: raw.status as Attempt["status"],
    duration_seconds: (raw.duration_minutes ?? 150) * 60,
    started_at: raw.started_at,
    expires_at: raw.deadline_at,
    current_index: 0,
    checkpoint: Math.max(1, ...(raw.checkpoints ?? []).map((x) => x.number)),
    questions: (raw.questions ?? [])
      .sort((a, b) => a.position - b.position)
      .map((x) => question(x.question)),
    answers,
    review_cards: (raw.review_cards ?? []).map(reviewCard),
  };
}
function dashboard(raw: Record<string, unknown>): Dashboard {
  const days = Number(raw.days_until_interview ?? 0),
    activeId = raw.active_attempt_id as number | undefined,
    active = raw.active_attempt as
      | {
          id: number;
          title: string;
          progress: number;
          remaining_seconds: number;
        }
      | null
      | undefined;
  return {
    interview_date: "",
    days_left: days,
    due_count: Number(raw.due_count ?? 0),
    weak_domains: (raw.abilities as Dashboard["weak_domains"]) ?? [],
    recent_score:
      raw.recent_score === null || raw.recent_score === undefined
        ? null
        : Number(raw.recent_score),
    streak: 0,
    active_attempt: active
      ? {
          id: active.id,
          title: active.title,
          progress: active.progress,
          remaining_seconds: active.remaining_seconds,
        }
      : activeId
      ? {
          id: activeId,
          title: "未完成的正式考试",
          progress: 0,
          remaining_seconds: 0,
        }
      : undefined,
    today: {
      title: "100 题全真模拟",
      description: `距离面试还有 ${days} 天，完成一次完整检验。`,
      question_count: 100,
      estimated_minutes: 150,
    },
  };
}
function settings(raw: Record<string, unknown>): Settings {
  return {
    interview_date: String(raw.interview_date ?? ""),
    llm_model: String(raw.llm_model ?? ""),
    llm_configured: Boolean(raw.llm_configured),
    grading_concurrency: Number(raw.llm_max_concurrency ?? 2),
    max_grading_batch: Number(raw.max_grading_batch ?? 100),
    autosave_delay_ms: Number(raw.autosave_delay_ms ?? 800),
  };
}

type RawResume = {
  id: number;
  filename: string;
  status: string;
  source: string;
  error?: string | null;
  structured?: Record<string, unknown>;
  job_description?: string;
  raw_preview?: string;
  created_at?: string;
};
type RawPlan = {
  id: number;
  resume_id: number;
  status: string;
  total: number;
  generated_count: number;
  error?: string | null;
  plan?: QuestionPlan["plan"];
  created_at?: string;
};
function resume(raw: RawResume): ResumeData {
  return {
    id: raw.id,
    filename: raw.filename,
    status: raw.status,
    source: raw.source,
    error: raw.error ?? null,
    structured: raw.structured ?? {},
    job_description: raw.job_description ?? "",
    raw_preview: raw.raw_preview ?? "",
    created_at: raw.created_at,
  };
}
function plan(raw: RawPlan): QuestionPlan {
  return {
    id: raw.id,
    resume_id: raw.resume_id,
    status: raw.status,
    total: raw.total,
    generated_count: raw.generated_count,
    error: raw.error ?? null,
    plan: raw.plan ?? null,
    created_at: raw.created_at,
  };
}

export const api = {
  dashboard: () =>
    body(http.get<Record<string, unknown>>("/dashboard")).then(dashboard),
  activeAttempt: () =>
    body(http.get<RawAttempt | null>("/attempts/active")).then((value) =>
      value ? attempt(value) : null,
    ),
  createAttempt: (mode = "formal", questionIds: number[] = []) =>
    body(
      http.post<RawAttempt>("/attempts", {
        mode,
        question_ids: questionIds,
      }),
    ).then(attempt),
  attempt: (id: number) =>
    body(http.get<RawAttempt>(`/attempts/${id}`)).then(attempt),
  confirmReview: (id: number) =>
    body(http.post<RawAttempt>(`/attempts/${id}/review-confirm`)).then(attempt),
  saveAnswer: (
    attemptId: number,
    questionId: number,
    payload: { value: string | string[]; flagged: boolean },
  ) =>
    body(
      http.put(`/attempts/${attemptId}/answers/${questionId}`, {
        answer: payload.value,
        flagged: payload.flagged,
        elapsed_seconds: 0,
      }),
    ),
  checkpoint: (id: number, n: number) =>
    body(http.post(`/attempts/${id}/checkpoints/${n}`)),
  submit: (id: number) => body(http.post(`/attempts/${id}/submit`)),
  review: (id: number) =>
    body(http.get<RawAttempt>(`/attempts/${id}/review`)).then((raw) => {
      const a = attempt(raw),
        objective = a.questions.filter(
          (q) => q.type === "single" || q.type === "multiple",
        ),
        correct = objective.filter(
          (q) =>
            JSON.stringify(a.answers[q.id]?.value) === JSON.stringify(q.answer),
        ).length,
        objectiveScore = Math.round(
          (correct / Math.max(1, objective.length)) * 40,
        ),
        grades = raw.answers
          .filter((x) => x.grading)
          .map((x) => {
            const questionIndex = a.questions.findIndex(
              (q) => q.id === x.question_id,
            );
            const question = a.questions[questionIndex];
            return {
              question_id: x.question_id,
              position: questionIndex + 1,
              question_stem: question?.stem ?? "题目内容不可用",
              domain: question?.domain ?? "未分类",
              type: question?.type ?? "short",
              candidate_answer: a.answers[x.question_id]?.value ?? "",
              score: x.grading!.score,
              max_score: x.grading!.max_score,
              status: x.grading!.source,
              hits: x.grading!.matched_points,
              omissions: x.grading!.missing_points,
              errors: x.grading!.incorrect_claims,
              improved_answer: x.grading!.improved_answer,
              confidence: x.grading!.confidence,
            };
          }),
        pending = a.questions.filter(
          (q) =>
            !["single", "multiple"].includes(q.type) &&
            a.answers[q.id]?.value &&
            ["pending", "failed"].includes(
              raw.answers.find((x) => x.question_id === q.id)?.grading_status ??
                "",
            ),
        ).length,
        pointsByType: Partial<Record<Question["type"], number>> = {
          short: 25 / 20,
          project: 20 / 8,
          system_design: 15 / 2,
          code: 10,
        },
        subjectiveScore = grades.reduce((sum, grade) => {
          const question = a.questions.find((q) => q.id === grade.question_id);
          const weight = question ? (pointsByType[question.type] ?? 0) : 0;
          return sum + (grade.score / Math.max(1, grade.max_score)) * weight;
        }, 0);
      return {
        attempt_id: id,
        total_score: Math.round(objectiveScore + subjectiveScore),
        objective_score: objectiveScore,
        pending_count: pending,
        grades,
        domain_scores: raw.domain_scores ?? [],
      } satisfies ReviewResult;
    }),
  startGrading: (_attemptId?: number) =>
    body(
      http.post<{ accepted: boolean; pending: number }>("/grading/run"),
    ).then((x) => ({
      job_id: "manual",
      pending: x.pending,
      accepted: x.accepted,
    })),
  stopGrading: (_jobId: string) => body(http.post("/grading/stop")),
  requeueGrading: (attemptId: number, includeCompleted = false) =>
    body<{ requeued: number }>(
      http.post("/grading/requeue", undefined, {
        params: { attempt_id: attemptId, include_completed: includeCompleted },
      }),
    ),
  overrideGrade: (
    attemptId: number,
    questionId: number,
    score: number,
    reason: string,
  ) =>
    body(
      http.post(`/attempts/${attemptId}/grades/${questionId}/override`, {
        score,
        reason,
      }),
    ),
  runCode: (code: string, questionId?: number) =>
    body(
      http.post<Record<string, unknown>>("/code/run", {
        code,
        question_id: questionId,
        visible_tests: [],
        hidden_tests: [],
      }),
    ).then(
      (raw) =>
        ({
          passed:
            Number(raw.visible_passed ?? 0) + Number(raw.hidden_passed ?? 0),
          total: Number(raw.visible_total ?? 0) + Number(raw.hidden_total ?? 0),
          stdout: "",
          stderr: ((raw.failures as string[]) ?? []).join("\n"),
          timed_out: Boolean(raw.timed_out),
          duration_ms: 0,
        }) satisfies CodeResult,
    ),
  questions: (params: Record<string, unknown>) =>
    body(
      http.get<{ items: RawQuestion[]; total: number }>("/questions", {
        params: {
          search: params.q,
          category: params.domain,
          offset: (Number(params.page) - 1) * 50,
          limit: 50,
        },
      }),
    ).then((x) => ({ total: x.total, items: x.items.map(question) })),
  reviewCards: (params: { q?: string; domain?: string; page?: number }) =>
    body(
      http.get<{
        total: number;
        items: RawReviewCard[];
      }>("/review-cards", {
        params: {
          search: params.q,
          category: params.domain,
          offset: ((params.page ?? 1) - 1) * 50,
          limit: 50,
        },
      }),
    ).then((result) => ({
      total: result.total,
      items: result.items.map(reviewCard),
    })),
  saveQuestion: (q: Partial<Question>) => {
    const payload = {
      external_id: `manual-${q.id ?? Date.now()}`,
      type:
        q.type === "single" || q.type === "multiple"
          ? "choice"
          : q.type === "short"
            ? "short_answer"
            : q.type,
      difficulty:
        q.difficulty === "基础"
          ? "basic"
          : q.difficulty === "深挖"
            ? "deep"
            : "practical",
      category: q.domain ?? "未分类",
      stem: q.stem ?? "",
      options: q.choices?.map((x) => x.text) ?? [],
      correct_answer: q.answer ?? "",
      explanation: q.explanation ?? "",
      scoring_points: q.scoring_points ?? [],
      visible_tests: q.visible_tests ?? [],
      hidden_tests: q.hidden_tests ?? [],
      tags: q.tags ?? [],
      source_url: q.source_url ?? "",
      verified_at: null,
      is_core: true,
      enabled: q.enabled ?? true,
    };
    return q.id
      ? body(http.put(`/questions/${q.id}`, payload))
      : body(http.post("/questions", payload));
  },
  candidates: () => body(http.get<Candidate[]>("/candidates")),
  reviewCandidate: (id: number, decision: "approve" | "reject") =>
    body(http.post(`/candidates/${id}/${decision}`)),
  mistakes: (domain?: string) =>
    body(
      http.get<{ items: RawQuestion[]; due_count: number }>("/mistakes", {
        params: domain ? { category: domain } : undefined,
      }),
    ).then((x) => ({ ...x, items: x.items.map(question) })),
  generateVariant: (id: number, count: number) =>
    body(http.post(`/questions/${id}/variants`, { count })),
  abilities: () => body(http.get<Ability[]>("/stats/abilities")),
  settings: () =>
    body(http.get<Record<string, unknown>>("/settings")).then(settings),
  saveSettings: (value: Partial<Settings>) =>
    body(
      http.put<Record<string, unknown>>("/settings", {
        interview_date: value.interview_date,
        llm_max_concurrency: value.grading_concurrency,
      }),
    ).then(settings),
  exportQuestions: () =>
    http
      .get("/questions/export", { responseType: "blob" })
      .then((response) => response.data as Blob),
  importQuestions: (file: File) =>
    file
      .text()
      .then((text) => body(http.post("/questions/import", JSON.parse(text)))),
  backup: () => body(http.post("/settings/backup")),
  // ---- 简历 + 规划表（初始化流程）----
  latestResume: () =>
    body(http.get<RawResume | null>("/resumes/latest")).then((raw) =>
      raw ? resume(raw) : null,
    ),
  uploadResume: (file: File, jobDescription: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("job_description", jobDescription);
    return body(http.post<RawResume>("/resumes", form)).then(resume);
  },
  createPlan: (resumeId: number) =>
    body(http.post<RawPlan>(`/resumes/${resumeId}/plan`)).then(plan),
  resumePlan: (resumeId: number) =>
    body(http.get<RawPlan>(`/resumes/${resumeId}/plan`)).then(plan),
  getPlan: (planId: number) =>
    body(http.get<RawPlan>(`/plans/${planId}`)).then(plan),
  confirmPlan: (planId: number) =>
    body(http.post<RawPlan>(`/plans/${planId}/confirm`)).then(plan),
  retryPlan: (planId: number) =>
    body(http.post<RawPlan>(`/plans/${planId}/retry`)).then(plan),
  // ---- LLM provider（设置页模型配置）----
  llmProvider: () => body(http.get<LlmProvider>("/llm/provider")),
  saveLlmProvider: (value: {
    display_name: string;
    base_url: string;
    api_key: string;
    model: string;
  }) => body(http.put<LlmProvider>("/llm/provider", value)),
  // ---- 模拟面试 ----
  createInterview: () =>
    body(http.post<InterviewSession>("/interview/sessions", {})),
  interviewDetail: (id: number) =>
    body(http.get<InterviewSession & { messages: InterviewMessageItem[] }>(
      `/interview/sessions/${id}`,
    )),
  interviewList: () =>
    body(http.get<InterviewSession[]>("/interview/sessions")),
  interviewReport: (id: number) =>
    body(http.get<InterviewReportItem>(`/interview/sessions/${id}/report`)),
  endInterview: (id: number) =>
    body(http.post<InterviewSession>(`/interview/sessions/${id}/end`)),
};
