<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "../api/client";
import type { Question } from "../types";
const items = ref<Question[]>([]),
  due = ref(0),
  generating = ref<number>();
const router = useRouter();
const route = useRoute();
const domain = computed(() =>
  typeof route.query.domain === "string" ? route.query.domain : undefined,
);
const domainLabels: Record<string, string> = {
  php: "PHP / Laravel",
  frontend: "前端 / Vue",
  database: "数据库",
  redis_async: "Redis 与异步",
  engineering: "工程能力",
  algorithms: "算法",
  projects: "项目深挖",
};
const domainTitle = computed(() =>
  domain.value ? (domainLabels[domain.value] ?? domain.value) : undefined,
);
onMounted(async () => {
  const r = await api.mistakes(domain.value);
  items.value = r.items;
  due.value = r.due_count;
});
async function variant(id: number) {
  generating.value = id;
  try {
    await api.generateVariant(id, 3);
  } finally {
    generating.value = undefined;
  }
}
async function retry(questionIds: number[] = []) {
  const attempt = await api.createAttempt("mistakes", questionIds);
  await router.push(`/attempts/${attempt.id}/review`);
}

function answerText(question: Question) {
  const answers = Array.isArray(question.answer)
    ? question.answer
    : [question.answer];
  const readable = answers
    .map((answer) => String(answer ?? "").trim())
    .filter(Boolean)
    .map((answer) => {
      const choice = question.choices?.find(
        (item) => item.key.toUpperCase() === answer.toUpperCase(),
      );
      return choice ? `${choice.key}. ${choice.text}` : answer;
    });
  return readable.join("、") || "—";
}
</script>
<template>
  <div class="page">
    <div class="page-head">
      <div>
        <span class="eyebrow">间隔复习</span>
        <h1>错题本{{ domainTitle ? ` · ${domainTitle}` : "" }}</h1>
        <p class="muted">
          今天有 {{ due }} 道到期。变式题会先检索可信来源，无法核验时不会生成。
        </p>
      </div>
      <el-button type="primary" :disabled="!items.length" @click="retry()"
        >开始到期重考</el-button
      >
    </div>
    <div v-if="!items.length" class="panel empty">暂无错题，继续保持。</div>
    <div
      v-for="q in items"
      :key="q.id"
      class="panel"
      style="margin-bottom: 12px"
    >
      <div class="tag-row">
        <el-tag>{{ q.domain }}</el-tag
        ><el-tag effect="plain">{{ q.difficulty }}</el-tag>
      </div>
      <p class="stem" style="margin: 12px 0">{{ q.stem }}</p>
      <div class="mistake-feedback">
        <div>
          <strong>正确答案</strong>
          <p>{{ answerText(q) }}</p>
        </div>
        <div>
          <strong>解析</strong>
          <p>
            {{
              q.explanation?.trim() ||
              "暂无解析，可查看题目来源或通过重考查看反馈。"
            }}
          </p>
        </div>
      </div>
      <div class="toolbar">
        <el-button type="primary" plain @click="retry([q.id])"
          >立即重考</el-button
        ><el-button :loading="generating === q.id" @click="variant(q.id)"
          >联网生成 3 道变式题</el-button
        ><a v-if="q.source_url" :href="q.source_url" target="_blank"
          >查看来源</a
        >
      </div>
    </div>
  </div>
</template>

<style scoped>
.mistake-feedback {
  display: grid;
  gap: 10px;
  margin: 14px 0;
  padding: 14px 16px;
  border: 1px solid #dbe7f4;
  border-radius: 8px;
  background: #f7faff;
}

.mistake-feedback strong {
  display: block;
  margin-bottom: 4px;
  color: #174a7e;
}

.mistake-feedback p {
  margin: 0;
  line-height: 1.7;
  white-space: pre-wrap;
}
</style>
