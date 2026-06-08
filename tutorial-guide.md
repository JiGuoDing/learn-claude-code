# Learn Claude Code 项目学习路线图

这份文档不是章节 README 的替代品，而是一张学习地图：你可以先用它建立全局结构，再回到各章 `README.md` 和 `code.py` 做精读。

本项目的主题不是“写一个更聪明的 Agent 大脑”，而是学习如何为已经具备推理能力的模型构建可工作的 **Agent Harness**：

```text
Agent Product = Model + Harness

Harness = Tools + Knowledge + Observation + Action Interfaces + Permissions
```

模型负责判断、推理和选择行动；Harness 负责把工具、权限、上下文、记忆、任务、团队协作、插件能力组织成一个可运行环境。本项目用 20 个递进章节，把 Claude Code 这类 coding agent harness 的关键机制拆开讲，再在 s20 合回一个完整系统。

---

## 1. 你应该怎样使用这份指南

如果你已经有 Agent 基础，但想系统提升 Agent 工程和 Python 能力，建议按下面节奏学习：

1. **先读本指南第 2-4 节**：建立项目全景，理解新版 20 章和旧版 12 章的关系。
2. **按第 5 节的 6 个阶段学习**：每阶段先跑代码，再读 README，最后做练习。
3. **用第 6 节做精读索引**：遇到复杂章节时，知道该盯哪些类、函数、数据结构。
4. **用第 7 节补 Python 能力**：把项目里反复出现的 Python 技术点逐个拆开掌握。
5. **用第 8 节做复刻练习**：不要只读，最终要自己写一个 mini harness。

推荐学习方式：

```text
读 README 的设计叙述
  -> 跑 code.py
  -> 找到新增函数/类
  -> 对照上一章 diff 思考“新增机制挂在循环哪里”
  -> 做一个小改造
```

每章最重要的问题都不是“这段代码能不能跑”，而是：

```text
这个机制解决什么 harness 问题？
它挂在 agent_loop 的哪个位置？
它改变了工具、上下文、权限、任务还是协作？
它为什么不应该写死在模型之外的流程编排里？
```

---

## 2. 项目定位：这是 Agent Harness 教程，不是普通应用项目

仓库里有 Python、Markdown、Next.js 三类内容，但学习主线是 Python 教学代码。

核心路径：

```text
learn-claude-code/
  s01_agent_loop/ ... s20_comprehensive/   # 新版 20 章主线，优先学习
  agents/                                  # 旧版 12 章可运行脚本
  docs/                                    # 旧版 12 章文档
  skills/                                  # s07 使用的 skill 示例
  web/                                     # Next.js 展示层，目前主要服务旧版 docs
  tests/                                   # 编译/冒烟测试
```

你应该优先学习：

```text
s01_agent_loop/code.py
...
s20_comprehensive/code.py
```

`agents/` 目录可以作为旧版压缩参考，尤其是 `agents/s_full.py`，它把旧 12 章机制合并成一个较短的完整样例。但如果你从零系统学习，应该以根目录 `s01_*` 到 `s20_*` 为准。

`web/` 是 Next.js 前端，用于展示文档和可视化。它对理解 Agent harness 不是主线，只需要知道：

- `web/package.json` 定义了 Next.js 项目脚本。
- `web/scripts/extract-content.ts` 会从文档中提取内容。
- `web/src/` 里是页面、组件、可视化和国际化数据。

除非你想研究教程网站本身，否则不要一开始陷入 `web/`。

---

## 3. 环境准备

### Python 运行环境

项目 Python 依赖很少：

```txt
anthropic>=0.25.0
python-dotenv>=1.0.0
pyyaml>=6.0
```

建议：

