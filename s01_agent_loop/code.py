#!/usr/bin/env python3
"""
s01_agent_loop.py - The Agent Loop
===================================

The entire secret of an AI coding agent in one pattern:

    while stop_reason == "tool_use":
        response = LLM(messages, tools)
        execute tools
        append results

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> |  Tool   |
    |  prompt  |      |       |      | execute |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                          (loop continues)

This is the core loop: feed tool results back to the model
until the model decides to stop. Production agents layer
policy, hooks, and lifecycle controls on top.

Key concepts demonstrated here:
  - The agent loop pattern (LLM ⇄ tool execution)
  - Tool definitions as JSON Schema
  - Multi-turn conversation state management
  - Safety guardrails (command filtering, timeouts, output truncation)
  - Streaming vs. non-streaming response handling

Usage:
    pip install anthropic python-dotenv
    ANTHROPIC_API_KEY=... python s01_agent_loop/code.py
"""

import os
import subprocess

# ── readline：为 REPL 提供交互式行编辑 ─────────────────────────────
# `readline` 模块提供 Emacs 风格的行编辑（Ctrl-A、Ctrl-E 等）、
# 命令历史（上下方向键）以及终端里的输入编辑能力。
# Windows 默认没有这个模块；这里用 try/except 优雅降级到普通 input()，
# 只是没有历史导航或行编辑功能。
try:
    import readline
    # 在 macOS 上，系统 Python 链接的是 libedit（readline 的替代品），
    # 而不是 GNU readline。libedit 有一个已知问题：中文/Unicode 字符会让
    # 退格键表现异常（删错字符或破坏显示）。下面四个 parse_and_bind() 调用
    # 会重新配置终端按键绑定，用来绕过这个 libedit 问题：
    #
    #   bind-tty-special-chars off  → 不让终端驱动拦截特殊按键
    #                                  （例如表示退格的 ^?），改由 libedit 处理
    #   input-meta on / output-meta on → 启用 8 位字符输入输出，让中文字符
    #                                    原样通过
    #   convert-meta off → 不转换 meta（Alt）按键序列；保留 UTF-8 字节，
    #                       避免被改写成 libedit 无法正确解析的转义序列
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
except ImportError:
    # Windows 或没有 readline 的环境中，input() 仍然可用，
    # 只是没有历史导航或行编辑。
    pass

# ── SDK 导入 ───────────────────────────────────────────────────────
# `Anthropic` 是 Anthropic（Claude）API 的 Python SDK 客户端。
# 它负责 HTTP 通信、认证、重试和流式响应。
# 这里用到的关键方法：
#   - client.messages.create()：发送一轮对话并获取响应
from anthropic import Anthropic

# `load_dotenv` 会从当前目录（或父目录）里的 `.env` 文件读取键值对，
# 并加载到 `os.environ` 中。
# 这样可以把 API key 放在源码之外。
# `override=True` 表示 .env 里的值优先于已有环境变量，
# 便于为这个脚本临时覆盖系统级设置。
from dotenv import load_dotenv

# ── 环境设置 ───────────────────────────────────────────────────────
# 加载 .env 文件，并让它优先于系统环境变量。
# 通常会在这里定义 ANTHROPIC_API_KEY、MODEL_ID 和 ANTHROPIC_BASE_URL。
load_dotenv(override=True)

# 一些代理/自定义 base URL 配置会使用 ANTHROPIC_AUTH_TOKEN，
# 而不是标准的 x-api-key 请求头。如果用户设置了自定义 base URL
# （意味着请求会经过代理或 API 网关），这里会清掉 ANTHROPIC_AUTH_TOKEN，
# 让 SDK 回退到标准认证机制（x-api-key 请求头），这通常更容易被代理支持。
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# 初始化 Anthropic 客户端。
# - `base_url`：允许把请求路由到代理、API 网关或自托管端点。
#   未设置（None）时，默认使用官方 Anthropic API 端点
#   （https://api.anthropic.com）。
# - 认证：SDK 会自动从环境变量读取 ANTHROPIC_API_KEY，
#   不需要显式传入。
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

