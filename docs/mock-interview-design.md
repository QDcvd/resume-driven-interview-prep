# 模拟面试 + 动态出题 · 设计方案（定稿）

> 状态：已与需求方 grill 确认 · 版本 1.0
> 关联：`docs/PRD.md`（原产品规格，本方案为演进方向）
> 本方案为**纯增量**设计：不修改现有考试主流程的表与路由，新增独立模块。

---

## 1. 产品定位

从"静态题库 + 100 题笔试"演进为 **"简历 + 工作描述(JD) 驱动的动态出题 + 笔试 + 模拟面试"** 闭环：

```
强制上传简历+JD → 解析 → 调研 → 规划表确认 → 生成50题(纯客观)
→ 50题笔试(自动判分) → 即出分+弱项展示 → 模拟面试(面试官主导,弱项优先)
→ 逐题报告(打分/修正/推荐答法) + 总结报告（可回看）
```

## 2. 主流程（已确认）

1. **首次启动强制初始化**：上传简历 PDF + 输入工作描述(JD)。
2. **解析**：MarkItDown 本地转 Markdown；
   - 文本型 PDF 直接走 pdfminer 文本层（本地、免费）；
   - 扫描版（无文本层）→ 页面转图 → 走已有 LLM vision 识别（零额外依赖）；模型无视觉能力时退 `markitdown-paddleocr` 插件。
3. **LLM 结构化提取**：技能 / 项目 / 经历 / 教育 等字段。
4. **Agent 调研**：基于简历 + JD + 内置网搜工具检索 → 生成"题目规划表"（领域 × 难度分布）。
5. **规划表确认**：前端展示 → 用户确认/微调 → 才进入生成。
6. **生成 50 题（纯客观选择题）**：优先网搜真实真题（带 `source_url` 证据），LLM 按简历/JD 定制补足；生成即用、可修正（题库页可改/禁用）。
7. **50 题笔试**：60 分钟 / 无检查点 / 交卷即出分（客观自动判分，无 AI 等待）。
8. **结果页**：总分 + 各领域得分 + 弱项展示 →「进入模拟面试」按钮。
9. **模拟面试**：面试官主导问答流，6-8 题（开场 1 / 项目深挖 2-3 / 技术深度 2 / 行为题 1-2 / 收尾），每题追问 ≤1-2 层；**弱项领域优先提问**；用户可随时提前结束。
10. **面试结束** → 逐题报告 + 总结报告，落库可回看（面试历史页）。

## 3. 已确认决策清单

| # | 决策点 | 结论 |
|---|--------|------|
| 1 | 简历 | **必填**，启动强制上传 + 输入 JD |
| 2 | 出题质量 | 混合出题 + **生成即用可修正**（每题留 source_url，可改/禁用） |
| 3 | 50 题构成 | **Agent 调研出规划表**（领域×难度），用户确认后执行 |
| 4 | 题组生命周期 | **一次性生成永久使用**；重出题 = 重新初始化 |
| 5 | 练习模式 | **砍掉** quick/expression/mistakes/code，只留 50 题考试 + 面试 |
| 6 | 题型 | **50 题纯客观**；主观考察全部移到模拟面试 |
| 7 | 面试输出 | **逐题报告 + 总结**（打分 x/10 + 修正点 + 推荐答法 + 提炼原则） |
| 8 | 面试规模 | 6-8 题，构成固定，追问 ≤1-2 层 |
| 9 | 交互模式 | 面试官主导问答流，可提前结束 |
| 10 | 笔试→面试衔接 | 交卷即出分 + **弱项联动面试** |
| 11 | 行为题来源 | 内置模板（宝洁八大问等）+ 简历定制，不网搜 |
| 12 | 运行形态 | 调研/出题**全程异步 + 阶段进度 + 可重试** |
| 13 | PDF 解析 | **MarkItDown 本地**；扫描版走 LLM vision / paddleocr 插件 |
| 14 | 笔试参数 | 50 题 / 60 分钟 / 无检查点 / 交卷即出分 |
| 15 | 面试可重复 | 可反复进行 + **历史报告回看** |

## 4. 默认决定的次要细节（可后续调整）

- **笔试可重考**：同一套 50 题可多次创建考试（复用现有 `Attempt` 模型），弱项取最近一次。
- **重新初始化**：新 50 题替换活跃题库（旧的禁用），历史笔试/面试记录保留供回看。
- **对话页渲染**：面试官消息与报告用 Markdown 渲染（含推荐答法代码块），用户输入纯文本。
- **上下文管理**：对话滑动窗口 + 自动摘要；简历全文只在开场注入。
- **技术栈**：SSE 流式（`StreamingResponse`）；搜索走 **DeepSeek 原生服务端 web_search**（`web_search_20250305` 服务器工具，Anthropic 兼容端点 `{base}/anthropic/v1/messages`，DSH `web-search-deepseek` 同款方案，见 `backend/app/search.py`）：调研 Agent 单次调用内完成多次服务端搜索 + 输出规划表，无需 MCP/独立进程/抓爬；`source_url` 校验用返回的 url，结果不可用时回退 ddgs。

