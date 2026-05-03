---
description: A helper agent
---

# Bad Subagent Fixture

Violates: AR-CC-041 (missing name), AR-CC-043 (tries to spawn subagent), AR-CC-044 (vague description, no routing signal).

## Instructions

When asked to investigate something, delegate the work using Task() to spawn another agent.

Use the @agent-investigator subagent to handle deep dives.

If unclear, ask the @agent-clarifier for help.