# 模型标识符：指定要使用哪个 Claude 模型。
# 例如："claude-sonnet-4-6"、"claude-opus-4-8"
MODEL = os.environ["MODEL_ID"]

# ── 系统提示词 ─────────────────────────────────────────────────────
# 系统提示词设置模型的人设和行为约束。
# 它不是对话历史的一部分，而是位于 messages “之上”，并在所有轮次中持续生效。
# 关键指令：
#   - "You are a coding agent" → 角色定义；模型会像工具一样行动
#   - "at {cwd}" → 让模型知道当前工作目录，便于生成正确的文件路径
#   - "Use bash to solve tasks" → 指示模型使用 bash 工具，而不是只解释方案
#   - "Act, don't explain" → 推动模型给出偏行动的响应；
#                            减少冗长铺垫，更快得到结果
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don't explain."

# ── 工具定义：这里只提供 bash ─────────────────────────────────────
# 工具按照 Anthropic API 的 tool-use 格式定义为 JSON Schema 对象。
# 每个工具包含：
#   - `name`：模型调用该工具时使用的标识符
#   - `description`：帮助模型判断什么时候使用这个工具
#   - `input_schema`：描述期望参数的 JSON Schema；
#                     模型会生成符合该 schema 的参数
#
# 这个 agent 有意保持极简：只有一个工具（bash）。
# 生产级 agent 通常会添加文件读写、搜索、网页获取等工具。
# 模型看到这个工具定义后，可以在需要运行 shell 命令时调用 bash(...)
# （例如列文件、跑测试、执行 git 等）。
TOOLS = [{
    "name": "bash",
    "description": "Run a shell command.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                # 模型会在这里生成 shell 命令字符串。
                # description 字段是隐含的：模型知道这里应该是有效的 shell 命令。
            }
        },
        "required": ["command"],  # 模型必须提供命令字符串
    },
}]


# ── 工具执行 / 安全层 ─────────────────────────────────────────────
def run_bash(command: str) -> str:
    """
    安全地执行 shell 命令并返回输出。

    这是 agent 的“手”：它把模型的意图
    （包含命令字符串的 tool_use 块）转换成真实的系统动作。

    安全特性（纵深防御）：
      1. 危险列表：在命令进入 shell 前，拦截包含明显破坏性模式的命令。
         这是一个朴素的子串检查，不是安全边界，只是常见事故的绊线。
      2. 超时（120 秒）：防止卡住的命令（无限循环、等待网络等）永远阻塞 agent。
         带 timeout 的 subprocess.run() 会抛出 TimeoutExpired，
         我们捕获后返回错误信息。
      3. 输出截断（5 万字符）：防止巨大输出（例如 cat 大型二进制文件）
         撑爆对话上下文或触碰 API token 限制。
      4. CWD 沙箱：命令在 os.getcwd() 中运行，也就是项目根目录。
         这不是真正的沙箱；生产级 agent 应使用 Docker、chroot，
         或至少使用专用临时目录。

    参数：
        command: LLM 生成的 shell 命令字符串。

    返回：
        包含 stdout+stderr（已截断）的字符串，或错误信息。
    """
    # ── 第 1 步：朴素安全过滤 ──
    # 检查命令是否包含危险子串。
    # 这是第一道“见招拆招”式防线。有动机的攻击者或有创造力的模型
    # 很容易绕过它（例如把 `sudo` 写成 `su''do`）。
    # 真正的 agent 需要操作系统级沙箱。
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"

    try:
        # ── 第 2 步：通过 subprocess 执行 ──
        # subprocess.run() 会启动子进程并等待它结束。
        # 参数：
        #   shell=True     → 通过 /bin/sh 运行，启用管道、重定向、通配符
        #                     以及模型可能使用的其他 shell 特性。
        #                     （取舍：相比 shell=False + 参数列表不那么安全，
        #                     但模型生成的是 shell 语法，所以这里需要它。）
        #   cwd=os.getcwd() → 在项目目录中运行，让相对路径按预期工作。
        #   capture_output=True → 将 stdout 和 stderr 都捕获到内存中，
        #                          而不是打印到终端。
        #   text=True      → 使用 UTF-8 将输出字节解码为 str，
        #                     方便直接作为 Python 字符串处理。
        #   timeout=120    → 如果进程运行超过 120 秒就杀掉它，
        #                     防止卡住的命令阻塞循环。
        r = subprocess.run(
            command,
            shell=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=120,
        )

        # ── 第 3 步：合并 stdout 和 stderr ──
        # 两个流都有价值：stdout 承载主要输出，
        # stderr 承载错误、警告和诊断信息。
        # 我们把它们拼接起来，让模型看到完整信息。
        # .strip() 会移除首尾空白（主要是 shell 输出末尾的换行）。
        out = (r.stdout + r.stderr).strip()

        # ── 第 4 步：截断并返回 ──
        # API 模型有上下文限制；返回 500KB 日志会浪费 token，
        # 也可能超过上下文窗口。
        # 50,000 个字符是在完整性和上下文效率之间的务实平衡。
        # 如果命令完全没有输出（strip 后为空字符串），
        # 返回一个占位符，让模型知道命令已成功运行，
        # 而不是误以为出了问题。
        return out[:50000] if out else "(no output)"

    # ── 错误处理 ──
    # TimeoutExpired：命令运行超过 120 秒。
    # 返回错误信息，而不是让 agent 循环崩溃。
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

    # FileNotFoundError：命令引用了不存在的可执行文件
    # （例如未安装 `npm`）。OSError：权限不足、管道中断等。
    # 两者都会作为错误信息返回，让模型看见问题，
    # 并可能尝试另一种方案。
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"