```sh
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

然后在 `.env` 中设置：

```env
ANTHROPIC_API_KEY=你的 key
MODEL_ID=你要使用的 Claude 模型
```

项目代码通常会这样加载配置：

```python
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv(override=True)
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]
```

这里有几个值得理解的点：

- `load_dotenv(override=True)` 会读取 `.env` 并覆盖当前环境变量，适合本地教程项目。
- `Anthropic(base_url=...)` 支持代理或自定义 API 网关；没设置时使用默认端点。
- `MODEL_ID` 用环境变量而不是硬编码，方便不同模型之间切换。

### 快速验证

不调用 API 的基本验证：

```sh
python -m py_compile s01_agent_loop/code.py
python -m pytest tests
```

运行第一章：

```sh
python s01_agent_loop/code.py
```

运行最终综合章：

```sh
python s20_comprehensive/code.py
```

注意：运行章节脚本会调用 LLM API，且部分章节会在工作区创建 `.tasks/`、`.mailboxes/`、`.worktrees/`、`.scheduled_tasks.json` 等运行产物。这些是学习过程的一部分。

---

## 4. 先抓住唯一不变的核心循环

从 s01 到 s20，外层机制越来越多，但核心循环始终是同一个：

```python
def agent_loop(messages):
    while True:
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
        )

        messages.append({
            "role": "assistant",
            "content": response.content,
        })

        if response.stop_reason != "tool_use":
            return

        results = []
        for block in response.content:
            if block.type == "tool_use":
                output = TOOL_HANDLERS[block.name](**block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })

        messages.append({"role": "user", "content": results})
