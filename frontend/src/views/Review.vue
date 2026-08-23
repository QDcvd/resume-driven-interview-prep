<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "../api/client";
import type { ReviewResult } from "../types";
import AbilityChart from "../components/AbilityChart.vue";

const route = useRoute();
const result = ref<ReviewResult>();
const starting = ref(false);
const gradingStarted = ref(false);

async function load() {
  result.value = await api.review(Number(route.params.id));
}

onMounted(load);

async function grade() {
  starting.value = true;
  try {
    const response = await api.startGrading(Number(route.params.id));
    gradingStarted.value = response.pending > 0;
    ElMessage.success(
      response.pending
        ? `已开始处理 ${response.pending} 道待评分题；结果会写入 SQLite，请稍后手动刷新。`
        : "当前没有待评分题。",
    );
  } finally {
    starting.value = false;
  }
}

async function stop() {
  await api.stopGrading("manual");
  gradingStarted.value = false;
  ElMessage.info("已发送停止信号；已完成的评分会保留。");
}

async function requeue(includeCompleted: boolean) {
  if (includeCompleted) {
    try {
      await ElMessageBox.confirm(
        "这会为所有已完成的主观题创建新的评分版本，历史评分仍会保留。",
        "确认重新评分",
        {
          type: "warning",
          confirmButtonText: "重新评分",
          cancelButtonText: "取消",
        },
      );
    } catch {
      return;
    }
  }
  const response = await api.requeueGrading(
    Number(route.params.id),
    includeCompleted,
  );
  await load();
  ElMessage.success(`已将 ${response.requeued} 道题恢复为待评分。`);
}

async function override(questionId: number) {
  const scoreInput = await ElMessageBox.prompt("请输入 0-10 分", "人工改分", {
    inputPattern: /^(10(?:\.0+)?|[0-9](?:\.\d+)?)$/,
    inputErrorMessage: "请输入 0-10",
  });
  const reasonInput = await ElMessageBox.prompt("请输入改分理由", "人工改分");
  await api.overrideGrade(
    Number(route.params.id),
    questionId,
    Number(scoreInput.value),
    reasonInput.value,
  );
  await load();
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <span class="eyebrow">考试复盘</span>
        <h1>先看结论，再修正表达</h1>
        <p class="muted">
          客观题即时判分；主观答案先保存到 SQLite，需要时手动启动批量评分。
        </p>
      </div>
      <div class="toolbar">
        <el-button @click="load">刷新评分结果</el-button
        ><el-button @click="$router.push('/')">返回首页</el-button>
      </div>
    </div>
    <div class="grid grid-3">
      <div class="panel">
        <span class="muted">当前总分</span>
        <div class="score-big">{{ result?.total_score ?? "—" }}</div>
      </div>
      <div class="panel">
        <span class="muted">客观题得分</span>
        <div class="score-big">{{ result?.objective_score ?? "—" }}</div>
      </div>
      <div class="panel">
        <span class="muted">待 AI 评分</span>
        <div class="score-big">{{ result?.pending_count ?? 0 }}</div>
        <div class="grading-actions">
          <el-button
            v-if="result?.pending_count"
            type="primary"
            :loading="starting"
            @click="grade"
            >评分全部待处理题</el-button
          >
          <el-button v-if="gradingStarted" type="warning" plain @click="stop"
            >停止本批评分</el-button
          >
          <div class="grading-secondary">
            <el-button @click="requeue(false)">重试失败任务</el-button>
            <el-button v-if="result?.grades.length" @click="requeue(true)"
              >重新评分已完成题</el-button
            >
          </div>
        </div>
      </div>
    </div>
    <div class="grid review-grid">
      <div class="panel">
        <h3>能力分布</h3>
        <AbilityChart :data="result?.domain_scores ?? []" />
      </div>
      <div class="panel">
        <h3>逐题反馈</h3>
        <div
          v-for="item in result?.grades"
          :key="item.question_id"
          class="grade-feedback"
        >
          <div class="feedback-head">
            <div class="feedback-title">
              <div class="tag-row">
                <b>第 {{ item.position }} 题</b>
                <el-tag effect="plain">{{ item.domain }}</el-tag>
              </div>
              <p class="feedback-stem">{{ item.question_stem }}</p>
            </div>
            <div class="feedback-score">
              <el-tag>{{ item.score }} / {{ item.max_score }}</el-tag>
              <el-button
                link
                type="primary"
                @click="override(item.question_id)"
                >人工改分</el-button
              >
            </div>
          </div>
          <div class="candidate-answer">
            <b>我的回答</b>
            <p>
              {{
                Array.isArray(item.candidate_answer)
                  ? item.candidate_answer.join("、")
                  : item.candidate_answer || "未作答"
              }}
            </p>
          </div>
          <p v-if="item.hits.length" class="feedback-positive">
            命中：{{ item.hits.join("；") }}
          </p>
          <p v-if="item.omissions.length" class="muted">
            遗漏：{{ item.omissions.join("；") }}
          </p>
          <p v-if="item.errors.length" class="feedback-error">
            错误：{{ item.errors.join("；") }}
          </p>
          <el-collapse v-if="item.improved_answer"
            ><el-collapse-item title="更适合面试的回答"
              ><p style="line-height: 1.8">
                {{ item.improved_answer }}
              </p></el-collapse-item
            ></el-collapse
          >
        </div>
      </div>
    </div>
  </div>
</template>