# ── 核心模式：agent 循环 ──────────────────────────────────────────
#
# 这个函数本身就是 agent。它实现了所有 AI coding agent 的基础模式：
#
#   1. 把对话 + 工具发送给 LLM
#   2. 如果 LLM 返回文本（而不是工具调用），就结束
#   3. 如果 LLM 调用工具，就执行工具、追加结果，
#      然后回到第 1 步
#
# 这个循环会持续到模型产生非 "tool_use" 的 stop_reason 为止，
# 通常是 "end_turn"（模型认为完成了）或 "stop_sequence"
# （模型命中了自定义停止序列）。
#
# 对话状态：
#   `messages` 列表会被原地修改。每次迭代都会追加：
#     - 一条包含模型响应的 "assistant" 消息（可能包含文本块和/或 tool_use 块）
#     - 一条包含 tool_result 块的 "user" 消息（每个工具调用一个结果）
#   每一轮都会把累积历史重新发给 API，
#   让模型拥有目前为止发生过的一切上下文。
#
# API 成本提示：
#   每一轮都会把完整消息历史重新发送给 API。
#   Anthropic 的 prompt caching 可以显著降低重复前缀的成本，
#   但这个简单实现没有使用它。
#   长对话的单轮成本会越来越高。
#
def agent_loop(messages: list):
    """
    运行 agent 循环：反复调用 LLM、执行工具并回传结果，
    直到模型生成最终文本响应。

    参数：
        messages: Anthropic API 格式的对话消息列表。
                  每条消息都是包含 "role" 和 "content" 的 dict。
                  这个列表会被原地修改：工具结果和 assistant 响应都会追加进去。
                  返回时，最后一条消息会是模型的最终文本响应。

    返回：
        None。最终响应位于 messages[-1]["content"]。
    """
    # ── 外层循环：一次迭代 = 一次 LLM 调用 + 一轮工具执行 ──
    # 这个循环没有显式迭代计数器，会按模型需要运行任意轮。
    # 简单的“列文件”任务可能只需 1 次迭代；
    # 复杂的“重构这个模块”任务可能需要 20 多次迭代。
    while True:
        # ── 第 1 步：调用 LLM ─────────────────────────────────────
        # client.messages.create() 会向 Anthropic API 发送同步 HTTP 请求。
        # 参数：
        #
        #   model=MODEL   → 要使用的 Claude 模型（来自环境变量）
        #   system=SYSTEM → 系统提示词（人设/行为）；它位于对话之上，
        #                    不在 message 列表里。
        #                    API 会把它当作独立且持续生效的指令层。
        #   messages=messages → 到目前为止的完整对话历史。
        #                        首次调用时，它通常只是 [{"role":"user",
        #                        "content":"..."}]。后续调用时，
        #                        它会包含所有前序轮次和工具结果。
        #   tools=TOOLS   → 模型可以选择调用的工具定义。
        #                    模型看到这些定义后，会决定是调用工具还是返回文本。
        #   max_tokens=8000 → 响应长度上限（不是输入长度）。
        #                      如果模型还想说更多，必须停止并在下一轮继续。
        #
        # response 对象包含：
        #   - response.content：内容块列表（text + tool_use）
        #   - response.stop_reason：模型停止生成的原因
        #     （"end_turn"、"tool_use"、"max_tokens"、"stop_sequence"）
        #   - response.id、response.model、response.usage：元数据
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )

        # ── 第 2 步：记录 assistant 的响应 ─────────────────────────
        # 将完整响应内容追加到对话历史中。
        # 它可能包含：
        #   - TextBlock 对象（type="text"）：模型的文本响应
        #   - ToolUseBlock 对象（type="tool_use"）：模型希望我们执行的工具调用
        # 单个响应可以包含多个内容块，例如模型可能先输出一些解释文本，
        # 然后在同一轮中调用工具。
        messages.append({
            "role": "assistant",
            "content": response.content,
        })

        # ── 第 3 步：检查是否完成 ─────────────────────────────────
        # stop_reason 告诉我们模型为什么停止生成。
        #
        #   "tool_use"     → 模型想调用一个或多个工具。
        #                     继续循环：执行工具，再把结果回传。
        #   "end_turn"     → 模型认为已经完成，并生成了最终答案。
        #                     退出循环；最后一条消息包含答案。
        #   "max_tokens"   → 模型在响应中途触及 max_tokens 限制。
        #                     在生产级 agent 中，通常会继续循环
        #                     （模型可能还想调用工具但 token 不够）。
        #                     这里为了简单起见，把它当作完成。
        #   "stop_sequence" → 模型命中了自定义停止序列（此处未使用）。
        #
        # 当 stop_reason 不是 "tool_use" 时就返回：
        # 对话已经完成，最终文本位于 messages[-1]["content"]。
        if response.stop_reason != "tool_use":
            return

        # ── 第 4 步：执行每个工具调用 ───────────────────────────────
        # response.content 列表可能包含多个块。
        # 我们会遍历所有块：
        #   - 跳过文本块（它们只是模型的说明，
        #     已经保存在对话历史中）
        #   - 执行 tool_use 块：提取命令，
        #     通过 run_bash() 运行，并收集结果
        #
        # 每个 tool_use 块包含：
        #   - block.type："tool_use"
        #   - block.id：唯一标识符（用于把结果匹配回对应调用）
        #   - block.name：工具名（"bash"）
        #   - block.input：匹配 input_schema 的参数 dict
        #                  （这里是 {"command": "..."}）
        results = []
        for block in response.content:
            if block.type == "tool_use":
                # ── 打印正在执行的命令 ───────────────────────────
                # 使用黄色文本（\033[33m）和 "$" 前缀模拟终端提示符。
                # 这样用户可以看见 agent 正在做什么。
                print(f"\033[33m$ {block.input['command']}\033[0m")

                # ── 执行命令 ─────────────────────────────────────
                # run_bash() 会处理安全检查、执行、超时和输出截断。
                output = run_bash(block.input["command"])

                # ── 显示输出预览 ─────────────────────────────────
                # 只向终端打印前 200 个字符，
                # 让用户能看见发生了什么，同时避免刷屏。
                # 完整输出（最多 5 万字符）会发送给模型。
                print(output[:200])

                # ── 构造 tool_result 块 ───────────────────────────
                # API 要求工具结果采用这个格式：
                #   - type："tool_result"（告诉 API 这是一个结果）
                #   - tool_use_id：必须匹配 tool_use 块的 id，
                #     这样模型才知道这个结果属于哪个工具调用
                #   - content：输出字符串（或内容块列表）
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })

        # ── 第 5 步：回传结果并继续循环 ────────────────────────────
        # 将所有工具结果作为一条 "user" 角色消息追加进去。
        # API 期望工具结果来自 "user" 角色：
        # 这是对话框架中的设定，即用户（我们的 agent 外壳）
        # 代替 assistant 执行了工具，并把结果报告回来。
        #
        # 追加完成后，循环回到第 1 步：
        # 下一次 client.messages.create() 调用会包含这些结果，
        # 然后模型可以：
        #   - 继续调用工具（如果还需要更多信息）
        #   - 生成最终文本答案（如果已经拿到所需信息）
        #   - 两者兼有（同一轮中既有文本说明，也有另一个工具调用）
        messages.append({"role": "user", "content": results})


