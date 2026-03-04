# How to Write QMR Semantic Knowledge Chunks

This file explains how to write and maintain `qmr_semantic_knowledge_chunks.txt` — the knowledge base that the QMR agent uses to understand business rules, SQL templates, and query logic.

---

## What is this file?

It's a plain text file containing a list of **knowledge chunks**. Each chunk teaches the agent one specific thing — a rule, a template, a mapping, an edge case, etc.

When the agent receives a question, it searches this file semantically and retrieves the most relevant chunks before generating SQL or answering. So **the better your chunks are written, the better the agent performs**.

---

## File Format

The file is a list of chunks separated by `---` on its own line.

```text
---
title: Your Chunk Title
tags: topic:your_topic, applies_to:all
content:
Your instructions here.
---
```

Every chunk has exactly three fields: `title`, `tags`, and `content`. That's it.

---

## The Three Fields

### `title`
A short, descriptive name for the chunk.

- Be specific — the agent uses the title to judge relevance
- Use plain English, no abbreviations
- Think of it as the heading of a rule book section

✅ Good:
```text
title: QMR Primary Query Template (Per-Table SELECT)
title: QMR Null and Empty Filter Handling
title: QMR Cross-Year Date Range Rules
```

❌ Avoid:
```text
title: Rule 1
title: Important
title: SQL stuff
```

---

### `tags`
A comma-separated list of labels. Used for your own organization — they don't directly control agent behavior, but they help retrieval slightly and keep the file readable as it grows.

Recommended prefixes:

| Prefix | Purpose | Examples |
|--------|---------|---------|
| `topic:` | What the chunk is about | `topic:filters`, `topic:date_split`, `topic:product_type` |
| `applies_to:` | Which scope it applies to | `applies_to:sku`, `applies_to:total`, `applies_to:all` |
| *(free tag)* | Any extra label | `sql_template`, `business_rule`, `edge_case` |

Example:
```text
tags: topic:filters, applies_to:all, business_rule
```

> **Note:** Tags are just labels for humans and loose retrieval hints. What actually matters for the agent is the `title` and `content`.

---

### `content`
The actual instructions. This is what the agent reads and follows.

**Write it as direct instructions to the agent:**
- Use "You must...", "Do NOT...", "When X then Y"
- Be explicit — don't assume the agent will infer things
- Include SQL examples where relevant (use fenced code blocks)
- Keep each chunk focused on **one topic**

---

## Full Example

```text
---
title: QMR Null and Empty Filter Handling
tags: topic:filters, applies_to:all, business_rule
content:
When a filter list contains empty strings or null-like values (e.g. '', 'null', 'none'),
strip them before building the SQL IN clause.

If after stripping the list is empty, omit the filter entirely.
Do NOT generate: AND o.region IN ('')

Example of correct behaviour:
- regionFilter = ['Dhaka', '', 'Rajshahi'] -> AND o.region IN ('Dhaka', 'Rajshahi')
- regionFilter = [''] or ['all']           -> omit filter entirely
---
```

---

## Rules to Follow

1. **Always start and end each chunk with `---` on its own line.**
2. **Every chunk must have all three fields:** `title`, `tags`, `content`.
3. **One topic per chunk.** If a chunk is covering two different things, split it into two.
4. **Be explicit in content.** The agent has no prior knowledge — if it's not written, it won't know.
5. **Use SQL code blocks** for any template or example SQL:
    ````text
    ```sql
    SELECT ...
    ```
    ````
6. **Don't duplicate.** If a rule already exists in another chunk, reference it in the title rather than repeating it (e.g. "see ProductType Mapping chunk").
7. **No blank chunks.** Every chunk must have meaningful content.

---

## What Makes a Good Chunk?

| ✅ Good chunk | ❌ Bad chunk |
|---|---|
| Covers exactly one rule or template | Mixes multiple unrelated topics |
| Written as direct agent instructions | Written as documentation for humans |
| Includes an example or SQL snippet | Vague, no examples |
| Specific, descriptive title | Generic title like "Rules" |
| Explicit about edge cases | Assumes the agent will figure it out |

---

## After Adding or Editing Chunks

Every time you change this file, you **must re-run ingestion** to update the vector embeddings:

```bash
uv run python ingest.py
```

If you skip this step, the agent will still use the old version.

---

## Quick Checklist

Before sending the file, verify:

- [ ] Every chunk starts and ends with `---`
- [ ] Every chunk has `title`, `tags`, and `content`
- [ ] No two chunks cover the exact same topic
- [ ] SQL examples use fenced code blocks
- [ ] Ingestion has been re-run after changes

---

## Current Chunk List (as of March 2026)

| Title | Topic | Applies To |
|-------|-------|------------|
| QMR SQL Template Overview (Must Follow) | overview | all |
| QMR Year Table Selection Rules | date_split | all |
| QMR ProductType Mapping | product_type | all |
| QMR Filters Template | filters | all |
| QMR Primary Query Template (Per-Table SELECT) | primary_query | all |
| QMR Primary Query Template (Union + Outer Aggregate) | primary_query_outer | all |
| QMR Retailer Order Query Template (Per-Table SELECT) | retailer_query | sku |
| QMR Retailer Order Query Template (Union + Outer Aggregate) | retailer_query_outer | sku |
| QMR Retailer Order Query Template (Total ProductType) | retailer_query | total |

> Update this table whenever you add or remove a chunk.