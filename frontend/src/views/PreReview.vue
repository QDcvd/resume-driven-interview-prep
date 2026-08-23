<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useExamStore } from "../stores/exam";
import { api } from "../api/client";
const store = useExamStore(),
  route = useRoute(),
  router = useRouter(),
  loading = ref(true);
onMounted(async () => {
  await store.load(Number(route.params.id));
  loading.value = false;
});
const done = computed(
  () => store.attempt?.review_cards.filter((x) => x.checked).length ?? 0,
);
async function begin() {
  const a = await api.confirmReview(Number(route.params.id));
  store.setAttempt(a);
  router.push(`/attempts/${a.id}/exam`);
}
</script>
<template>
  <div class="page" v-loading="loading">
    <div class="page-head">
      <div>
        <span class="eyebrow">考前复习</span>
        <h1>先唤醒知识，再开始计时</h1>
        <p class="muted">
          系统从完整知识库中按本卷考点精选最多 15 张卡片，不展示原题和答案；复习用时不计入考试。
        </p>
      </div>
      <el-progress
        type="circle"
        :percentage="
          store.attempt?.review_cards.length
            ? Math.round((done / store.attempt.review_cards.length) * 100)
            : 0
        "
        :width="72"
      />
    </div>
    <div
      v-for="c in store.attempt?.review_cards"
      :key="c.id"
      class="panel review-card"
    >
      <el-checkbox v-model="c.checked"
        ><h3>
          {{ c.title }}
          <el-tag size="small" effect="plain">{{ c.domain }}</el-tag>
        </h3></el-checkbox
      >
      <p style="white-space: pre-line; line-height: 1.8">{{ c.summary }}</p>
      <div v-if="c.pitfalls.length" class="pitfalls">
        <b>易错提醒：</b>{{ c.pitfalls.join("；") }}
      </div>
    </div>
    <div
      class="panel"
      style="
        position: sticky;
        bottom: 14px;
        display: flex;
        justify-content: space-between;
        align-items: center;
      "
    >
      <span class="muted"
        >本次精选 {{ store.attempt?.review_cards.length ?? 0 }} 张，已确认 {{ done }} /
        {{ store.attempt?.review_cards.length ?? 0 }} 个知识点</span
      >
      <div>
        <el-button @click="begin">跳过复习</el-button
        ><el-button
          type="primary"
          :disabled="done !== (store.attempt?.review_cards.length ?? 0)"
          @click="begin"
          >我已复习，开始考试</el-button
        >
      </div>
    </div>
  </div>
</template>