# ── 入口点 / REPL ─────────────────────────────────────────────────
# 当脚本被直接执行（而不是被导入）时，会运行这个代码块。
# 它提供一个简单的读取-求值-打印循环（REPL），用于和 agent 交互。
if __name__ == "__main__":
    print("s01: Agent Loop")
    print("输入问题，回车发送。输入 q 退出。\n")
    # 翻译：“输入你的问题，按回车发送。输入 q 退出。”

    # `history` 是对话状态。它会在同一个会话的多次用户提问之间持续存在，
    # 因此模型能记住之前讨论过的内容。每次用户提问都会追加一条 user 消息，
    # 随后 agent_loop() 会追加 assistant 消息和工具消息。
    history = []

    # ── REPL 循环 ─────────────────────────────────────────────────
    while True:
        try:
            # ── 读取用户输入 ─────────────────────────────────────
            # 使用青色提示符（\033[36m）和 "s01 >>" 标签。
            # input() 会阻塞，直到用户按下回车。
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            # EOFError：用户按下 Ctrl-D（Unix）或 Ctrl-Z+Enter（Windows）
            # KeyboardInterrupt：用户按下 Ctrl-C
            # 两者都表示“我结束了” → 跳出 REPL 循环
            break

        # ── 检查退出命令 ─────────────────────────────────────────
        # 空输入或 "q"/"exit"（不区分大小写）都会退出。
        # .strip() 用于处理只包含空白字符的输入。
        if query.strip().lower() in ("q", "exit", ""):
            break

        # ── 将用户消息追加到历史中 ───────────────────────────────
        # 用户的原始文本会成为一条 "user" 角色消息。
        # 这是新任务或追问的入口点。
        history.append({"role": "user", "content": query})

        # ── 运行 agent 循环 ─────────────────────────────────────
        # 这里是核心过程。agent_loop() 会：
        #   1. 将完整历史发送给 LLM
        #   2. 执行模型请求的所有工具
        #   3. 循环直到模型生成最终答案
        # 所有中间消息（assistant 响应、工具调用、工具结果）
        # 都会原地追加到 `history`。
        agent_loop(history)

        # ── 打印最终文本响应 ─────────────────────────────────────
        # agent_loop() 返回后，历史中的最后一条消息
        # 就是 assistant 的最终响应。它的 content 是内容块列表
        # （即使只有一个块也是列表）。
        #
        # 我们只需要提取文本块并打印。
        # tool_use 块在这里会被跳过，因为它们已经在循环中执行，
        # 并且输出也已经显示过。
        #
        # `history[-1]` = 最后一条 assistant 消息
        # `history[-1]["content"]` = TextBlock/ToolUseBlock 对象列表
        # 我们会遍历并只打印 type == "text" 的块。
        # getattr(block, "type", None) 可以安全处理 block 是普通 dict
        # 而不是类型化对象的情况（API 版本差异）。
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if getattr(block, "type", None) == "text":
                    print(block.text)
        # 在下一个提示符前打印空行，形成视觉分隔
        print()
