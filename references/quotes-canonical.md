# Canonical Quotes — Verbatim Anthropic Doctrine

For citation in reports. Each quote is verbatim and traceable to the Anthropic source page declared in `references/rules-anthropic.yaml § meta.source_attribution`.

## Top 25 Most-Cited Quotes (skill-local quick access)

### On Clarity

> "Think of Claude as a brilliant but new employee who lacks context on your norms and workflows. The more precisely you explain what you want, the better the result."
> — *prompt-engineering/claude-prompting-best-practices, Be clear and direct*

> "Golden rule: Show your prompt to a colleague with minimal context on the task and ask them to follow it. If they'd be confused, Claude will be too."
> — *Be clear and direct*

> "Tell Claude what to do instead of what not to do."
> — *Control the format of responses*

### On Newer-Model Calibration

> "Where you might have said 'CRITICAL: You MUST use this tool when...', you can use more normal prompting like 'Use this tool when...'."
> — *Tool usage (scoped to Opus 4.5/4.6 on the live page)*

> "Claude Opus 4.8 interprets prompts literally and explicitly, particularly at lower effort levels. It does not silently generalize an instruction from one item to another, and it does not infer requests you didn't make."
> — *prompting-claude-opus-4-8, More literal instruction following (same sentence for Sonnet 5 on its page; updated 2026-07-11)*

> "If you need Claude to apply an instruction broadly, state the scope explicitly (for example, 'Apply this formatting to every section, not just the first one')."
> — *prompting-claude-opus-4-8, More literal instruction following*

### On XML Structure

> "XML tags help Claude parse complex prompts unambiguously, especially when your prompt mixes instructions, context, examples, and variable inputs."
> — *Structure prompts with XML tags*

### On Examples

> "Examples are one of the most reliable ways to steer Claude's output format, tone, and structure."
> — *Use examples effectively*

> "Include 3–5 examples for best results."
> — *Use examples effectively*

### On Long Context

> "Place your long documents and inputs near the top of your prompt, above your query, instructions, and examples. Queries at the end can improve response quality by up to 30% in tests."
> — *Long context prompting*

> "As token count grows, accuracy and recall degrade, a phenomenon known as context rot."
> — *context-windows*

### On Thinking & Reasoning

> "Prefer general instructions over prescriptive steps. A prompt like 'think thoroughly' often produces better reasoning than a hand-written step-by-step plan."
> — *Leverage thinking*

> "If you observe shallow reasoning on complex problems, raise effort to `high` or `xhigh` rather than prompting around it."
> — *Calibrating effort and thinking depth*

### On Hallucination Reduction

> "Allow Claude to say 'I don't know': Explicitly give Claude permission to admit uncertainty."
> — *reduce-hallucinations*

> "Never speculate about code you have not opened. If the user references a specific file, you MUST read the file before answering."
> — *Minimizing hallucinations in agentic coding*

### On Skills Authoring

> "Default assumption: Claude is already very smart. Only add context Claude doesn't already have."
> — *agent-skills/best-practices*

> "Always write in third person. The description is injected into the system prompt, and inconsistent point-of-view can cause discovery problems."
> — *agent-skills/best-practices*

> "Keep SKILL.md under 500 lines for optimal performance."
> — *agent-skills/best-practices*

> "Claude has a tendency to 'undertrigger' skills... please make the skill descriptions a little bit 'pushy'."
> — *github.com/anthropics/skills/skill-creator*

> "If you find yourself writing ALWAYS or NEVER in all caps, or using super rigid structures, that's a yellow flag — if possible, reframe and explain the reasoning."
> — *github.com/anthropics/skills/skill-creator*

### On CLAUDE.md Doctrine

> "Target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence."
> — *code.claude.com/docs/en/memory*

> "Bloated CLAUDE.md files cause Claude to ignore your actual instructions! For each line, ask: 'Would removing this cause Claude to make mistakes?' If not, cut it."
> — *code.claude.com/docs/en/best-practices*

> "You can tune instructions by adding emphasis (e.g., 'IMPORTANT' or 'YOU MUST') to improve adherence."
> — *code.claude.com/docs/en/best-practices*

### On Hooks

> "Use hooks for actions that must happen every time with zero exceptions. Unlike CLAUDE.md instructions which are advisory, hooks are deterministic and guarantee the action happens."
> — *code.claude.com/docs/en/best-practices*

> "For most hook events, only exit code 2 blocks the action. Exit code 1 is treated as non-blocking error and proceeds, contrary to Unix convention."
> — *code.claude.com/docs/en/hooks*

### On Subagents

> "Subagents receive only this system prompt (plus basic environment details like working directory), not the full Claude Code system prompt."
> — *code.claude.com/docs/en/sub-agents*

> "Subagents cannot spawn other subagents."
> — *code.claude.com/docs/en/sub-agents*

### On Building Effective Agents

> "Workflows offer predictability and consistency for well-defined tasks, whereas agents are the better option when flexibility and model-driven decision-making are needed."
> — *anthropic.com/engineering/building-effective-agents*

> "Include stopping conditions (maximum iterations) to maintain control."
> — *building-effective-agents*

> "Poka-yoke your tools. Change the arguments so that it is harder to make mistakes."
> — *building-effective-agents*

### On Verification

> "Include tests, screenshots, or expected outputs so Claude can check itself. This is the single highest-leverage thing you can do."
> — *code.claude.com/docs/en/best-practices*

> "If you can't verify it, don't ship it."
> — *code.claude.com/docs/en/best-practices*

### On Tool Use

> "Provide extremely detailed descriptions. This is by far the most important factor in tool performance."
> — *agents-and-tools/tool-use/define-tools*

> "If you intend to call multiple tools and there are no dependencies between the tool calls, make all of the independent tool calls in parallel."
> — *Optimize parallel tool calling*

> "Never use placeholders or guess missing parameters in tool calls."
> — *Optimize parallel tool calling*
