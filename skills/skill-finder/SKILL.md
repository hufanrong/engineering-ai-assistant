---
name: skill-finder
description: Find existing agent skills from public directories before inventing or rewriting one. Use when the user asks for a suitable skill, similar skills, installable skills for a task, skill discovery by keyword or category, or wants to compare available skills across public ecosystems.
---

# Skill Finder

Use this skill to discover existing skills from public skill directories instead of guessing what already exists.

Primary source:

- `findskills.org` public directory and API

Background source:

- `findskill.com/docs/overview` is the product documentation entry point and is currently served from Volc CDN infrastructure

## Core Rules

- Prefer the official FindSkills MCP server when available.
- If MCP is not available, use the public HTTP API.
- Do not crawl the full dataset.
- Start with narrow keyword search, then broaden to category browsing only if search results are weak.
- Be explicit about the limits of unauthenticated results: public responses may omit URL, author, star count, and other rich metadata.

## When To Use

Use this skill when the user asks any of the following:

- "find a skill for ..."
- "what skills already exist for ..."
- "search installable skills"
- "compare skill options"
- "is there already a skill for this workflow"
- "find MCP skills", "find agent skills", "find automation skills"

## Workflow

### 1. Clarify the need

Extract:

- task goal
- likely category
- expected execution environment
- whether the user wants discovery only or an import recommendation

### 2. Search first

Prefer keyword search:

```text
GET https://findskills.org/api/v1/search?q={keyword}&limit=20
```

Guidance:

- Start with 1-3 precise keywords.
- Use multiple searches if the task spans different concepts.
- If results are noisy, simplify the query instead of adding too many words.

### 3. Browse by category if needed

If search is sparse or the user is exploring a space:

```text
GET https://findskills.org/api/v1/skills?category={category}&limit=20
```

Available categories include:

- `search`
- `coding`
- `data`
- `communication`
- `media`
- `automation`
- `security`
- `ai-ml`
- `devops`
- `finance`
- `productivity`
- `integration`
- `other`

### 4. Summarize candidates

For each useful candidate, report:

- skill name
- short description
- category
- safety label
- why it matches the task

If the API only returns summary fields, say that directly.

### 5. Recommend next action

Depending on the user intent, end with one of:

- best 3 skills to evaluate further
- best 1 skill to import
- gaps where no strong match exists

## Output Format

Use a compact structure:

```text
Query: ...
Best matches:
1. <skill>
   - Why it matches: ...
   - Category: ...
   - Safety: ...
2. ...

Recommendation:
- ...
```

## Practical Notes

- Public API rate limit is 30 requests per minute per IP.
- Public responses are cached for 5 minutes.
- Without a developer API key, results may include `_hint` telling you richer metadata is available elsewhere.

## References

- Read [references/findskills-api.md](references/findskills-api.md) when you need the concrete endpoints, public response shape, and current dataset stats.