```

你要重点理解 Anthropic Messages API 的几个概念：

| 概念 | 含义 |
|------|------|
| `messages` | 对话历史。每轮都把累计上下文发给模型 |
| `system` | 系统提示词，不属于普通 user/assistant 历史 |
| `tools` | 工具 schema，告诉模型有哪些动作可选 |
| `tool_use` block | 模型决定调用工具时输出的结构化块 |
| `tool_result` block | Harness 执行工具后回填给模型的结果 |
| `stop_reason` | 模型停止原因，教学版常用它判断是否继续工具循环 |

关键心智模型：

```text
模型不直接执行工具。
模型只输出“我要调用哪个工具、传什么参数”。
Python harness 负责真正执行，并把结果塞回 messages。
```

所以本项目所有高级机制，本质都是围绕这几件事做工程化：

- LLM 前：准备 system prompt、压缩上下文、注入记忆和通知。
- 工具前：权限检查、hook、并发/后台策略。
- 工具中：dispatch 到内置工具或外部 MCP 工具。
- 工具后：写回结果、记录事件、触发后处理。
- 停止时：总结、清理、等待下一次触发。

---

## 5. 六阶段学习路线

### 阶段一：让 Agent 能行动

对应章节：

- [s01 Agent Loop](s01_agent_loop/README.md)
- [s02 Tool Use](s02_tool_use/README.md)
- [s03 Permission](s03_permission/README.md)
- [s04 Hooks](s04_hooks/README.md)

学习目标：

- 理解最小 agent loop。
- 理解工具 schema 和工具分发。
- 理解为什么权限必须在执行前判断。
- 理解 hook 如何把扩展点挂在循环外，而不是把主循环写乱。

重点代码：

- `run_bash`
- `safe_path`
- `TOOL_HANDLERS`
- `check_permission`
- `register_hook`
- `trigger_hooks`
- `agent_loop`

这一阶段要形成的能力：

```text
你应该能从零写一个只有 bash/read/write 三个工具的 agent loop，
并能解释每一次 messages 追加为什么符合 tool_use/tool_result 配对语义。
```

练习：

1. 给 s02 加一个 `list_dir` 工具，只列目录，不执行 shell。
2. 给 s03 的权限系统加一条规则：禁止写入 `.env`。
3. 给 s04 加一个 `PostToolUse` hook：当输出超过 1000 字符时写入临时文件，只返回路径。

### 阶段二：让 Agent 做复杂任务

对应章节：

- [s05 TodoWrite](s05_todo_write/README.md)
- [s06 Subagent](s06_subagent/README.md)
- [s07 Skill Loading](s07_skill_loading/README.md)
- [s08 Context Compact](s08_context_compact/README.md)

学习目标：

- 理解 TodoWrite 是会话内计划，不是跨会话任务系统。
- 理解 subagent 的价值是上下文隔离，而不是更强的模型。
- 理解 skill loading 的关键是“目录先可见，正文按需加载”。
- 理解上下文压缩不是单一摘要，而是多层预算控制。

重点代码：

- `run_todo_write`
- `spawn_subagent`
- `_scan_skills`
- `load_skill`
- `snip_compact`
- `micro_compact`
- `tool_result_budget`
- `compact_history`
- `reactive_compact`

关键设计细节：

`TodoWrite` 的价值不是“列表 UI”，而是强迫模型把任务分解成可检查的步骤。它通常只存在于当前会话中，适合“我现在正在做什么”。

`spawn_subagent` 会创建新的 `messages`，让子 agent 在干净上下文里探索。主 agent 不继承子 agent 的全部过程，只拿最终摘要。这能降低上下文污染。

`Skill Loading` 不应该把所有 `SKILL.md` 塞进 system prompt。正确方式是：

```text
system prompt 只列 skill 名称和 description
模型需要时调用 load_skill(name)
Harness 再把完整 skill 正文注入
```

`Context Compact` 建议按成本从低到高处理：

```text
大工具结果落盘 -> 老 tool_result 替换为占位 -> 裁剪不重要历史 -> LLM 摘要
```

练习：

1. 给 s05 的 todo 增加校验：同一时间只能有一个 `in_progress`。
2. 改造 s06，让 subagent 只允许 `read_file` 和 `glob`，不能写文件。
3. 给 s07 新增一个 `skills/python-debugging/SKILL.md`，让 agent 能按需加载调试原则。
4. 在 s08 中把超过 50KB 的工具结果落盘，并返回文件路径。

### 阶段三：让 Agent 记住、恢复、组织 Prompt

对应章节：

- [s09 Memory](s09_memory/README.md)
- [s10 System Prompt](s10_system_prompt/README.md)
- [s11 Error Recovery](s11_error_recovery/README.md)

学习目标：

- 区分 memory、skill、system prompt、conversation history。
- 理解 system prompt 应该运行时组装，不应写成一个巨大的静态字符串。
- 理解错误恢复是 agent loop 的外围机制，而不是工具内部逻辑。

重点代码：

- `write_memory_file`
- `select_relevant_memories`
- `extract_memories`
- `consolidate_memories`
- `assemble_system_prompt`
- `get_system_prompt`
- `update_context`
- `RecoveryState`
- `retry_delay`
- `with_retry`
- `reactive_compact`

关键设计细节：

Memory 的难点不是“保存所有内容”，而是：

```text
选择：哪些记忆和当前任务有关？
提取：从当前对话中沉淀什么？
整理：如何去重、合并、淘汰？
```

System prompt 组装应该像配置渲染：

```python
def assemble_system_prompt(context: dict) -> str:
    sections = [
        identity_section(context),
        workspace_section(context),
        tools_section(context),
        memory_section(context),
        skills_section(context),
    ]
    return "\n\n".join(s for s in sections if s)
```

这样做的好处是每一段都有清晰来源，未来加入 MCP、worktree、team 状态时不用重写整个 prompt。

Error Recovery 要覆盖几类常见失败：

- 输出被 `max_tokens` 截断：提高上限或要求 continuation。
- prompt 太长：触发 reactive compact。
- 429/529/临时网络错误：指数退避重试。
- 重复失败：切 fallback model 或把错误明确反馈给用户。

练习：

1. 在 s10 的 system prompt 中增加“当前任务数量”段落。
2. 在 s11 的 `retry_delay` 中加入 jitter，避免多个 agent 同时重试。
3. 设计一个 memory 文件格式，区分 user preference、project fact、decision record。

### 阶段四：让任务长期运行

对应章节：

- [s12 Task System](s12_task_system/README.md)
- [s13 Background Tasks](s13_background_tasks/README.md)
- [s14 Cron Scheduler](s14_cron_scheduler/README.md)

学习目标：

- 理解 TodoWrite 和 Task System 是两个不同层次。
- 理解持久化任务图如何支撑恢复和多 agent 协作。
- 理解慢操作为什么要变成后台任务。
- 理解 cron 调度要和 agent loop 解耦。

重点代码：

- `Task`
- `create_task`
- `can_start`
- `claim_task`
- `complete_task`
- `is_slow_operation`
- `should_run_background`
- `start_background_task`
- `collect_background_results`
- `CronJob`
- `cron_matches`
- `schedule_job`
- `cron_scheduler_loop`
- `queue_processor_loop`

关键设计细节：

Task System 是磁盘上的可恢复任务图：

```python
@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str
    owner: str | None
    blockedBy: list[str]
