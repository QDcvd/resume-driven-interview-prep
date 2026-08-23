<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { api } from "../api/client";
import type { ReviewCard } from "../types";

const categories = [
  { value: "php", label: "PHP / Laravel" },
  { value: "frontend", label: "Vue 3 / TypeScript" },
  { value: "database", label: "MySQL / 数据库" },
  { value: "redis_async", label: "Redis / 异步任务" },
  { value: "engineering", label: "微服务 / Nginx / 工程" },
  { value: "algorithms", label: "算法 / Python" },
  { value: "projects", label: "项目实战" },
];
const labels = Object.fromEntries(categories.map((item) => [item.value, item.label]));
const items = ref<ReviewCard[]>([]);
const total = ref(0);
const loading = ref(false);
const query = reactive({ q: "", domain: "", page: 1 });

async function load(reset = false) {
  if (reset) query.page = 1;
  loading.value = true;
  try {
    const result = await api.reviewCards(query);
    items.value = result.items;
    total.value = result.total;
  } finally {
    loading.value = false;
  }
}

onMounted(() => load());
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <span class="eyebrow">完整知识库</span>
        <h1>知识卡片</h1>
        <p class="muted">
          共 {{ total }} 张知识卡片；考前复习会从这里按本次试卷精选最多 15 张。
        </p>
      </div>
    </div>

    <div class="panel">
      <el-form inline>
        <el-form-item label="搜索">
          <el-input
            v-model="query.q"
            placeholder="标题、原理或易错点"
            clearable
            @keyup.enter="load(true)"
          />
        </el-form-item>
        <el-form-item label="领域">
          <el-select v-model="query.domain" clearable style="width: 220px">
            <el-option
              v-for="category in categories"
              :key="category.value"
              :label="category.label"
              :value="category.value"
            />
          </el-select>
        </el-form-item>
        <el-button type="primary" @click="load(true)">筛选</el-button>
      </el-form>
    </div>

    <div v-loading="loading" class="knowledge-grid">
      <article v-for="card in items" :key="card.id" class="panel review-card">
        <div class="knowledge-card-head">
          <h3>{{ card.title }}</h3>
          <el-tag size="small" effect="plain">
            {{ labels[card.domain] ?? card.domain }}
          </el-tag>
        </div>
        <p class="knowledge-card-content">{{ card.summary }}</p>
        <div v-if="card.pitfalls.length" class="pitfalls">
          <b>知识标签：</b>{{ card.pitfalls.join("；") }}
        </div>
      </article>
      <el-empty v-if="!loading && !items.length" description="没有匹配的知识卡片" />
    </div>

    <el-pagination
      v-if="total > 50"
      v-model:current-page="query.page"
      layout="prev, pager, next, total"
      :page-size="50"
      :total="total"
      @current-change="load()"
    />
  </div>
</template>

<style scoped>
.knowledge-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin: 18px 0;
}
.knowledge-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.knowledge-card-head h3 {
  margin: 0;
}
.knowledge-card-content {
  white-space: pre-line;
  line-height: 1.75;
}
@media (max-width: 900px) {
  .knowledge-grid {
    grid-template-columns: 1fr;
  }
}
</style>
