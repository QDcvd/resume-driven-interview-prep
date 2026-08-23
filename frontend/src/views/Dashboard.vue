<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { api } from "../api/client";
import type { Dashboard } from "../types";
const d = ref<Dashboard>();
const loading = ref(true);
const router = useRouter();
const weakDomains = computed(() => d.value?.weak_domains.slice(0, 4) ?? []);
const domainLabels: Record<string, string> = {
  php: "PHP / Laravel",
  frontend: "前端 / Vue",
  database: "数据库",
  redis_async: "Redis 与异步",
  engineering: "工程能力",
  algorithms: "算法",
  projects: "项目深挖",
};
function domainLabel(name: string) {
  return domainLabels[name] ?? name;
}
function focusText(score: number) {
  if (score < 40) return "优先补齐基础概念与面试表达";
  if (score < 60) return "加强高频场景和工程风险辨析";
  return "通过错题复练巩固答题稳定性";
}
onMounted(async () => {
  try {
    d.value = await api.dashboard();
  } finally {
    loading.value = false;
  }
});
async function startExam() {
  const a = await api.createAttempt("formal");
  router.push(`/attempts/${a.id}/review`);
}
async function startInterview() {
  try {
    const s = await api.createInterview();
    router.push(`/interview/${s.id}`);
  } catch (e) {
    const err = e as { response?: { data?: { detail?: string } } };
    ElMessage.error(err?.response?.data?.detail ?? "创建面试失败");
  }
}
</script>
<template>
  <div class="page" v-loading="loading">
    <div class="page-head">
      <div>
        <span class="eyebrow"
          >TODAY · 面试倒计时 {{ d?.days_left ?? "—" }} 天</span
        >
        <h1>今天，把薄弱点变成得分点</h1>
        <p class="muted">按岗位权重和复习间隔，为你安排最值得做的练习。</p>
      </div>
      <el-button plain @click="$router.push('/analytics')"
        >查看能力报告</el-button
      >
    </div>
    <el-alert
      v-if="d?.active_attempt"
      :closable="false"
      type="warning"
      show-icon
      ><template #title
        >你有一场未完成的考试：{{ d.active_attempt.title }}（{{
          d.active_attempt.progress
        }}%）</template
      ><el-button
        size="small"
        @click="$router.push(`/attempts/${d!.active_attempt!.id}/exam`)"
        >继续考试</el-button
      ></el-alert
    >
    <div class="grid grid-3" style="margin: 18px 0">
      <div class="panel metric">
        <span class="muted">今日待复习</span
        ><strong>{{ d?.due_count ?? 0 }} <small>题</small></strong>
      </div>
      <div class="panel metric">
        <span class="muted">最近正式卷</span
        ><strong>{{ d?.recent_score ?? "—" }} <small>分</small></strong>
      </div>
      <div class="panel metric">
        <span class="muted">连续学习</span
        ><strong>{{ d?.streak ?? 0 }} <small>天</small></strong>
      </div>
    </div>
    <div class="panel task-card">
      <div class="task-top">
        <div>
          <span class="eyebrow">今日主任务</span>
          <h2>50 题正式笔试</h2>
          <p class="muted">
            基于简历与 JD 生成的 50 道客观选择题，60 分钟限时，交卷即出分。
          </p>
        </div>
        <el-tag type="primary">50 题 · 60 分钟 · 满分 100</el-tag>
      </div>
      <div class="tag-row">
        <el-tag effect="plain">全客观选择题</el-tag
        ><el-tag effect="plain">无检查点</el-tag
        ><el-tag effect="plain">交卷即出分</el-tag
        ><el-tag effect="plain">成绩联动面试弱项</el-tag>
      </div>
      <div class="task-actions">
        <el-button type="primary" size="large" @click="startExam"
          >进入笔试</el-button
        ><el-button size="large" @click="startInterview"
          >模拟面试</el-button
        >
        <el-button size="large" plain @click="$router.push('/interviews')"
          >面试历史</el-button
        >
        <el-button size="large" plain @click="$router.push('/onboarding')"
          >初始化题库</el-button
        >
      </div>
    </div>
    <div class="section-title">
      <h2>需要优先补强</h2>
      <el-button link type="primary" @click="$router.push('/mistakes')"
        >进入错题本</el-button
      >
    </div>
    <div v-if="weakDomains.length" class="grid grid-3">
      <div v-for="x in weakDomains" :key="x.name" class="panel weak-domain-card">
        <div class="weak-domain-head">
          <b>{{ domainLabel(x.name) }}</b><strong>{{ x.score }} 分</strong>
        </div>
        <p class="muted">{{ focusText(x.score) }}</p>
        <small class="muted">已纳入 {{ x.answered }} 道已评分题</small
        ><el-progress
          :percentage="x.score"
          :stroke-width="8"
          style="margin-top: 15px"
        />
        <el-button
          link
          type="primary"
          @click="$router.push({ path: '/mistakes', query: { domain: x.name } })"
          >复习该领域错题</el-button
        >
      </div>
    </div>
    <div v-else-if="d" class="panel empty ability-empty-state">
      完成一次正式考试后，系统会在这里生成优先补强领域。
    </div>
  </div>
</template>
