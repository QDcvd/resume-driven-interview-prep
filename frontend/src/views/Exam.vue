<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter, onBeforeRouteLeave } from "vue-router";
import { ElMessageBox, ElMessage } from "element-plus";
import { useExamStore } from "../stores/exam";
import { api } from "../api/client";
import CodeEditor from "../components/CodeEditor.vue";
const s = useExamStore(),
  route = useRoute(),
  router = useRouter(),
  running = ref(false),
  submitting = ref(false);
const q = computed(() => s.current);
const answer = computed({
  get: () =>
    s.attempt?.answers[q.value?.id ?? -1]?.value ??
    (q.value?.type === "multiple" ? [] : ""),
  set: (v) =>
    q.value &&
    s.remaining > 1 &&
    s.updateAnswer(q.value.id, v, s.attempt?.answers[q.value.id]?.flagged),
});
const time = computed(
  () =>
    `${String(Math.floor(s.remaining / 3600)).padStart(2, "0")}:${String(Math.floor((s.remaining % 3600) / 60)).padStart(2, "0")}:${String(s.remaining % 60).padStart(2, "0")}`,
);
const checkpoint = computed(() => Math.floor(s.currentIndex / 25) + 1);
const checkpointTotal = computed(() =>
  Math.max(1, Math.ceil((s.attempt?.questions.length ?? 1) / 25)),
);
onMounted(async () => {
  await s.load(Number(route.params.id));
  // 页面加载时考试已超时（例如刷新/恢复页面），立即自动交卷，
  // 否则 remaining 直接为 0，倒计时 watch 不会触发，考试会卡住。
  if (s.remaining === 0 && s.attempt?.status === "in_progress") {
    submit(true);
  }
});
onBeforeUnmount(() => s.flush());
onBeforeRouteLeave(async () => {
  await s.flush();
  return true;
});
watch(
  () => s.remaining,
  async (v) => {
    if (v === 1) await s.flush();
    if (v === 0) submit(true);
  },
);
function flag() {
  if (!q.value) return;
  const a = s.attempt?.answers[q.value.id];
  s.updateAnswer(q.value.id, a?.value ?? "", !a?.flagged);
}
async function next() {
  if (!s.attempt) return;
  if ((s.currentIndex + 1) % 25 === 0) {
    await s.flush();
    const feedback = (await api.checkpoint(s.attempt.id, checkpoint.value)) as {
      answered: number;
      objective_correct: number;
      objective_total: number;
      weak_categories: string[];
    };
    const weak = feedback.weak_categories.length
      ? `；需留意：${feedback.weak_categories.join("、")}`
      : "";
    await ElMessageBox.alert(
      `本段已答 ${feedback.answered}/25，客观题正确 ${feedback.objective_correct}/${feedback.objective_total}${weak}。`,
      "检查点完成",
    );
  }
  if (s.currentIndex < s.attempt.questions.length - 1) s.currentIndex++;
}
async function submit(timedOut = false) {
  if (!s.attempt || submitting.value) return;
  submitting.value = true;
  try {
    if (!timedOut) {
      await ElMessageBox.confirm(
        "交卷后不能继续修改答案，确认提交？",
        "提交整卷",
        { type: "warning" },
      );
      await s.flush();
    } else {
      ElMessage.warning("考试时间已到，系统正在自动交卷。");
    }
    await api.submit(s.attempt.id);
    await router.push(`/attempts/${s.attempt.id}/result`);
  } finally {
    submitting.value = false;
  }
}
async function run() {
  if (typeof answer.value !== "string") return;
  running.value = true;
  try {
    const r = await api.runCode(answer.value, q.value?.id);
    if (q.value && s.attempt?.answers[q.value.id])
      s.attempt.answers[q.value.id].code_result = r;
    ElMessage.success(`通过 ${r.passed}/${r.total} 个测试`);
  } finally {
    running.value = false;
  }
}
</script>
<template>
  <template v-if="s.attempt && q"
    ><header class="exam-header">
      <div>
        <b>{{ s.attempt.title }}</b
        ><span class="muted">
          · 第 {{ checkpoint }} / {{ checkpointTotal }} 区段</span
        >
      </div>
      <div class="toolbar">
        <span
          ><i class="status-dot" />
          {{
            s.saveState === "saving"
              ? "保存中"
              : s.saveState === "error"
                ? "保存失败"
                : "已自动保存"
          }}</span
        ><el-divider direction="vertical" /><b
          :style="{ color: s.remaining < 600 ? '#c4473a' : '' }"
          >{{ time }}</b
        ><el-button type="danger" plain @click="submit">交卷</el-button>
      </div>
    </header>
    <div class="exam-layout">
      <section class="panel question-box">
        <div class="question-meta">
          <span
            >第 <b>{{ s.currentIndex + 1 }}</b> /
            {{ s.attempt.questions.length }} 题 · {{ q.type }}</span
          >
          <div class="tag-row">
            <el-tag size="small" effect="plain">{{ q.domain }}</el-tag
            ><el-tag size="small" effect="plain">{{ q.difficulty }}</el-tag>
          </div>
        </div>
        <div class="stem">{{ q.stem }}</div>
        <el-radio-group
          v-if="q.type === 'single'"
          v-model="answer"
          style="display: block"
          ><el-radio
            v-for="c in q.choices"
            :key="c.key"
            :value="c.key"
            class="choice"
            >{{ c.key }}. {{ c.text }}</el-radio
          ></el-radio-group
        ><el-checkbox-group v-else-if="q.type === 'multiple'" v-model="answer"
          ><el-checkbox
            v-for="c in q.choices"
            :key="c.key"
            :value="c.key"
            class="choice"
            >{{ c.key }}. {{ c.text }}</el-checkbox
          ></el-checkbox-group
        ><template v-else-if="q.type === 'code'"
          ><CodeEditor v-model="answer as string" />
          <div class="toolbar" style="margin-top: 12px">
            <el-button type="primary" plain :loading="running" @click="run"
              >运行示例与隐藏测试</el-button
            ><span v-if="s.attempt.answers[q.id]?.code_result" class="muted"
              >通过 {{ s.attempt.answers[q.id].code_result!.passed }} /
              {{ s.attempt.answers[q.id].code_result!.total }}</span
            >
          </div></template
        ><el-input
          v-else
          v-model="answer"
          type="textarea"
          class="answer-text"
          placeholder="请用结构化语言作答：先结论，再原理，最后结合项目说明……"
          show-word-limit
          maxlength="5000"
        />
        <div
          style="
            display: flex;
            justify-content: space-between;
            margin-top: 26px;
          "
        >
          <el-button :disabled="s.currentIndex === 0" @click="s.currentIndex--"
            >上一题</el-button
          >
          <div>
            <el-button
              :type="s.attempt.answers[q.id]?.flagged ? 'warning' : 'default'"
              @click="flag"
              >{{
                s.attempt.answers[q.id]?.flagged ? "已标记" : "标记复查"
              }}</el-button
            ><el-button type="primary" @click="next">{{
              (s.currentIndex + 1) % 25 === 0 ? "完成本区段" : "下一题"
            }}</el-button>
          </div>
        </div>
      </section>
      <aside class="panel answer-card">
        <div style="display: flex; justify-content: space-between">
          <b>答题卡</b><span class="muted">{{ s.progress }}%</span>
        </div>
        <el-progress
          :percentage="s.progress"
          :show-text="false"
          style="margin: 12px 0 18px"
        />
        <div class="answer-grid">
          <button
            v-for="(item, i) in s.attempt.questions"
            :key="item.id"
            :class="[
              'answer-number',
              {
                done: s.attempt.answers[item.id],
                current: i === s.currentIndex,
                flagged: s.attempt.answers[item.id]?.flagged,
              },
            ]"
            @click="s.currentIndex = i"
          >
            {{ i + 1 }}
          </button>
        </div>
        <el-divider />
        <div class="muted" style="font-size: 12px">
          蓝色：已作答　橙边：已标记<br />每 25 题自动形成检查点
        </div>
      </aside>
    </div></template
  >
</template>
