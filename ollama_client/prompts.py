"""Prompt templates for Ollama interactions.

Stores system prompts, extraction prompts, and consolidation
prompts used by the memory and agent subsystems.
"""

MEMORY_EXTRACTION_PROMPT = """\
You are a memory extraction system. Analyze the following conversation turn \
and extract important information as structured memory cells.

Return a JSON array of memory cells. Each cell must have these fields:
- "scene": a short label grouping related memories (e.g. "project_setup", "user_preferences")
- "cell_type": one of "fact", "plan", "preference", "decision", "task", "risk"
- "salience": a float from 0.0 to 1.0 indicating importance (1.0 = critical)
- "content": a concise statement capturing the information

Rules:
- Return ONLY the JSON array, no other text.
- If nothing worth remembering, return an empty array: []
- Each cell should be self-contained and understandable without context.
- Prefer fewer, higher-quality cells over many low-quality ones.

Conversation turn:
User: {user_message}
Assistant: {assistant_message}
"""

SCENE_CONSOLIDATION_PROMPT = """\
You are a memory consolidation system. Below are all memory cells for the scene \
"{scene}". Summarize them into a single coherent paragraph of 100 words or fewer.

The summary should capture the essential facts, decisions, and context so that \
an agent reading only this summary would understand the scene.

Memory cells:
{cells}

Return ONLY the summary paragraph, no other text.
"""

AGENT_SYSTEM_PROMPT = """\
You are a helpful AI assistant with access to tools for interacting with the \
filesystem and executing commands. You have long-term memory that persists \
across conversations.

Available tools:
- bash: Execute shell commands in a sandboxed environment. Use this to explore \
files, run scripts, and gather information.
- memory_search: Search your long-term memory for relevant past context.

Guidelines:
- Think step by step before acting.
- Use tools when you need concrete information rather than guessing.
- Be concise and direct in your responses.
- If a command fails, analyze the error and try an alternative approach.
- Never execute destructive commands (rm -rf, sudo, etc.) without explicit user confirmation.
"""
