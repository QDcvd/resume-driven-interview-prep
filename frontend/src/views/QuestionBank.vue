<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "../api/client";
import type { Question } from "../types";
const categories = [
  { value: "php", label: "PHP / Laravel" },
  { value: "frontend", label: "Vue 3 / TypeScript" },
  { value: "database", label: "关系型数据库" },
  { value: "redis_async", label: "Redis / 异步任务" },
  { value: "engineering", label: "工程与安全" },
  { value: "algorithms", label: "算法 / Python" },
  { value: "projects", label: "项目与目标公司业务" },
];
const items = ref<Question[]>([]),
  total = ref(0),
  query = reactive({ q: "", domain: "", page: 1 }),
  editing = ref<Partial<Question>>(),
  file = ref<HTMLInputElement>();
async function load() {
  const r = await api.questions(query);
  items.value = r.items;
  total.value = r.total;
}
onMounted(load);
async function save() {
  await api.saveQuestion(editing.value!);
  editing.value = undefined;
  await load();
  ElMessage.success("题目已保存");
}
async function toggle(question: Question) {
  await api.saveQuestion(question);
  ElMessage.success(question.enabled ? "题目已启用" : "题目已停用");
}
function newQuestion() {
  editing.value = {
    type: "single",
    difficulty: "基础",
    domain: "php",
    tags: [],
    choices: "ABCD".split("").map((key) => ({ key, text: "" })),
    answer: "A",
    scoring_points: [],
    enabled: true,
  };
}
async function exp() {
  const b = await api.exportQuestions(),
    u = URL.createObjectURL(b),
    a = document.createElement("a");
  a.href = u;
  a.download = "questions.json";
  a.click();
  URL.revokeObjectURL(u);
}
async function imp(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (f) {
    await api.importQuestions(f);
    await load();
  }
}
</script>
<template>
  <div class="page">
    <div class="page-head">
      <div>
        <span class="eyebrow">核心题库</span>
        <h1>题库管理</h1>
        <p class="muted">
          共 {{ total }} 道人工核验题。修改后以 SQLite 为准，可用 JSON 迁移。
        </p>
      </div>
      <div class="toolbar">
        <input
          ref="file"
          type="file"
          accept=".json"
          hidden
          @change="imp"
        /><el-button @click="file?.click()">导入 JSON</el-button
        ><el-button @click="exp">导出 JSON</el-button
        ><el-button type="primary" @click="newQuestion">新增题目</el-button>
      </div>
    </div>
    <div class="panel">
      <el-form inline
        ><el-form-item label="搜索"
          ><el-input
            v-model="query.q"
            placeholder="题干、标签"
            clearable
            @keyup.enter="load" /></el-form-item
        ><el-form-item label="领域"
          ><el-select v-model="query.domain" clearable style="width: 190px"
            ><el-option
              v-for="x in categories"
              :key="x.value"
              :label="x.label"
              :value="x.value" /></el-select></el-form-item
        ><el-button type="primary" @click="load">筛选</el-button></el-form
      ><el-table :data="items"
        ><el-table-column prop="id" label="#" width="65" /><el-table-column
          prop="stem"
          label="题目"
          min-width="430"
          show-overflow-tooltip
        /><el-table-column
          prop="type"
          label="题型"
          width="110"
        /><el-table-column
          prop="domain"
          label="领域"
          width="160"
        /><el-table-column
          prop="difficulty"
          label="难度"
          width="90"
        /><el-table-column label="启用" width="90"
          ><template #default="s"
            ><el-switch
              v-model="s.row.enabled"
              @change="toggle(s.row)" /></template></el-table-column
        ><el-table-column label="操作" width="90"
          ><template #default="s"
            ><el-button link type="primary" @click="editing = { ...s.row }"
              >编辑</el-button
            ></template
          ></el-table-column
        ></el-table
      >
    </div>
    <el-dialog
      v-model="editing"
      title="编辑题目"
      width="720"
      @closed="editing = undefined"
      ><el-form v-if="editing" label-position="top"
        ><el-form-item label="题干"
          ><el-input v-model="editing.stem" type="textarea" :rows="4"
        /></el-form-item>
        <div class="grid" style="grid-template-columns: 1fr 1fr">
          <el-form-item label="题型"
            ><el-select v-model="editing.type"
              ><el-option
                v-for="x in [
                  'single',
                  'multiple',
                  'short',
                  'project',
                  'system_design',
                ]"
                :key="x"
                :value="x" /></el-select></el-form-item
          ><el-form-item label="领域"
            ><el-select v-model="editing.domain"
              ><el-option
                v-for="x in categories"
                :key="x.value"
                :label="x.label"
                :value="x.value" /></el-select
          ></el-form-item>
        </div>
        <template
          v-if="editing.type === 'single' || editing.type === 'multiple'"
        >
          <el-form-item label="选项">
            <el-input
              v-for="choice in editing.choices"
              :key="choice.key"
              v-model="choice.text"
            >
              <template #prepend>{{ choice.key }}</template>
            </el-input>
          </el-form-item>
          <el-form-item label="正确答案"
            ><el-select v-model="editing.answer"
              ><el-option
                v-for="letter in ['A', 'B', 'C', 'D']"
                :key="letter"
                :value="letter" /></el-select
          ></el-form-item>
        </template>
        <el-form-item v-else label="评分点">
          <el-select
            v-model="editing.scoring_points"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="输入评分点后回车"
          />
        </el-form-item>
        <el-form-item label="解析"
          ><el-input
            v-model="editing.explanation"
            type="textarea"
            :rows="4" /></el-form-item
        ><el-form-item label="来源 URL"
          ><el-input v-model="editing.source_url" /></el-form-item></el-form
      ><template #footer
        ><el-button @click="editing = undefined">取消</el-button
        ><el-button type="primary" @click="save">保存</el-button></template
      ></el-dialog
    >
  </div>
</template>