```

`blockedBy` 表示“我依赖哪些任务完成”。`claim_task` 必须先调用 `can_start`，否则 agent 会跳过前置依赖直接开工。

后台任务的核心语义是：

```text
原始 tool_use 必须立刻配一个 tool_result。
慢操作完成后的真实结果不能再伪装成原始 tool_result，
而应该作为 task_notification 注入后续 messages。
```

Cron Scheduler 应该分三层：

```text
scheduler thread：只检查时间
cron_queue：只存已触发任务
agent_loop / queue_processor：只负责交付给模型
```

这样时间判断、队列传递和模型执行不会互相耦合。

练习：

1. 给 s12 增加 `release_task`：队友退出时把 `in_progress` 重置为 `pending`。
2. 给 s13 的后台任务增加 `status` 查询工具。
3. 给 s14 写 5 个 cron 表达式测试，包括 `*/5 * * * *` 和一次性任务。

### 阶段五：让多个 Agent 协作

对应章节：

- [s15 Agent Teams](s15_agent_teams/README.md)
- [s16 Team Protocols](s16_team_protocols/README.md)
- [s17 Autonomous Agents](s17_autonomous_agents/README.md)
- [s18 Worktree Isolation](s18_worktree_isolation/README.md)

学习目标：

- 理解 subagent 和 teammate 的生命周期差异。
- 理解文件收件箱为什么适合教学展示异步通信。
- 理解协议状态机如何避免“发了请求但不知道谁回复”。
- 理解自治认领如何降低 Lead 分配成本。
- 理解 worktree 隔离如何解决并行写文件冲突。

重点代码：

- `MessageBus`
- `spawn_teammate_thread`
- `ProtocolState`
- `new_request_id`
- `match_response`
- `consume_lead_inbox`
- `idle_poll`
- `scan_unclaimed_tasks`
- `detect_repo_root`
- `EventBus`
- `WorktreeManager`
- `bind_task_to_worktree`

关键设计细节：

s15 的 `MessageBus` 用 JSONL 文件模拟邮箱：

```text
send = append 一行 JSON
read_inbox = 读取并消费
```

文件邮箱的优点是可观察、可持久化、容易调试；缺点是并发写需要锁。教学版简化了锁，真实系统必须考虑竞争。

s16 的 `ProtocolState` 解决的是请求-响应匹配：

```text
Lead 发 request_shutdown(teammate) -> 生成 request_id
队友回复 shutdown_response(request_id, approve)
Lead 用 request_id 找到原请求并更新状态
```

没有 request_id，多 agent 协作会很快变成一堆无法归因的消息。

s17 的自治认领让队友在 IDLE 状态下扫描任务板：

```text
先查 inbox，优先处理 shutdown 等协议消息
再查 pending + no owner + can_start 的任务
能认领就 claim，然后回到 WORK
```

s18 的 worktree 隔离把任务和目录绑定：

```text
task_id -> worktree_name -> filesystem path
```

队友 claim 到绑定 worktree 的任务后，`bash/read/write` 应该在对应目录执行，而不是共享主目录。

练习：

1. 在 s15 中观察 `.mailboxes/` 文件内容，手动写一条消息给 lead。
2. 给 s16 新增一种协议消息：`status_request` / `status_response`。
3. 在 s17 中创建三个带依赖的任务，观察两个队友是否按依赖顺序自动认领。
4. 在 s18 中给每个 worktree 写一个事件日志，记录 create/keep/remove。

### 阶段六：接外部能力并综合成完整 Harness

对应章节：

- [s19 MCP Plugin](s19_mcp_plugin/README.md)
- [s20 Comprehensive Agent](s20_comprehensive/README.md)

学习目标：

- 理解 MCP 是外部工具接入协议，不是另一个 agent loop。
- 理解工具池可以动态组装。
- 理解命名空间为什么要用 `mcp__server__tool`。
- 理解 s20 如何把所有机制放回一个循环。

重点代码：

- `MCPClient`
- `connect_mcp`
- `normalize_mcp_name`
- `assemble_tool_pool`
- `BUILTIN_TOOLS`
- `BUILTIN_HANDLERS`
- `prepare_context`
- `call_llm`
- `build_user_content`
- `inject_background_notifications`
- `agent_loop`

关键设计细节：

MCP 的核心流程：

```text
connect_mcp(name)
  -> 连接 server
  -> 发现 tools/list
  -> 把工具变成 mcp__server__tool
  -> assemble_tool_pool 合并内置工具和 MCP 工具
  -> 模型下一轮就能调用这些工具
