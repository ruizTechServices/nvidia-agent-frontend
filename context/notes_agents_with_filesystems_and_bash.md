# Notes: How to Build Agents with Filesystems and Bash

Source: https://vercel.com/blog/how-to-build-agents-with-filesystems-and-bash

## Core Thesis

Replace custom retrieval tooling with filesystem structure and bash commands. Instead of building bespoke retrieval pipelines for every data type, organize data as files and let the agent use standard Unix commands (ls, grep, cat, find) to explore and retrieve context on demand. The model already knows how to use these tools from training — no custom tool logic needed.

## Architecture Pattern

```
Agent receives task
  → Explores filesystem (ls, find)
  → Searches for relevant content (grep)
  → Reads specific files (cat)
  → Sends only relevant context to LLM
  → Returns structured output
```

**Key insight**: The agent treats data like a codebase. It searches for patterns, reads sections, and builds context the same way it would debug code. This leverages native model capabilities rather than bolting on custom behaviors.

## Execution Isolation

The agent and its tool execution run on **separate compute**. The sandbox lets the agent explore files without access to production systems. You trust the agent's reasoning, but the sandbox isolates what it can actually do.

This separation is critical for security — the agent can run bash commands freely within the sandbox without risk to external systems.

## Context Management: Why Filesystems Beat Alternatives

| Approach | Problem |
|---|---|
| **Prompt stuffing** | Hits token limits — cannot fit all data upfront |
| **Vector/semantic search** | Imprecise for structured data requiring specific values (e.g., exact account numbers, dates, config values) |
| **Filesystem + bash** | Minimal context, on-demand loading, precise retrieval |

The agent loads files on demand. A large transcript doesn't go into the prompt upfront. The agent reads metadata, greps for relevant sections, then pulls only what it needs. Context stays minimal through selective file retrieval.

## Data Organization Patterns

### Principle: Structure data to match domain hierarchies

**Customer Support System:**
```
/customers/
  /cust_12345/
    profile.json           # customer metadata
    tickets/
      ticket_001.md        # individual support tickets
      ticket_002.md
    conversations/
      2024-01-15.txt       # interaction history
    preferences.json       # customer preferences
```

**Document Analysis System:**
```
/documents/
  /uploaded/               # raw inputs
  /extracted/              # processed outputs
  /analysis/               # structured results
    summary.md
    key_terms.json
    risk_assessment.md
/templates/                # analysis prompts and rules
```

**Sales Call Summary System:**
```
gong-calls/
  demo-call-001-companyname-product-demo.md
  metadata.json
  previous-calls/
salesforce/
  account.md
  opportunity.md
  contacts.md
slack/
  slack-channel.md
research/
  company-research.md
  competitive-intel.md
playbooks/
  sales-playbook.md
```

### Why These Structures Work

- **Naming conventions carry meaning** — filenames encode entity type, ID, and purpose
- **Directory hierarchy encodes relationships** — a ticket inside a customer folder is implicitly linked
- **Standard formats (JSON, Markdown)** — models parse these natively
- **Separation of raw data, processed data, and templates** — clear data lifecycle

## Agent Behavior Examples

An agent looking for customer objections doesn't need a custom "objection detector" tool:
```bash
grep -i "concern\|worried\|issue\|problem" conversations/2024-01-15.txt
```

An agent examining sales context:
```bash
ls gong-calls/          # see what calls exist
cat metadata.json       # read call metadata
grep -i "objection" demo-call-001-companyname-product-demo.md  # find specific content
```

## Debuggability

When the agent fails, you see exactly what files it read and what commands it ran. The execution path is visible — unlike opaque vector search pipelines where failure modes are hidden.

## Referenced Tools and Libraries

- **AI SDK** — for tool execution and model calls (Vercel's SDK)
- **bash-tool** — open-sourced sandboxed filesystem access tool
- The article demonstrates production usage via a Sales Call Summary template on Vercel

## Key Takeaways for This Project

1. **Don't build custom retrieval for every data type** — structure data as files instead
2. **Leverage Unix commands the model already knows** — grep, cat, find, ls, awk
3. **Sandbox all agent execution** — separate reasoning from tool execution environment
4. **Organize data hierarchically** — directory structure encodes domain relationships
5. **Load context on demand** — never stuff everything into the prompt upfront
6. **Make agent behavior debuggable** — visible execution paths via command history
7. **Use precise retrieval (grep/find) over semantic search** when data is structured and specific values matter
