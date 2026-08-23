# 基于简历的面试考试系统 · Resume-Driven Interview Prep

面向技术面试的本地单用户考试系统。上传简历 + 填写岗位 JD，系统结合两者生成 **50 道客观选择题**的正式笔试，交卷即出分；笔试后进入 **LLM 模拟面试**，即时评分并输出逐题报告。全流程由 AI 驱动，无人工题库。

## 核心流程

1. **初始化**：上传 PDF 简历 + 填写岗位 JD → 调研 Agent（原生 web 搜索）生成 50 题规划表 → 确认后一次性生成题目。
2. **笔试**：50 道客观选择题，60 分钟限时，无检查点，交卷即出分，成绩联动弱项分析。
3. **复习**：错题复习、知识卡片、能力分析，按岗位权重与复习间隔安排练习。
4. **模拟面试**：笔试后按弱项进入，6-8 问（开场 / 项目 / 技术 / 行为 / 收尾），支持追问、提前结束，即时评分 + 逐题评估报告，可重复进行并历史回看。

## Windows / Ubuntu 安装

需要 Python 3.11+、[uv](https://docs.astral.sh/uv/) 与 Node.js 20+。

```bash
python install.py
```

安装脚本会创建 `.env`、安装 Python/前端依赖并构建 Vue。模型配置可稍后填写。

本项目不使用 Docker。Windows 和 Ubuntu 都使用同一套 `uv` 安装与启动方式；安装和启动严格分开，日常启动不会改动依赖。

## 启动

```bash
uv run python start.py
```

服务默认只监听 `127.0.0.1:8000` 并自动打开浏览器。启动过程不会安装或更新依赖。首次启动会自动执行 SQLite 迁移并备份现有数据库（最多保留最近 10 份）。

## 大模型配置

复制生成的 `.env` 后填写兼容 OpenAI 接口的配置：

```dotenv
LLM_API_KEY=你的密钥
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=模型名称
```

也可在 **系统设置 → 模型提供方** 页面配置自定义提供方（显示名 / BaseURL / API Key / 模型），动态生效。所有 AI 功能（出题 / 调研 / 评分 / 面试）都硬依赖 LLM；未配置时界面会引导去配置。

调研 Agent 使用 DeepSeek 原生 web_search 检索真实面试题作为证据；面试追问阶段会查询题库辅助。

## 开发

```bash
uv run python dev.py        # 开发后端（自动重载）
cd frontend && npm run dev  # 前端 Vite（/api 代理到 127.0.0.1:8000）
```

前端构建：`cd frontend && npm run build`（vue-tsc 类型检查 + vite 构建，产物由后端直接托管）。

完整产品规格见 [docs/PRD.md](docs/PRD.md)，模拟面试设计见 [docs/mock-interview-design.md](docs/mock-interview-design.md)。
