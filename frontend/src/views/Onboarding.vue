<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { api } from "../api/client";
import type { QuestionPlan, ResumeData } from "../types";

const router = useRouter();
const uploading = ref(false);
const creating = ref(false);
const confirming = ref(false);
const resume = ref<ResumeData | null>(null);
const plan = ref<QuestionPlan | null>(null);
const jd = ref("");
const file = ref<File | null>(null);
const fileInput = ref<HTMLInputElement>();

const needUpload = computed(() => !resume.value || resume.value.status !== "parsed");
const step = computed(() => {
  if (!plan.value) return "idle";
  if (plan.value.status === "pending") return "researching";
  if (plan.value.status === "confirming") return "confirming";
  if (plan.value.status === "generating") return "generating";
  if (plan.value.status === "done") return "ready";
  return "failed";
});
const totalCount = computed(
  () => plan.value?.plan?.domains?.reduce((s, d) => s + d.count, 0) ?? 0,
);

onMounted(async () => {
  resume.value = await api.latestResume().catch(() => null);
  if (resume.value && resume.value.status === "parsed") {
    jd.value = resume.value.job_description ?? "";
    await refreshPlan();
  }
});

async function refreshPlan() {
  if (!resume.value) return;
  const existing = await api.resumePlan(resume.value.id).catch(() => null);
  if (existing && existing.status !== "failed") {
    plan.value = existing;
    if (!["done", "failed"].includes(existing.status)) poll(existing.id);
    return;
  }
  try {
    const created = await api.createPlan(resume.value.id);
    plan.value = created;
    poll(created.id);
  } catch (e) {
    plan.value = null;
    ElMessage.error(errorText(e, "生成规划表失败"));
  }
}

let timer: ReturnType<typeof setInterval> | undefined;
function poll(planId: number) {
  clearInterval(timer);
  timer = setInterval(async () => {
    try {
      const p = await api.getPlan(planId);
      plan.value = p;
      if (["done", "failed"].includes(p.status)) clearInterval(timer);
    } catch {
      clearInterval(timer);
    }
  }, 3000);
}

async function onPickFile(event: Event) {
  const input = event.target as HTMLInputElement;
  file.value = input.files?.[0] ?? null;
}

async function upload() {
  if (!file.value) return ElMessage.warning("请选择 PDF 简历文件");
  if (!jd.value.trim()) return ElMessage.warning("请填写目标岗位描述（JD）");
  uploading.value = true;
  try {
    resume.value = await api.uploadResume(file.value, jd.value.trim());
    ElMessage.success("简历解析完成");
    await refreshPlan();
  } catch (e) {
    ElMessage.error(errorText(e, "简历解析失败"));
  } finally {
    uploading.value = false;
  }
}

async function confirm() {
  if (!plan.value) return;
  confirming.value = true;
  try {
    const p = await api.confirmPlan(plan.value.id);
    plan.value = p;
    poll(p.id);
  } catch (e) {
    ElMessage.error(errorText(e, "确认失败"));
  } finally {
    confirming.value = false;
  }
}

async function retry() {
  if (!plan.value) return;
  try {
    const p = await api.retryPlan(plan.value.id);
    plan.value = p;
    poll(p.id);
  } catch (e) {
    ElMessage.error(errorText(e, "重试失败"));
  }
}

async function startExam() {
  const a = await api.createAttempt("formal");
  router.push(`/attempts/${a.id}/review`);
}

function errorText(e: unknown, fallback: string) {
  const err = e as { response?: { data?: { detail?: string } } };
  return err?.response?.data?.detail ?? fallback;
}

