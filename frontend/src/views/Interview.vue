<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { api } from "../api/client";
import type {
  InterviewMessageItem,
  InterviewReportItem,
  InterviewSession,
} from "../types";

const route = useRoute();
const router = useRouter();
const sessionId = Number(route.params.id);
const session = ref<InterviewSession | null>(null);
const messages = ref<InterviewMessageItem[]>([]);
const input = ref("");
const busy = ref(false);
const thinking = ref(false);
const toolNote = ref("");
const statusNote = ref("");
const streaming = ref<{ role: string; content: string } | null>(null);
const report = ref<InterviewReportItem | null>(null);
const loadingReport = ref(false);
const listEl = ref<HTMLElement>();

const blueprint = computed(() => session.value?.blueprint?.questions ?? []);
const ended = computed(() => session.value?.status === "ended");
const weakLabel: Record<string, string> = {
  php: "PHP",
  laravel: "Laravel",
  mysql: "MySQL",
  database: "数据库",
  redis: "Redis",
  redis_async: "Redis/异步",
  frontend: "前端",
  websocket: "WebSocket",
  "message-queue": "消息队列",
};

onMounted(load);

async function load() {
  try {
    const d = await api.interviewDetail(sessionId);
    session.value = d;
    messages.value = d.messages ?? [];
    if (session.value?.status === "ended") {
      const r = await api.interviewReport(sessionId).catch(() => null);
      report.value = r;
    }
  } catch (e) {
    ElMessage.error("面试会话加载失败");
  }
  scroll();
}

function scroll() {
  nextTick(() => listEl.value?.scrollTo({ top: listEl.value.scrollHeight }));
}

function renderMarkdown(text: string) {
  const esc = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return esc
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br/>");
}

async function send() {
  const text = input.value.trim();
  if (!text || busy.value) return;
  if (session.value?.status !== "active") {
    return ElMessage.warning("面试已结束");
  }
  input.value = "";
  busy.value = true;
  thinking.value = true;
  toolNote.value = "";
  statusNote.value = "";
  messages.value.push({ id: -1, role: "user", content: text, created_at: "" });
  streaming.value = { role: "interviewer", content: "" };
  scroll();
  try {
    await streamMessages(text);
  } catch (e) {
    ElMessage.error("网络错误，请重试");
    if (streaming.value && !streaming.value.content) streaming.value = null;
  } finally {
    busy.value = false;
    thinking.value = false;
  }
}