## 5. 架构与表结构（新增，不动现有表）

```
backend/app/
  resume_parser.py      # MarkItDown 本地解析 + 扫描版 LLM vision + 结构化提取
  research_agent.py     # 调研：简历+JD+网搜 → 规划表
  question_generator.py # 按规划表生成 50 题（复用 variants 证据核验管线）
  search.py             # 搜索：DeepSeek 原生 web_search（Anthropic 端点）→ 回退 ddgs
  interview_agent.py    # 面试：状态机 + tool calling + SSE 流式 + 报告生成
  interview_runner.py   # 会话循环 / 滑动窗口 / 摘要

frontend/src/
  views/Onboarding.vue      # 强制初始化：上传简历 + 输入 JD + 规划表确认
  views/Interview.vue       # 对话页（消息列表 + 底部输入框）
  views/InterviewHistory.vue # 历史报告回看
```

### 表结构

```sql
resumes(id, filename, raw_markdown, structured_json, source, created_at)
question_plans(id, resume_id, plan_json, status, created_at)   -- pending|confirmed|done
interview_sessions(id, attempt_id?, resume_id, status, started_at, ended_at)
interview_messages(id, session_id, role, content, created_at)
interview_reports(id, session_id, questions_json, summary_text, score, created_at)
```

## 6. 分阶段 MVP

| 阶段 | 内容 | 依赖 |
|------|------|------|
| P1 | 上传 + MarkItDown 解析 + LLM 结构化 → `resumes` 表 | 无 |
| P2 | 调研出规划表 + 确认 + 生成 50 题（复用 variants 搜索管线）→ `questions` | P1 |
| P3 | 笔试改造：50 题纯客观 / 60 分钟 / 即出分，砍练习模式入口 | P2 |
| P4 | 模拟面试后端：会话 + 消息 + SSE + tool calling + 弱项联动 + 报告生成 | P2 |
| P5 | 前端：对话页 + 规划表确认页 + 结果页按钮 + 面试历史页 | P3/P4 |

## 7. 关键风险与对策

| 风险 | 等级 | 对策 |
|------|------|------|
| 新链路强依赖 LLM（无 LLM 无法调研出题） | 高 | 初始化流程在未配置 LLM 时引导配置；运行时降级提示 |
| 扫描版 PDF 识别质量 | 中 | LLM vision 优先，paddleocr 兜底；解析结果页可人工修正 |
| 生成 50 题耗时/部分失败 | 中 | 异步 + 阶段进度 + 按题重试，失败题标记可单题补生成 |
| 面试上下文膨胀（简历+历史） | 中 | 滑动窗口 + 自动摘要 |
| 网搜可用性（DDG 限流/超时） | 中 | 复用现有 `DDGSException` 处理；tool 调用超时重试降级 |
| SSE 与现有 `BackgroundTasks` 并发 | 低 | `StreamingResponse` 独立处理，单用户无压力 |
| 上传安全（类型/大小/路径） | 低 | 校验扩展名 + 大小限制 + 受控存储目录 |

---

## 8. Agent 技术实现（已 grill 确认）

### 8.1 架构形态

- **自研轻量 tool-calling loop**（OpenAI SDK 原生 tool calling + 自写消息循环 + 状态机），**不引入 Agent 框架**（LangGraph/smolagents 均不用）。与现有 `grading.py`/`variants.py` 直接调 SDK 的风格一致，零新增框架依赖。
- **两个独立 Agent**：
  - **调研 Agent**（prompt=出题官）：`[search_tool]` + 结构化输出规划表。
  - **面试 Agent**（prompt=面试官）：`[bank_tool(可选)]`，**面试中不网搜**（零延迟、稳定）。
  - 共享 LLM client 与 search 实现；**报告生成**是面试结束时的一次结构化调用，不设独立 Agent。

### 8.2 对话循环与 SSE

两阶段流式（`StreamingResponse`），事件协议：

```jsonc
// POST /api/interview/sessions/{id}/messages
// SSE events:
{ "type": "thinking" }            // LLM 思考 / 调用工具阶段（不流 token）
{ "type": "tool", "name": "query_bank", "args": "..." }  // 工具执行开始（可重复）
{ "type": "token", "text": "..." } // 最终回复逐 token 流式
{ "type": "done", "message_id": 12, "action": "followup|next|end", "score": {...}|null, "stage": "...", "current_index": n }
{ "type": "status", "text": "..." } // 进度提示（如“正在生成报告”）
{ "type": "report", "id": 3 }        // 报告已生成（action=end 时）
{ "type": "error", "message": "..." }
```