```

名称规范化很重要：

```python
def normalize_mcp_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)
```

否则外部 server 名或工具名可能包含空格、斜杠、冒号等字符，导致工具名冲突或注入风险。

s20 最值得反复读。你要重点看每个机制位于循环哪个位置：

```text
用户输入
  -> UserPromptSubmit hooks
  -> cron/background 通知注入
  -> context compact
  -> memory + skills + MCP state 组装 system prompt
  -> LLM with retry
  -> PreToolUse hooks + permission
  -> builtin/MCP/background dispatch
  -> PostToolUse hooks
  -> tool_result / notification 回 messages
  -> 下一轮
```

练习：

1. 给 s19 新增一个 mock MCP server：`notes`，提供 `search_notes` 和 `create_note`。
2. 在 s20 中连接两个 MCP server，观察 `assemble_tool_pool` 如何合并工具。
3. 画出 s20 的 agent_loop 流程图，并标出每个章节贡献的机制。

---

## 6. 20 章精读提纲

下面是逐章精读时的关注点。建议每章用 30-90 分钟，复杂章节可以拆成两次。

| 章节 | 先理解什么 | 代码精读重点 | Python 知识点 |
|------|------------|--------------|---------------|
| s01 | 最小 agent loop | `client.messages.create`、`run_bash`、`tool_result` 回填 | `subprocess.run`、环境变量、REPL |
| s02 | 工具分发 | `TOOL_HANDLERS[block.name](**block.input)` | 字典分发、`Path`、`glob` |
| s03 | 权限边界 | deny list、路径越界检查、用户确认 | `Path.resolve`、`is_relative_to`、输入校验 |
| s04 | hooks | `register_hook`、`trigger_hooks`、Pre/Post/Stop | 函数作为一等对象、回调 |
| s05 | 当前任务计划 | `run_todo_write`、状态约束 | list/dict 校验、状态机 |
| s06 | 子 agent | 新 `messages`、工具子集、摘要返回 | 函数复用、隔离上下文 |
| s07 | 技能按需加载 | frontmatter 解析、skill catalog、`load_skill` | 文件扫描、正则、Markdown frontmatter |
| s08 | 上下文压缩 | 四层 compact pipeline | 文件持久化、预算控制 |
| s09 | 记忆系统 | selection/extraction/consolidation | 文本文件索引、信息抽取 |
| s10 | prompt 组装 | `assemble_system_prompt(context)` | 字符串拼接、上下文字典 |
| s11 | 错误恢复 | `RecoveryState`、退避、reactive compact | `try/except`、重试、异常分类 |
| s12 | 任务图 | `Task`、`blockedBy`、claim/complete | `dataclass`、JSON 持久化 |
| s13 | 后台任务 | daemon thread、placeholder result、notification | `threading`、共享 dict、锁 |
| s14 | 定时调度 | `CronJob`、cron 解析、queue processor | `datetime`、线程、队列 |
| s15 | 团队通信 | `MessageBus`、JSONL inbox、队友线程 | 文件追加、线程内 agent loop |
| s16 | 协议 | `ProtocolState`、request_id、响应匹配 | 协议设计、状态记录 |
| s17 | 自治认领 | idle poll、scan task board、auto claim | 轮询、优先级处理 |
| s18 | worktree 隔离 | repo root、worktree record、cwd 切换 | Git 命令封装、路径安全 |
| s19 | MCP | `MCPClient`、动态工具池、命名空间 | mock 协议、lambda 闭包 |
| s20 | 综合系统 | 机制归位、完整 `agent_loop` | 大文件阅读、模块边界识别 |

精读每章时建议问自己 5 个问题：

1. 这一章新增了什么 harness 能力？
2. 新能力是在 LLM 前、工具前、工具执行中、工具后还是停止时生效？
3. 新增的数据结构是什么？生命周期是什么？
4. 如果这个机制用于生产，需要补哪些安全和并发细节？
5. 这个机制和前面章节有没有重叠？边界在哪里？

---

## 7. 借项目补齐的 Python 知识清单

### 7.1 `pathlib.Path` 和路径安全

项目大量使用：

```python
WORKDIR = Path.cwd()

