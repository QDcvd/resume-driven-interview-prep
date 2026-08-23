<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { api } from "../api/client";
import type { InterviewReportItem, InterviewSession } from "../types";

const router = useRouter();
const sessions = ref<InterviewSession[]>([]);
const reports = ref<Record<number, InterviewReportItem>>({});
const loading = ref(true);

const stageLabel: Record<string, string> = {
  opening: "开场",
  ask: "提问",
  followup: "追问",
  closing: "收尾",
  reporting: "报告生成中",
};

onMounted(async () => {
  try {
    sessions.value = await api.interviewList();
    await Promise.all(
      sessions.value
        .filter((s) => s.status === "ended")
        .map(async (s) => {
          const r = await api.interviewReport(s.id).catch(() => null);
          if (r) reports.value[s.id] = r;
        }),
    );
  } finally {
    loading.value = false;
  }
});

function open(session: InterviewSession) {
  router.push(`/interview/${session.id}`);
}

async function createAndOpen() {
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
        <span class="eyebrow">MOCK INTERVIEW</span>
        <h1>模拟面试历史</h1>
        <p class="muted">可重复进行，报告与逐题评分永久保留。</p>
      </div>
      <el-button type="primary" @click="createAndOpen()">开始新面试</el-button>
    </div>

    <div v-if="!sessions.length" class="panel empty">
      还没有模拟面试记录。完成笔试后即可进入模拟面试，或直接开始一场。
    </div>

    <div v-for="s in sessions" :key="s.id" class="panel session-card" @click="open(s)">
      <div class="session-main">
        <div>
          <span class="eyebrow">#{{ s.id }}</span>
          <h3>
            {{ s.status === "ended" ? "已结束" : "进行中" }}
            <el-tag
              size="small"
              :type="s.status === 'ended' ? 'info' : 'success'"
              >{{ stageLabel[s.stage] ?? s.stage }}</el-tag
            >
          </h3>
          <p class="muted">
            {{ s.created_at?.slice(0, 16) ?? "—" }} · 蓝图
            {{ s.blueprint?.questions?.length ?? 0 }} 题 · 弱项：{{
              s.weak_areas.length ? s.weak_areas.join("、") : "无"
            }}
          </p>
        </div>
        <div v-if="reports[s.id]" class="session-score">
          <strong>{{ reports[s.id].score }}</strong><small> / 10</small>
        </div>
      </div>
      <div v-if="reports[s.id]" class="session-summary muted">
        {{ reports[s.id].summary_text }}
      </div>
    </div>
  </div>
</template>
<style scoped>
.session-card {
  cursor: pointer;
  margin-bottom: 12px;
  transition: box-shadow 0.2s;
}
.session-card:hover {
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.08);
}
.session-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.session-score strong {
  font-size: 28px;
  color: #1677ff;
}
.session-summary {
  margin-top: 8px;
  font-size: 13px;
  border-left: 3px solid #eef0f4;
  padding-left: 10px;
}
</style>
