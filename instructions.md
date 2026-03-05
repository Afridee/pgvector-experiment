# How to Write API Knowledge Chunks

This file explains how to write and maintain `knowledge_chunks.txt` — the knowledge base that the agent uses to understand available API endpoints, required parameters, payload structures, authentication, and response shapes.

---

## What is this file?

It's a plain text file containing a list of **knowledge chunks**. Each chunk teaches the agent one specific thing about an API — an endpoint, its parameters, its response format, an auth rule, an edge case, etc.

When the agent receives a request, it searches this file semantically and retrieves the most relevant chunks **before making any API call**. The agent relies entirely on these chunks to know:
- Which endpoint to call
- What parameters are required vs. optional
- How to build the payload or query string
- What the response looks like (including any download URLs)

**The better your chunks are written, the better the agent performs.**

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
- Think of it as the heading of an API reference section

✅ Good:
```text
title: Sales Report API — Endpoint and Method
title: Sales Report API — Required Parameters
title: Authentication — Bearer Token Header
title: Report Response — Download URL Handling
```

❌ Avoid:
```text
title: Rule 1
title: Important
title: API stuff
```

---

### `tags`
A comma-separated list of labels. Used for your own organization — they don't directly control agent behavior, but they help retrieval slightly and keep the file readable as it grows.

Recommended prefixes:

| Prefix | Purpose | Examples |
|--------|---------|---------|
| `topic:` | What the chunk is about | `topic:endpoint`, `topic:auth`, `topic:parameters`, `topic:response` |
| `applies_to:` | Which endpoint or scope it applies to | `applies_to:sales_report`, `applies_to:all` |
| *(free tag)* | Any extra label | `api_template`, `business_rule`, `edge_case` |

Example:
```text
tags: topic:parameters, applies_to:sales_report, business_rule
```

> **Note:** Tags are just labels for humans and loose retrieval hints. What actually matters for the agent is the `title` and `content`.

---

### `content`
The actual instructions. This is what the agent reads and follows.

**Write it as direct instructions to the agent:**
- Use "You must...", "Do NOT...", "When X then Y"
- Be explicit — don't assume the agent will infer things
- Include JSON payload examples and response examples where relevant (use fenced code blocks)
- Keep each chunk focused on **one topic**

---

## Full Example

```text
---
title: Sales Report API — Endpoint and Method
tags: topic:endpoint, applies_to:sales_report, api_template
content:
To generate a sales report, make a POST request to:

  https://api.example.com/v1/reports/sales

You MUST include the following header:
  Content-Type: application/json

The auth token is injected automatically from the API_TOKEN environment variable.
Do NOT ask the user for the token.

Example request:

```json
{
  "region": "Dhaka",
  "start_date": "2025-01-01",
  "end_date": "2025-01-31",
  "product_type": "SKU"
}
```
---

---
title: Sales Report API — Required Parameters
tags: topic:parameters, applies_to:sales_report, business_rule
content:
Before calling the Sales Report API, you MUST collect all of the following from the user:

- region       : string — the region name (e.g. "Dhaka", "Rajshahi")
- start_date   : string in YYYY-MM-DD format — start of the reporting period
- end_date     : string in YYYY-MM-DD format — end of the reporting period (inclusive)
- product_type : string — either "SKU" or "Total"

If ANY of these are missing, ask the user for them BEFORE calling the API.
Do NOT use placeholder or default values.
---

---
title: Sales Report API — Response and Download Link
tags: topic:response, applies_to:sales_report
content:
A successful Sales Report API response (HTTP 200) looks like:

```json
{
  "status": "success",
  "report_id": "abc123",
  "download_url": "https://files.example.com/reports/abc123.xlsx",
  "generated_at": "2025-01-15T10:30:00Z"
}
```

If the response contains a "download_url" field, present it to the user as a
clickable download link. Use this format in your reply:

  📥 Your report is ready: [Download Report](https://files.example.com/reports/abc123.xlsx)

If "status" is not "success", or if "download_url" is missing, inform the user
that the report could not be generated and show the error details.
---
```

---

## Rules to Follow

1. **Always start and end each chunk with `---` on its own line.**
2. **Every chunk must have all three fields:** `title`, `tags`, and `content`.
3. **One topic per chunk.** Split endpoint definition, required parameters, optional parameters, and response handling into separate chunks.
4. **Be explicit in content.** The agent has no prior knowledge — if it's not written, it won't know.
5. **Use JSON code blocks** for payload and response examples:
    ````text
    ```json
    { "key": "value" }
    ```
    ````
6. **Don't duplicate.** If a rule already exists in another chunk, reference it by title rather than repeating it.
7. **No blank chunks.** Every chunk must have meaningful content.
8. **Never put auth secrets in chunks.** Auth tokens come from environment variables. Only document the header name and the fact that the token is injected automatically.

---

## Chunk Design Guide — One API, Multiple Chunks

For each API endpoint you should typically write **four chunks**:

| Chunk | What it covers |
|-------|---------------|
| `[Name] — Endpoint and Method` | URL, HTTP method, Content-Type, auth note |
| `[Name] — Required Parameters` | Every field the agent MUST collect from the user before calling |
| `[Name] — Optional Parameters` | Fields that have defaults or can be omitted |
| `[Name] — Response and Download Link` | Response shape, how to present data, how to handle download URLs and errors |

Split further if an endpoint has complex logic (e.g. conditional parameters, pagination, multiple response types).

---

## What Makes a Good Chunk?

| ✅ Good chunk | ❌ Bad chunk |
|---|---|
| Covers exactly one aspect of one endpoint | Mixes endpoint definition with parameter list |
| Written as direct agent instructions | Written as documentation for humans |
| Includes a JSON example | Vague, no examples |
| Specific, descriptive title | Generic title like "API Rules" |
| Explicit about which params are required vs. optional | Leaves it ambiguous |
| States what to do with download URLs | Assumes the agent will figure it out |

---

## After Adding or Editing Chunks

Every time you change this file, you **must re-run ingestion** to update the vector embeddings:

```bash
uv run python ingest.py
```

If you skip this step, the agent will still use the old version.

---

## Quick Checklist

Before saving the file, verify:

- [ ] Every chunk starts and ends with `---`
- [ ] Every chunk has `title`, `tags`, and `content`
- [ ] No two chunks cover the exact same topic
- [ ] JSON examples use fenced code blocks
- [ ] Required vs. optional parameters are clearly separated
- [ ] Auth secrets are NOT in the chunks (env vars only)
- [ ] Download URL handling is documented in the response chunk
- [ ] Ingestion has been re-run after changes

---

## Current Chunk List

Update this table whenever you add or remove a chunk.

| Title | Topic | Applies To |
|-------|-------|------------|
| *(add your chunks here)* | | |

> **Tip:** Group rows by endpoint name for readability.