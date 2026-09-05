# FindSkills API Reference

Source basis:

- `https://findskills.org/llms.txt`
- `https://findskills.org/api/v1/stats`
- sample public responses from:
  - `GET /api/v1/search?q=design&limit=3`
  - `GET /api/v1/skills?category=search&limit=3`
- background docs entry:
  - `https://findskill.com/docs/overview`

## Recommended Access Pattern

Preferred:

```text
npx -y findskills-mcp
```

Fallback:

- `GET https://findskills.org/api/v1/search?q={keyword}&limit=20`
- `GET https://findskills.org/api/v1/skills?category={category}&limit=20`
- `GET https://findskills.org/api/v1/skills/{id}`
- `GET https://findskills.org/api/v1/stats`

## Public Constraints

- Do not crawl or download the full dataset.
- Rate limit: 30 requests/minute/IP.
- Responses are cached for 5 minutes.
- Public responses may omit richer metadata such as URL, author, and stars.

## Current Public Stats

Observed from `GET /api/v1/stats` on 2026-04-10:

- `total_skills`: `39749`
- `last_updated`: `2026-04-09`

Category counts:

- `search`: `805`
- `coding`: `1896`
- `data`: `1143`
- `communication`: `2262`
- `media`: `3798`
- `automation`: `2725`
- `security`: `1347`
- `ai-ml`: `3757`
- `devops`: `1234`
- `finance`: `1369`
- `productivity`: `1698`
- `integration`: `1843`
- `other`: `15869`

Source counts:

- `manual`: `6`
- `github`: `10524`
- `clawhub`: `26846`
- `smithery`: `2373`

## Sample Search Response Shape

Example:

```text
GET /api/v1/search?q=design&limit=3
```

Observed fields:

- `skills[]`
- `skills[].name`
- `skills[].description`
- `skills[].tags`
- `skills[].category`
- `skills[].safety_label`
- `skills[]._hint`
- `total`
- `limit`
- `offset`
- `query`
- `sort`
- `next`

## Sample Category Browse Response Shape

Example:

```text
GET /api/v1/skills?category=search&limit=3
```

Observed fields:

- `skills[]`
- `skills[].name`
- `skills[].description`
- `skills[].tags`
- `skills[].category`
- `skills[].safety_label`
- `skills[]._hint`
- `total`
- `limit`
- `offset`
- `next`

## Usage Guidance

- Search first when the user already knows the task.
- Browse by category when the user is exploring a space.
- Use stats only for context, not as the primary discovery flow.
