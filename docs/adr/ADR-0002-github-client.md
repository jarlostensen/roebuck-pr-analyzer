# ADR-0002: Use PyGithub as the GitHub API client

> This ADR was created retrospectively to document an existing decision.

- **Status**: accepted
- **Date**: 2026-03-13 (retrofitted)

## Context

All four analysers need to fetch data from GitHub: PR diffs, file commit histories, repository trees, and tag comparisons. A client library is needed to abstract the GitHub REST API.

## Decision

Use **PyGithub** (`github` package) as the GitHub REST API wrapper.

## Considered options

- **Raw `httpx` / `requests`** — full control, no abstraction; requires hand-rolling pagination, auth, and response parsing for every endpoint
- **PyGithub** — high-level object model for repos, PRs, commits, tags; handles pagination transparently
- **GitHub GraphQL API** — more efficient (fetch exactly what is needed in one request), but requires writing GraphQL queries and a different client

## Consequences

**Pros:**
- High-level API reduces boilerplate for common operations (`repo.get_pull()`, `repo.get_commits()`, `repo.compare()`)
- Handles pagination automatically (important for commit lists)
- `RateLimitExceededException` is a first-class exception, making rate-limit handling explicit

**Cons:**
- Synchronous only — concurrency requires `ThreadPoolExecutor` (used in `SpecLoader`)
- Churn analysis iterates commits then fetches each commit's file list, which is O(commits) in API calls; the REST API does not support an efficient "files changed per commit in date range" query
- Diff reconstruction from per-file patches loses some unified diff metadata (hunk context headers)
