<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "../api/client";
import type { LlmProvider, Settings } from "../types";
const form = ref<Settings>();
const provider = ref<LlmProvider>({
  display_name: "",
  base_url: "",
  api_key: "",
  model: "",
  configured: false,
  active: false,
});
const savingProvider = ref(false);
onMounted(async () => {
  form.value = await api.settings();
  provider.value = await api.llmProvider().catch(() => provider.value);
});
async function save() {
  form.value = await api.saveSettings(form.value!);
  ElMessage.success("设置已保存");
}
async function backup() {
  await api.backup();
  ElMessage.success("已创建数据库备份");
}
async function saveProvider() {
  if (!provider.value.display_name.trim() || !provider.value.base_url.trim()) {
    return ElMessage.warning("请填写提供方名称与 API 地址");
  }
  savingProvider.value = true;
  try {
    provider.value = await api.saveLlmProvider({
      display_name: provider.value.display_name.trim(),
      base_url: provider.value.base_url.trim(),
      api_key: provider.value.api_key.trim(),
      model: provider.value.model.trim(),
    });
    ElMessage.success("模型提供方已保存并立即生效");
  } catch (e) {
    const err = e as { response?: { data?: { detail?: string } } };
    ElMessage.error(err?.response?.data?.detail ?? "保存失败");
  } finally {
    savingProvider.value = false;
  }
}
</script>
<template>
  <div class="page">
    <div class="page-head">
      <div>
        <span class="eyebrow">本地配置</span>
        <h1>系统设置</h1>
        <p class="muted">
          模型提供方密钥仅在浏览器会话内保存到服务端，不会在界面回显明文。
        </p>
      </div>
      <el-button @click="backup">立即备份 SQLite</el-button>
    </div>

    <div class="panel" style="max-width: 720px; margin-bottom: 16px">
      <h2 style="margin-top: 0">模型提供方（LLM）</h2>
      <el-alert
        :type="provider.configured ? 'success' : 'warning'"
        :closable="false"
        :title="
          provider.configured
            ? `已配置：${provider.display_name}（${provider.model}）`
            : '未配置模型。所有 AI 功能（出题/评分/面试）都需要模型提供方。'
        "
        show-icon
      />
      <el-form label-position="top" style="margin-top: 14px">
        <el-form-item label="提供方名称">
          <el-input v-model="provider.display_name" placeholder="如 DeepSeek" />
        </el-form-item>
        <el-form-item label="API 地址">
          <el-input
            v-model="provider.base_url"
            placeholder="https://api.deepseek.com"
          />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="provider.api_key"
            type="password"
            show-password
            placeholder="sk-…（已保存的密钥不会回显，留空则沿用）"
          />
        </el-form-item>
        <el-form-item label="模型名">
          <el-input v-model="provider.model" placeholder="deepseek-v4-flash" />
        </el-form-item>
        <el-button
          type="primary"
          :loading="savingProvider"
          @click="saveProvider"
          >保存并应用</el-button
        >
      </el-form>
    </div>

    <div class="panel" style="max-width: 720px">
      <h2 style="margin-top: 0">复习偏好</h2>
      <el-form v-if="form" label-position="top"
        ><el-form-item label="面试日期"
          ><el-date-picker
            v-model="form.interview_date"
            value-format="YYYY-MM-DD" /></el-form-item
        ><el-form-item label="模型状态"
          ><el-alert
            :type="form.llm_configured ? 'success' : 'warning'"
            :closable="false"
            :title="
              form.llm_configured
                ? `已配置：${form.llm_model}`
                : '尚未配置模型，答案会安全保存为待评分'
            " /></el-form-item
        ><el-form-item label="批量评分并发数"
          ><el-input-number
            v-model="form.grading_concurrency"
            :min="1"
            :max="5" /></el-form-item
        ><el-form-item label="单次最大评分题数"
          ><el-input-number
            v-model="form.max_grading_batch"
            :min="1"
            :max="100" /></el-form-item
        ><el-form-item label="自动保存延迟（毫秒）"
          ><el-input-number
            v-model="form.autosave_delay_ms"
            :min="300"
            :max="5000"
            :step="100" /></el-form-item
        ><el-button type="primary" @click="save">保存设置</el-button></el-form
      >
    </div>
  </div>
</template>
