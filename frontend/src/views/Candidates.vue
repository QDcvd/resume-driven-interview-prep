<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../api/client";
import type { Candidate } from "../types";
const items = ref<Candidate[]>([]);
async function load() {
  items.value = await api.candidates();
}
onMounted(load);
async function decide(id: number, d: "approve" | "reject") {
  await api.reviewCandidate(id, d);
  await load();
}
</script>
<template>
  <div class="page">
    <div class="page-head">
      <div>
        <span class="eyebrow">AI 候选题</span>
        <h1>审核后才能进入正式题库</h1>
        <p class="muted">
          每道题都必须有可访问的检索证据；请核对题干、答案和解析。
        </p>
      </div>
      <el-tag type="warning">待审核 {{ items.length }}</el-tag>
    </div>
    <div v-if="!items.length" class="panel empty">暂无待审核候选题。</div>
    <div
      v-for="x in items"
      :key="x.id"
      class="panel"
      style="margin-bottom: 14px"
    >
      <div class="tag-row">
        <el-tag>{{ x.domain }}</el-tag
        ><el-tag effect="plain">{{ x.type }}</el-tag>
      </div>
      <p class="stem" style="margin: 14px 0">{{ x.stem }}</p>
      <el-alert type="info" :closable="false"
        ><template #title>证据：{{ x.evidence_title }}</template
        ><a :href="x.source_url" target="_blank">{{
          x.source_url
        }}</a></el-alert
      >
      <div class="toolbar" style="justify-content: flex-end; margin-top: 14px">
        <el-button type="danger" plain @click="decide(x.id, 'reject')"
          >拒绝</el-button
        ><el-button type="primary" @click="decide(x.id, 'approve')"
          >核验通过并启用</el-button
        >
      </div>
    </div>
  </div>
</template>