def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path
```

你要理解：

- `Path.cwd()` 当前工作目录。
- `(WORKDIR / p)` 拼路径。
- `.resolve()` 规整 `..`、符号链接等路径。
- `.is_relative_to(WORKDIR)` 防止写出工作区。

这是 coding agent harness 的基础安全层。任何 read/write/edit 工具都应该先过它。

### 7.2 `subprocess.run`

典型模式：

```python
r = subprocess.run(
    command,
    shell=True,
    cwd=WORKDIR,
    capture_output=True,
    text=True,
    timeout=120,
)
out = (r.stdout + r.stderr).strip()
```

需要理解：

- `shell=True` 方便执行字符串命令，但有注入和破坏风险。
- `cwd=WORKDIR` 限定命令运行目录。
- `capture_output=True` 捕获 stdout/stderr。
- `text=True` 返回字符串而不是 bytes。
- `timeout=120` 防止命令无限挂起。

生产系统还需要更严格的命令解析、沙箱、权限审批和资源限制。

### 7.3 JSON Schema 工具定义

工具定义通常是：

```python
{
    "name": "read_file",
    "description": "Read file contents.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["path"],
    },
}
```

这不是给 Python 用的类型提示，而是给模型看的动作空间。description 写得清楚，模型才更容易在正确时机调用正确工具。

### 7.4 字典分发

s02 开始用：

```python
TOOL_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
}

output = TOOL_HANDLERS[block.name](**block.input)
```

这比一长串 `if block.name == ...` 更适合扩展。后面 MCP 动态工具池也是这个思想的升级版。

### 7.5 `dataclass`

任务、协议、cron job 常用 `dataclass`：

```python
@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str
    owner: str | None
    blockedBy: list[str]