实现要点：
- 逐轮应答一次流式调用，正文末尾带 `@@JSON@@` 元数据（`action`/`score`），runner 用 400 字符前瞻做流式裁剪，把元数据从客户端可见文本中剥离。
- DeepSeek 推理模型工具往返需回传 `reasoning_content`（否则 400），runner 已捕获并透传。
- 蓝图在 `POST /api/interview/sessions` 时同步生成（6-8 题），弱项领域取自最近一次已提交正式笔试的得分最低类别。
- 报告在 `action=end` 时随流生成，或由 `POST /api/interview/sessions/{id}/end`（提前结束）后台线程生成，前端轮询 `GET .../report`。

### 8.3 状态机（全量入 DB）

- `interview_sessions` 增加字段：`stage`(opening/ask/followup/closing/reporting)、`current_index`、`follow_up_count`、`question_plan_json`（6-8 题蓝图）。
- 追问层数显式落库；刷新/断线后按 DB 状态 + 消息重放恢复。
- 面试蓝图构成（已确认）：开场 1 + 项目深挖 2-3 + 技术深度 2 + 行为 1-2 + 收尾；弱项领域优先。

### 8.4 上下文管理

- 系统 prompt = 面试官人格 + 简历结构化摘要 + JD 要点 + 笔试弱项 + 行为模板。
- 对话历史 = 最近 N 轮（滑动窗口）+ 早期自动摘要；简历全文仅开场注入一次。
- 报告生成时从**全量 DB 消息**重建逐题上下文。

### 8.5 结构化输出（strict json_schema）

**规划表**（调研 Agent 输出）：
```json
{ "plan": [ { "domain": "mysql", "difficulty": "basic", "count": 15 }, ... ],
  "rationale": "调研依据摘要（网搜来源）" }
```
校验：count 合计 = 50，领域均来自 JD 技术栈/简历经历。

**逐题报告**（面试结束结构化调用，字段来自确认示例）：
```json
{ "summary": "整体总结", "overall_score": 8.0,
  "questions": [ { "question": "...", "user_answer": "...", "score": 7.5,
    "max_score": 10, "corrections": ["需要修正..."], "recommended_answer": "...",
    "principle": "提炼的原则..." } ] }
```

### 8.6 50 题生成容错

- 分块生成（每次 5-10 题）+ 每题证据核验（复用 `variants.py` 证据管线）。
- 失败题**单题重试 ≤2 次**，仍失败标记"待补"（题库页可见、可单题重新生成）。
- 异步阶段进度：`调研中 → 生成规划表 → 生成题目 x/50 → 完成`，可重试。

### 8.7 LLM 配置（简化版 DSH 模式）

- **全硬依赖**：无 LLM 完全不可用；初始化流程在未配置时引导去配置。
- 设置页新增「模型」分区，交互参照通用工具链的"设置 → 模型 → 添加自定义提供方"模式：
  - provider 行：显示名 + 已配置/缺失圆点 + 编辑/移除（删除需确认弹窗）。
  - 「添加自定义提供方」卡片字段：显示名 / BaseURL / API Key / 模型列表（OpenAI 兼容）。
  - 配置存 `app_settings`（动态生效）；`.env` 三变量作默认兜底。

### 8.8 调研预算与兜底

- **不设搜索预算**：调研 Agent 自主决定搜索次数。
- 硬兜底：单次调研绝对超时（如 5 分钟）+ 最大搜索次数上限（防挂死），超出即产出当前结果或报错可重试。

### 8.9 Token 成本参考（单用户本地，量级估算）

| 环节 | 量级 |
|------|------|
| 调研出规划表 | 搜索 3-8 次 + 1 次规划表生成 ≈ 数千 token |
| 生成 50 题 | 分块 5-10 次调用 ≈ 1-2 万 token（含检索证据） |
| 单场面试 6-8 题 | 每次回复 ≈ 1-3k token，全场约 1-2 万 token（含上下文） |
| 报告生成 | 一次调用 ≈ 3-5k token |

### 8.10 新增后端模块

```
backend/app/
  resume_parser.py      # MarkItDown + 扫描版 LLM vision + 结构化提取
  research_agent.py     # 调研：简历+JD+网搜 → 规划表
  question_generator.py # 按规划表分块生成 50 题（复用 variants 证据管线）
  interview_agent.py    # 面试：tool-calling loop + SSE + 报告
  llm_provider.py       # LLM 配置读写（app_settings）+ OpenAI client 工厂
```
