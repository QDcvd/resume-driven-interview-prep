<script setup lang="ts">
import { useRoute } from "vue-router";
const route = useRoute();
</script>
<template>
  <div class="shell">
    <aside v-if="!route.path.includes('/exam')" class="sidebar">
      <div class="brand">
        <span class="brand-mark">真</span>
        <div><b>面试备考中心</b><small>全栈工程师专项</small></div>
      </div>
      <el-menu router :default-active="route.path"
        ><el-menu-item index="/">今日任务</el-menu-item
        ><el-menu-item index="/onboarding">初始化笔试</el-menu-item
        ><el-menu-item index="/interviews">模拟面试</el-menu-item
        ><el-menu-item index="/mistakes">错题复习</el-menu-item
        ><el-menu-item index="/knowledge">知识卡片</el-menu-item
        ><el-menu-item index="/analytics">能力分析</el-menu-item
        ><el-menu-item index="/questions">题库管理</el-menu-item
        ><el-menu-item index="/settings">系统设置</el-menu-item></el-menu
      >
      <div class="sidebar-foot">本地单用户 · 数据仅存 SQLite</div>
    </aside>
    <main :class="['main', { 'exam-main': route.path.includes('/exam') }]">
      <router-view />
    </main>
  </div>
</template>