async function streamMessages(text: string) {
  const resp = await fetch(`/api/interview/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: text }),
  });
  if (!resp.ok || !resp.body) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error(detail.detail || "请求失败");
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx = buffer.indexOf("\n\n");
    while (idx >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (line) handleEvent(JSON.parse(line.slice(6)));
      idx = buffer.indexOf("\n\n");
    }
  }
}

function handleEvent(ev: {
  type: string;
  text?: string;
  name?: string;
  score?: { score?: number; max_score?: number; comment?: string } | null;
  action?: string;
  message_id?: number;
  message?: string;
}) {
  if (ev.type === "thinking") {
    thinking.value = true;
  } else if (ev.type === "tool") {
    toolNote.value = `正在查询题库（${ev.name}）`;
  } else if (ev.type === "token") {
    thinking.value = false;
    if (!streaming.value) streaming.value = { role: "interviewer", content: "" };
    streaming.value.content += ev.text ?? "";
    scroll();
  } else if (ev.type === "done") {
    thinking.value = false;
    toolNote.value = "";
    const content = streaming.value?.content ?? "";
    const score = ev.score;
    const final = score
      ? `${content}\n\n> 即时评分：**${score.score}/${score.max_score}** ${score.comment ? "· " + score.comment : ""}`
      : content;
    if (streaming.value) {
      streaming.value = null;
      messages.value.push({
        id: ev.message_id ?? 0,
        role: "interviewer",
        content: final,
        created_at: "",
      });
    }
    if (session.value) {
      session.value.stage = ev.action === "end" ? "closing" : "ask";
    }
    if (ev.action === "end") {
      statusNote.value = "面试已结束，正在生成评估报告…";
      pollReport();
    }
    scroll();
  } else if (ev.type === "status") {
    statusNote.value = ev.message ?? "";
  } else if (ev.type === "report") {
    pollReport();
  } else if (ev.type === "error") {
    thinking.value = false;
    ElMessage.error(ev.message ?? "发生错误");
    if (streaming.value && !streaming.value.content) streaming.value = null;
  }
}

async function pollReport(attempt = 0) {
  try {
    const r = await api.interviewReport(sessionId);
    report.value = r;
    if (session.value) session.value.status = "ended";
    statusNote.value = "";
    loadingReport.value = false;
  } catch {
    if (attempt < 20) {
      setTimeout(() => pollReport(attempt + 1), 3000);
    } else {
      loadingReport.value = false;
      ElMessage.error("报告生成较慢，请稍后刷新查看");
    }
  }
}

async function endNow() {
  if (session.value?.status !== "active" || busy.value) return;
  busy.value = true;
  loadingReport.value = true;
  statusNote.value = "正在结束面试并生成报告…";
  try {
    await api.endInterview(sessionId);
    if (session.value) session.value.stage = "closing";
    pollReport();
  } catch (e) {
    ElMessage.error("结束失败");
    busy.value = false;
    loadingReport.value = false;
    statusNote.value = "";
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div class="page interview-page">
    <div class="page-head">
      <div>
        <span class="eyebrow">MOCK INTERVIEW</span>
        <h1>模拟面试</h1>
        <p class="muted">
          <template v-if="session">
            笔试弱项：{{
              session.weak_areas.length
                ? session.weak_areas.map((w) => weakLabel[w] ?? w).join("、")
                : "暂无"
            }}
          </template>
        </p>
      </div>
      <div>
        <el-button plain @click="$router.push('/interviews')"
          >历史回看</el-button
        >
        <el-button
          v-if="session?.status === 'active'"
          type="danger"
          plain
          :disabled="busy"
          @click="endNow"
          >结束面试</el-button
        >
      </div>
    </div>

    <div class="interview-layout">
      <aside class="blueprint panel">
        <h3>面试蓝图</h3>
        <ol>
          <li
            v-for="(q, i) in blueprint"
            :key="i"
            :class="{ current: session && session.current_index === i }"
          >
            <small class="type-chip">{{ q.type }}</small>
            <span>{{ q.question }}</span>
          </li>
        </ol>
      </aside>

      <div class="chat-panel panel">
        <div ref="listEl" class="chat-list">
          <div v-if="!messages.length && !streaming" class="chat-empty muted">
            面试官会先开场提问，请在下方输入回答。
          </div>
          <div
            v-for="(m, i) in messages"
            :key="i"
            :class="['msg', m.role === 'user' ? 'user' : 'interviewer']"
          >
            <div class="bubble" v-html="renderMarkdown(m.content)" />
          </div>
          <div v-if="streaming" class="msg interviewer">
            <div class="bubble" v-html="renderMarkdown(streaming.content || '…')" />
          </div>
          <div v-if="thinking && !streaming" class="msg interviewer">
            <div class="bubble thinking">面试官正在思考…</div>
          </div>
          <div v-if="toolNote" class="tool-note">{{ toolNote }}</div>
          <div v-if="statusNote" class="tool-note warn">{{ statusNote }}</div>
        </div>

        <div v-if="report" class="report panel">
          <h2>面试评估报告</h2>
          <div class="report-score">
            <div class="score-ring">
              <strong>{{ report.score }}</strong><small>/ 10</small>
            </div>
            <p class="muted">{{ report.summary_text }}</p>
          </div>
          <el-collapse>
            <el-collapse-item
              v-for="(q, i) in report.questions"
              :key="i"
              :title="`${i + 1}. ${q.question}（${q.score}/${q.max_score}）`"
            >
              <p><b>你的回答：</b>{{ q.user_answer }}</p>
              <p v-if="q.corrections?.length">
                <b>改进建议：</b>
                <ul><li v-for="(c, j) in q.corrections" :key="j">{{ c }}</li></ul>
              </p>
              <p v-if="q.recommended_answer">
                <b>参考答案要点：</b>{{ q.recommended_answer }}
              </p>
              <p v-if="q.principle"><b>考察原则：</b>{{ q.principle }}</p>
            </el-collapse-item>
          </el-collapse>
        </div>

        <div v-if="session?.status === 'active'" class="chat-input">
          <el-input
            v-model="input"
            type="textarea"
            :rows="2"
            resize="none"
            placeholder="输入你的回答…（Enter 发送，Shift+Enter 换行）"
            @keydown.enter.exact.prevent="send"
          />
          <el-button type="primary" :loading="busy" :disabled="!input.trim()" @click="send"
            >发送</el-button
          >
        </div>
      </div>
    </div>
  </div>
</template>
<style scoped>
.interview-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
  margin-top: 16px;
}
.blueprint h3 {
  margin: 0 0 10px;
  font-size: 14px;
}
.blueprint ol {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.6;
  color: #666;
}
.blueprint li.current {
  color: #1677ff;
  font-weight: 600;
}
.type-chip {
  display: inline-block;
  background: #eef2ff;
  color: #4f6ef2;
  border-radius: 4px;
  padding: 0 4px;
  margin-right: 4px;
  font-size: 10px;
}
.chat-panel {
  display: flex;
  flex-direction: column;
  min-height: 70vh;
}
.chat-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  max-height: 62vh;
}
.chat-empty {
  text-align: center;
  padding: 40px 0;
}
.msg {
  display: flex;
  margin-bottom: 12px;
}
.msg.user {
  justify-content: flex-end;
}
.bubble {
  max-width: 76%;
  padding: 10px 14px;
  border-radius: 12px;
  background: #f4f6fa;
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 1.7;
}
.msg.user .bubble {
  background: #1677ff;
  color: #fff;
}
.msg.interviewer .bubble {
  background: #f4f6fa;
}
.bubble.thinking {
  color: #999;
  font-style: italic;
}
.tool-note {
  font-size: 12px;
  color: #888;
  margin: 4px 12px;
}
.tool-note.warn {
  color: #d46b08;
}
.chat-input {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid #eef0f4;
}
.chat-input .el-input {
  flex: 1;
}
.report {
  margin-top: 12px;
}
.report-score {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 10px;
}
.score-ring {
  text-align: center;
}
.score-ring strong {
  font-size: 34px;
  color: #1677ff;
}
.report-score p {
  margin: 0;
}
</style>
