# fetch — Skill

Fetches URLs from the internet and returns clean, token-efficient Markdown content for analysis, quoting, and
reasoning. Use this instead of making raw HTTP calls — the server handles HTML simplification, robots.txt, and
chunked retrieval automatically.

## Tools

- **fetch**: Retrieve a URL and get its content as Markdown (default) or raw HTML.
  - Always start with `raw: false` (default). Only request `raw: true` if you need to inspect the original HTML structure.
  - Use `max_length` to cap output size. Default is 5000 characters — increase only if you need more context.
  - Use `start_index` to paginate through long pages. If a fetch is truncated, re-call with `start_index` set to where the previous response ended.

## Usage Patterns

**Fetch and summarise a page:**
Call `fetch` with the URL. The server returns Markdown — parse it directly without further HTML cleanup.

**Read a long document in chunks:**
First call: `fetch(url=..., max_length=5000)`. If truncated, second call: `fetch(url=..., start_index=5000, max_length=5000)`. Repeat until content ends.

**Check JSON APIs:**
Pass a JSON API endpoint URL. The server returns the raw response body; set `raw: true` to avoid any Markdown conversion on JSON.

## Notes

- The server respects `robots.txt` for model-initiated requests by default. User-initiated requests bypass it.
- Can reach local/internal IPs — be aware of SSRF risk in untrusted contexts.
- Unreachable or non-existent URLs return a clear error message, not a hang.
- No credentials or API keys required.