```

适合表达结构化状态。通常会配合 `asdict()` 和 JSON 持久化使用。

### 7.6 线程和队列

后台任务、cron、队友都用线程：

```python
threading.Thread(target=worker, daemon=True).start()
```

关键点：

- `daemon=True` 表示主进程退出时线程不阻止退出。
- 共享 dict/list 时需要锁，否则可能出现竞态。
- 队列适合跨线程传递通知，比如 `Queue` 或受锁保护的 list。

### 7.7 文件持久化

任务系统、邮箱、记忆、worktree record 都使用文件：

```python
path.write_text(json.dumps(data, indent=2))
data = json.loads(path.read_text())
```

教学版偏简单；生产版要考虑：

- 原子写入。
- 文件锁。
- 部分写失败恢复。
- 并发读写一致性。

### 7.8 闭包和 lambda 捕获

s19/s20 组装 MCP handler 时会用到类似模式：

```python
handlers[prefixed] = (
    lambda *, c=mcp_client, t=tool_def["name"], **kw:
        c.call_tool(t, kw)
)
```

`c=mcp_client` 和 `t=tool_def["name"]` 是为了在循环中固定当前值。否则 lambda 可能捕获到循环结束后的最后一个变量值。这是 Python 闭包里很常见的坑。

---

## 8. 从读懂到会写：复刻路线

如果你想真正掌握，建议不要只跑项目代码，而是自己新建一个 `playground/mini_agent.py`，按下面顺序复刻。

### 里程碑 1：最小 loop

实现：

- `messages`
- `TOOLS`
- `run_bash`
- `agent_loop`

验收：

```text
用户输入“列出当前目录”
模型调用 bash
harness 执行命令
结果回填给模型
模型输出总结
```

### 里程碑 2：工具池

增加：

- `read_file`
- `write_file`
- `edit_file`
- `glob`
- `TOOL_HANDLERS`

验收：

```text
模型能读文件、写文件、编辑文件，不需要通过 bash 拼命令。
```

### 里程碑 3：权限和 hooks

增加：

- `safe_path`
- deny list
- `register_hook`
- `trigger_hooks`

验收：

```text
写出工作区被拒绝。
危险 bash 命令被拒绝。
日志 hook 能记录工具调用。
```

### 里程碑 4：计划、子 agent、技能

增加：

- `todo_write`
- `spawn_subagent`
- `skills/` 扫描
- `load_skill`

验收：

```text
复杂任务前模型会列 todo。
探索性任务可派给 subagent。
模型能按需加载 skill 正文。
```

### 里程碑 5：任务系统和后台

增加：

- `.tasks/task_*.json`
- `create_task/list/get/claim/complete`
- 后台线程执行慢命令

验收：

```text
任务跨进程重启仍保留。
慢命令先返回 placeholder，完成后注入 notification。
```

### 里程碑 6：团队和 worktree

增加：

- `MessageBus`
- 队友线程
- `ProtocolState`
- idle auto-claim
- worktree 绑定

验收：

```text
Lead 创建任务。
两个队友自动认领。
队友之间通过 inbox 通信。
不同任务在不同目录执行。
```

### 里程碑 7：MCP 和综合循环

增加：

- mock MCP server
- `connect_mcp`
- `assemble_tool_pool`
- s20 风格完整 loop

验收：

```text
连接 docs server 后，下一轮模型能看到 mcp__docs__search。
内置工具和 MCP 工具共用同一套分发机制。
```

---

## 9. 学习时常见误区

### 误区一：把 Agent 当成流程图

本项目反复强调：不要用硬编码流程替代模型判断。Harness 只提供工具、上下文和边界。什么时候读文件、什么时候写代码、什么时候停止，应该让模型根据上下文决定。

### 误区二：把 TodoWrite 当成 Task System

TodoWrite 是当前会话内的执行清单；Task System 是持久化任务图。前者帮助一个 agent 不漂移，后者支持跨会话恢复和多 agent 协作。

### 误区三：把 Subagent 和 Teammate 混为一谈

Subagent 是一次性上下文隔离工具。Teammate 是有生命周期、有 inbox、有协议的持久协作者。

### 误区四：把 Memory 当成无限历史

Memory 不是把历史全存起来。Memory 是选择、提取、整理后的长期上下文。保存越多不一定越好，关键是相关、准确、可检索。

### 误区五：忽略权限和路径安全

Agent harness 给模型行动能力，也必须给它边界。任何文件写入、shell 执行、MCP destructive tool 都应该进入权限管线。

---

## 10. 最后建议：按“机制归位”理解 s20

如果只能深读一个文件，读 [s20_comprehensive/code.py](s20_comprehensive/code.py)。

但不要一上来读它。先按 s01-s19 理解每个机制，再回到 s20 问：

```text
这个函数来自哪一章？
它挂在循环哪里？
它是否改变 messages？
它是否改变 tools？
它是否改变 system prompt？
它是否改变工作目录、任务状态或团队状态？
```

最终你要形成的能力不是背出这个项目的代码，而是能独立设计一个 Agent Harness：

```text
一个循环
一套工具池
一个权限管线
一个上下文管理策略
一个任务系统
一套协作协议
一个外部能力接入层
```

机制很多，循环一个。
