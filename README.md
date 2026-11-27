<div align="center">

# 🤖 基于 LangGraph 的多智能体代码审查系统

**LangGraph Multi-Agent Code Review System**

5 个专业 AI Agent 并行工作，自动发现代码中的安全漏洞、质量问题、测试缺失、文档缺失和可维护性隐患，输出结构化的审查报告。

Built with [LangGraph](https://langchain-ai.github.io/langgraph/) · [Anthropic Claude](https://www.anthropic.com/) / [OpenAI](https://openai.com/) / [DeepSeek](https://www.deepseek.com/) · [Pydantic](https://docs.pydantic.dev/) · [Semgrep](https://semgrep.dev/) · [Ruff](https://docs.astral.sh/ruff/)

</div>

---

> **📌 项目出处**：本项目基于 [Om Solanki 的 multi-agent-code-reviewer](https://github.com/OmkumarSolanki/multi-agent-code-reviewer)（MIT 许可证）改造而来。在原项目 4 个 agent 的基础上，**新增了「可维护性」审查 agent**，并解决了 DeepSeek 等 OpenAI 兼容 provider 的结构化输出兼容性问题，以及 Windows 平台下的若干跨平台缺陷。具体改动见 [我的改动](#-我的改动)。

---

## 🎯 它能做什么

给它一个 GitHub Pull Request 链接，它会返回一份结构化的 JSON 审查报告，识别：

| Agent | 关注点 | 确定性工具 | LLM 角色 |
|---|---|---|---|
| 🔒 **Security** | 安全漏洞（注入、硬编码密钥、弱加密） | Semgrep | 解释发现、给出修复建议、补漏 |
| 🧹 **Quality** | 代码质量（复杂度、命名、DRY） | Ruff + AST | 识别超出 linter 的坏味道 |
| 🧪 **Test Mapping** | 测试覆盖 | AST 交叉比对 | 为未覆盖实体推荐测试 |
| 📝 **Docs** | 文档缺失 | AST 扫描 docstring | 基于签名补一行 docstring |
| 🛠️ **Maintainability** | 可维护性（长函数、多参数、上帝类） | AST 指标 | 给出重构建议 |

```bash
$ swarm review https://github.com/owner/repo/pull/42 --output report.json
```

设置 `--post-comments` 时，还会把 Markdown 摘要回帖到 PR（明确标注为 bot 生成）。

提供两个入口：**CLI**（`swarm review …`）和 **HTTP API**（`POST /review`），共享同一个异步核心。

> v1 仅支持 Python 仓库。

---

## 💡 为什么用多智能体，而不是一个大 prompt

单个 AI 用一个巨型 prompt 审查整个 PR 有几个问题：

1. **上下文膨胀** —— 把安全规则 + 风格规则 + 测试模式 + 文档规范塞进一个 prompt，模型对每个维度都不够专注。
2. **工具不同** —— 安全用 Semgrep、质量用 Ruff、测试映射走 AST。让一个 agent 串行做这些既慢又乱。
3. **视角不同** —— "安全分析师"和"文档审查员"的思考方式本就不同，专家人设产出更专业的发现。
4. **故障隔离** —— security agent 崩了，其他 agent 仍能产出结果；单 agent 崩了就是全崩。
5. **真并行** —— 5 个 agent 的总耗时约等于最慢的那个，而不是五者之和。

---

## 🏗️ 架构

```
                    User submits PR URL
                            │
                            ▼
            ┌───────────────────────────────┐
            │  Planning Node（确定性规则）   │
            │  → 决定跑哪些 agent            │
            └───────────────────────────────┘
                            │
        ┌──────┬──────┬──────┴──────┬──────────┐
        ▼      ▼      ▼             ▼          ▼
   ┌────────┐┌───────┐┌───────┐┌───────┐┌──────────────┐
   │Security││Quality││  Test ││ Docs  ││Maintainability│
   │ Agent  ││ Agent ││Mapping││ Agent ││    Agent      │
   └────────┘└───────┘└───────┘└───────┘└──────────────┘
        │      │      │         │          │
    Semgrep  Ruff/AST AST+test  AST       AST
      +LLM    +LLM    mapping  +LLM       +LLM
        │      │      │         │          │
        └──────┴──────┴────┬────┴──────────┘
                           ▼
            ┌───────────────────────────────┐
            │   Aggregator                  │
            │   （去重、排序、LLM 总结）      │
            └───────────────────────────────┘
                           │
                           ▼
                 Structured JSON Report
```

5 个专家通过 LangGraph 的 [`Send` API](https://langchain-ai.github.io/langgraph/concepts/low_level/#send) **并行**执行，总时长由最慢的 agent 决定。

### 确定性优先（deterministic-first）

每个专家都遵循同一个模式：**先跑确定性工具，再交给 LLM 分析**。纯 LLM 会幻觉（编造行号、报不存在的漏洞），纯规则无法"推理为什么错"。两者结合 = 规则保证高精度 + LLM 保证高召回和解释。

---

## 🚀 快速开始

### 1. 安装

```bash
git clone <你的仓库地址>
cd multi-agent-code-reviewer

python -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

> 国内环境 pip 下载慢，可用清华镜像：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple`

### 2. 安装 Semgrep

Semgrep 是独立的 CLI 工具（security agent 调用它）：

```bash
pip install semgrep          # 或 brew install semgrep / pipx install semgrep
```

### 3. 配置

```bash
cp .env.example .env
```

编辑 `.env`，任选一个 LLM provider：

```bash
# DeepSeek（OpenAI 兼容，国内可用）
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat

# 或 OpenAI
# LLM_PROVIDER=openai
# OPENAI_API_KEY=sk-...

# 或 Anthropic Claude（默认）
# ANTHROPIC_API_KEY=sk-ant-...
```

回帖评论 / 私有仓库需要 `GITHUB_TOKEN`。LangSmith 追踪是可选的。

### 4. 运行

```bash
swarm review https://github.com/owner/repo/pull/42              # JSON 到 stdout
swarm review <PR_URL> --output report.json --post-comments      # 写文件 + 回帖
swarm review <PR_URL> --only security,maintainability           # 只跑指定 agent
```

HTTP 服务：

```bash
uvicorn reviewer.api:app --host 0.0.0.0 --port 8000
curl -X POST http://localhost:8000/review -H 'content-type: application/json' -d '{"pr_url": "..."}'
```

---

## ⚙️ 配置

| 变量 | 必填 | 说明 |
|---|---|---|
| `LLM_PROVIDER` | 否 | `anthropic`（默认）/ `openai`。DeepSeek 用 `openai` |
| `ANTHROPIC_API_KEY` | provider=anthropic 时 | Anthropic key |
| `OPENAI_API_KEY` | provider=openai 时 | OpenAI / DeepSeek key |
| `OPENAI_BASE_URL` | 用 DeepSeek 时 | `https://api.deepseek.com` |
| `LLM_MODEL` | 否 | 覆盖默认模型 |
| `GITHUB_TOKEN` | 私有仓库/回帖时 | GitHub token |

---

## 🛡️ 可靠性设计

内置生产级加固（而非事后补丁）：

- **每 agent 超时**（120/90/60/90/60s）—— 通过 `asyncio.timeout`，超时记录到 `agents_failed` 而非崩溃
- **异步重试 + 指数退避 + 抖动**（3 次，1s→2s→4s，封顶 10s）—— `CancelledError` 永不重试
- **每端点熔断器**（CLOSED → OPEN → HALF_OPEN）—— 5 次失败/60s 打开 30s，防止雪崩
- **失败隔离** —— 每个 agent 捕获自身异常，aggregator 容忍部分结果
- **降级兜底** —— LLM 失败退回工具种子结果，用户永远拿得到东西

---

## 🧬 数据模型

### Finding

```jsonc
{
  "id": "F-001",
  "agent": "security|quality|test_mapping|docs|maintainability",
  "category": "security|quality|test_coverage|documentation|maintainability",
  "severity": "critical|high|medium|low|info",
  "file_path": "app/auth.py",
  "line_start": 23,
  "line_end": 25,
  "title": "...",
  "explanation": "...",
  "suggestion": "...",
  "confidence": 0.92,
  "tool_source": "semgrep:python.lang.security.unsafe-eq"
}
```

### ReviewReport

包含 PR 元信息、排序后的 findings、LLM 生成的执行摘要、`agents_succeeded` / `agents_failed`、trace_id 等。

---

## 📁 项目结构

```
reviewer/
├── cli.py                    # Typer CLI 入口
├── api.py                    # FastAPI HTTP 入口
├── runner.py                 # 共享异步 run_review()
├── config.py                 # 环境变量读取
├── agents/
│   ├── base.py               # get_llm() + analyze_with_schema()（重试+熔断包装）
│   ├── security.py           # security_agent_node
│   ├── quality.py            # quality_agent_node
│   ├── test_mapping.py       # test_mapping_agent_node
│   ├── docs.py               # docs_agent_node
│   └── maintainability.py    # maintainability_agent_node  ← 新增
├── graph/
│   ├── state.py              # ReviewState + AGENT_NODE_TO_LABEL
│   ├── planner.py            # 确定性规划节点
│   ├── builder.py            # build_review_graph() + Send 分发
│   └── aggregator.py         # 去重 + 排序 + LLM 总结
├── tools/
│   ├── github_client.py      # 异步 fetch_pr()
│   ├── semgrep_runner.py     # Semgrep 子进程封装
│   ├── ruff_runner.py        # Ruff 子进程封装
│   └── ast_inspector.py      # AST 分析（函数/类/引用）
├── reliability/
│   ├── retry.py              # async_retry 装饰器
│   └── circuit_breaker.py    # CircuitBreaker
├── models/
│   ├── findings.py           # Finding / Severity / Category
│   └── report.py             # ReviewReport / AgentFailure
└── observability/
    └── langsmith_setup.py    # 可选追踪配置
tests/                        # 279 个测试 + fixture 样例仓库
```

---

## 🔧 我的改动

基于原项目（Om Solanki / multi-agent-code-reviewer，MIT）所做的改造：

1. **新增「可维护性」agent**（`reviewer/agents/maintainability.py`）—— 用 AST 扫描函数长度、参数数量、god class，交给 LLM 给出重构建议，接入 planner / builder / state / 数据模型。
2. **修复 DeepSeek 等 OpenAI 兼容 provider 的结构化输出兼容性**（`reviewer/agents/base.py`）—— 将 `with_structured_output` 改为 `method="function_calling"`，规避 `response_format: json_schema` 不被支持的 400 错误。
3. **修复 Windows 平台跨平台缺陷** —— 包括 `tests/test_ruff_runner.py` 的可执行文件名大小写断言（`ruff.EXE` vs `ruff.exe`）。
4. **接入 DeepSeek provider** —— 通过 `OPENAI_BASE_URL` 配置，验证功能调用链路。

---

## 🙏 致谢

本项目基于以下优秀开源工具：

- [LangGraph](https://langchain-ai.github.io/langgraph/) —— agent 编排，`Send` API 并行分发
- [LangChain](https://www.langchain.com/) —— LLM 胶水与结构化输出
- [Anthropic Claude](https://www.anthropic.com/) / [OpenAI](https://openai.com/) / [DeepSeek](https://www.deepseek.com/) —— 各专家背后的 LLM
- [Semgrep](https://semgrep.dev/) —— 安全静态分析
- [Ruff](https://docs.astral.sh/ruff/) —— Python linter
- [Pydantic](https://docs.pydantic.dev/) —— 每个 LLM 输出的 schema 强制
- [FastAPI](https://fastapi.tiangolo.com/) + [Typer](https://typer.tiangolo.com/) —— HTTP 与 CLI

特别感谢原项目作者 [Om Solanki](https://github.com/OmkumarSolanki) 的开源工作。

## License

[MIT](LICENSE)
