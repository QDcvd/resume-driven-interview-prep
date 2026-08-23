<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../api/client";
import type { Ability } from "../types";
import AbilityChart from "../components/AbilityChart.vue";
const data = ref<Ability[]>([]);
onMounted(async () => {
  data.value = await api.abilities();
});
</script>
<template>
  <div class="page">
    <div class="page-head">
      <div>
        <span class="eyebrow">能力分析</span>
        <h1>总分之外，看到真正的短板</h1>
        <p class="muted">
          一级领域观察全局，答题量和趋势帮助判断分数是否可靠。
        </p>
      </div>
    </div>
    <div class="grid" style="grid-template-columns: 1.1fr 1fr">
      <div class="panel"><AbilityChart :data="data" /></div>
      <div class="panel">
        <el-table :data="data"
          ><el-table-column prop="name" label="领域" /><el-table-column
            prop="score"
            label="掌握度"
            ><template #default="s"
              ><el-progress
                :percentage="s.row.score" /></template></el-table-column
          ><el-table-column
            prop="answered"
            label="作答"
            width="70"
          /><el-table-column label="趋势" width="80"
            ><template #default="s"
              ><span
                :style="{ color: s.row.trend >= 0 ? '#23845b' : '#c4473a' }"
                >{{ s.row.trend >= 0 ? "↑" : "↓" }}
                {{ Math.abs(s.row.trend) }}</span
              ></template
            ></el-table-column
          ></el-table
        >
      </div>
    </div>
  </div>
</template>