const difficultyLabel: Record<string, string> = {
  basic: "基础",
  practical: "实战",
  deep: "深挖",
};
</script>
<template>
  <div class="page">
    <div class="page-head">
      <div>
        <span class="eyebrow">ONBOARDING</span>
        <h1>初始化笔试</h1>
        <p class="muted">
          上传简历 + 填写岗位 JD，系统为你生成 50 道客观选择题的笔试规划并自动出题。
        </p>
      </div>
      <el-button plain @click="$router.push('/interviews')"
        >模拟面试入口</el-button
      >
    </div>

    <!-- 第 1 步：上传简历 -->
    <div v-if="needUpload" class="panel" style="max-width: 760px">
      <h2>1. 上传简历与岗位描述</h2>
      <el-form label-position="top">
        <el-form-item label="PDF 简历">
          <input
            ref="fileInput"
            type="file"
            accept="application/pdf"
            class="file-input"
            @change="onPickFile"
          />
          <span class="muted" v-if="file">已选择：{{ file.name }}</span>
        </el-form-item>
        <el-form-item label="目标岗位 JD（必填）">
          <el-input
            v-model="jd"
            type="textarea"
            :rows="4"
            placeholder="例如：PHP 后端开发工程师，要求熟练掌握 PHP、MySQL、Redis，熟悉消息队列与实时通信……"
          />
        </el-form-item>
        <el-button type="primary" :loading="uploading" @click="upload"
          >解析简历并生成规划</el-button
        >
      </el-form>
    </div>

    <!-- 第 2 步：调研中 -->
    <div
      v-else-if="step === 'researching'"
      class="panel"
      style="max-width: 760px"
    >
      <h2>正在调研岗位要求</h2>
      <p class="muted">
        调研 Agent 正在结合简历与 JD 搜索真实面试题并制定 50 题规划表…
      </p>
      <el-progress :percentage="40" :indeterminate="true" style="margin: 12px 0" />
    </div>

    <!-- 第 3 步：确认规划表 -->
    <div v-else-if="step === 'confirming'" class="panel" style="max-width: 760px">
      <h2>2. 确认题目规划表</h2>
      <p class="muted">
        {{ plan?.plan?.rationale || "调研 Agent 给出的领域分布" }}
      </p>
      <el-table :data="plan?.plan?.domains ?? []" size="small" style="margin: 12px 0">
        <el-table-column prop="domain" label="领域" width="180" />
        <el-table-column prop="count" label="题量" width="90" />
        <el-table-column label="难度分布">
          <template #default="{ row }">
            <span v-for="(n, key) in row.difficulty" :key="key" class="tag-row">
              <el-tag size="small" effect="plain">
                {{ difficultyLabel[key] }} {{ n }}
              </el-tag>
            </span>
          </template>
        </el-table-column>
      </el-table>
      <div class="tag-row" style="margin-bottom: 14px">
        <el-tag type="info">合计 {{ totalCount }} 题</el-tag>
        <el-tag type="warning">全部客观选择题</el-tag>
      </div>
      <el-button type="primary" :loading="confirming" @click="confirm"
        >确认并生成 50 题</el-button
      >
      <el-button @click="retry">重新调研</el-button>
    </div>

    <!-- 第 4 步：生成中 -->
    <div
      v-else-if="step === 'generating'"
      class="panel"
      style="max-width: 760px"
    >
      <h2>正在生成题目</h2>
      <p class="muted">
        已生成 {{ plan?.generated_count ?? 0 }} / {{ plan?.total ?? 50 }} 题，请稍候…
      </p>
      <el-progress
        :percentage="
          Math.round(((plan?.generated_count ?? 0) / Math.max(1, plan?.total ?? 50)) * 100)
        "
        style="margin: 12px 0"
      />
    </div>

    <!-- 第 5 步：就绪 -->
    <div v-else-if="step === 'ready'" class="panel" style="max-width: 760px">
      <h2>题库就绪</h2>
      <p class="muted">
        已生成 {{ plan?.total ?? 50 }} 道客观选择题（60 分钟，满分 100，交卷即出分）。
      </p>
      <div class="tag-row" style="margin-bottom: 14px">
        <el-tag
          v-for="d in plan?.plan?.domains ?? []"
          :key="d.domain"
          effect="plain"
          >{{ d.domain }} {{ d.count }}</el-tag
        >
      </div>
      <el-button type="primary" size="large" @click="startExam"
        >进入 50 题笔试</el-button
      >
      <el-button size="large" @click="$router.push('/interviews')"
        >先做模拟面试</el-button
      >
    </div>

    <!-- 失败 -->
    <div v-else class="panel" style="max-width: 760px">
      <h2>初始化失败</h2>
      <el-alert
        :closable="false"
        type="error"
        :title="plan?.error || '规划表生成失败'"
        show-icon
      />
      <el-button style="margin-top: 14px" @click="retry">重试</el-button>
      <el-button style="margin-top: 14px" @click="needUpload = true">
        更换简历
      </el-button>
    </div>
  </div>
</template>
<style scoped>
.file-input {
  display: block;
  margin-bottom: 6px;
}
</style>
