import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api } from "../api/client";
import type { Answer, Attempt } from "../types";
export const useExamStore = defineStore("exam", () => {
  const attempt = ref<Attempt | null>(null),
    currentIndex = ref(0),
    remaining = ref(0),
    saveState = ref<"saved" | "saving" | "error">("saved");
  const current = computed(() => attempt.value?.questions[currentIndex.value]);
  const progress = computed(() =>
    attempt.value
      ? Math.round(
          (Object.keys(attempt.value.answers).length /
            attempt.value.questions.length) *
            100,
        )
      : 0,
  );
  let timer: number | undefined;
  const pending = new Map<number, number>();
  function setAttempt(v: Attempt) {
    attempt.value = v;
    currentIndex.value = v.current_index || 0;
    remaining.value = calcRemaining(v);
    startClock();
  }
  function calcRemaining(v: Attempt) {
    if (v.expires_at)
      return Math.max(
        0,
        Math.floor((new Date(v.expires_at).getTime() - Date.now()) / 1000),
      );
    return v.duration_seconds;
  }
  async function load(id: number) {
    setAttempt(await api.attempt(id));
  }
  async function create(mode = "formal") {
    setAttempt(await api.createAttempt(mode));
    return attempt.value!;
  }
  function startClock() {
    if (timer) clearInterval(timer);
    if (attempt.value?.status === "in_progress")
      timer = window.setInterval(
        () => (remaining.value = Math.max(0, remaining.value - 1)),
        1000,
      );
  }
  function updateAnswer(
    questionId: number,
    value: string | string[],
    flagged = false,
  ) {
    if (!attempt.value) return;
    const a: Answer = { question_id: questionId, value, flagged };
    attempt.value.answers[questionId] = a;
    saveState.value = "saving";
    const old = pending.get(questionId);
    if (old) clearTimeout(old);
    pending.set(
      questionId,
      window.setTimeout(async () => {
        try {
          await api.saveAnswer(attempt.value!.id, questionId, {
            value,
            flagged,
          });
          saveState.value = "saved";
        } catch {
          saveState.value = "error";
        }
      }, 800),
    );
  }
  async function flush() {
    if (!attempt.value) return;
    for (const timeout of pending.values()) clearTimeout(timeout);
    pending.clear();
    try {
      await Promise.all(
        Object.values(attempt.value.answers).map((a) =>
          api.saveAnswer(attempt.value!.id, a.question_id, {
            value: a.value,
            flagged: a.flagged,
          }),
        ),
      );
      saveState.value = "saved";
    } catch {
      // 保存失败可预期（如超时后后端已自动交卷并返回 409），
      // 不应抛出让自动交卷/离开页面的流程中断。
      saveState.value = "error";
    }
  }
  return {
    attempt,
    currentIndex,
    current,
    remaining,
    progress,
    saveState,
    setAttempt,
    load,
    create,
    updateAnswer,
    flush,
  };
});
