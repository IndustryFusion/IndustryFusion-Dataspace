# Design

## Context

`architecture.md`, "Management GUI", and the issue describe the screens. `management-api.md` is the contract they use, and reachability has no route of its own. Company details come from #17, and the screens work without them.

## Decisions

### Served by the API, from one image

The image builds the UI in a first stage, and copies the result in. So its build context becomes `management/`, with the Dockerfile still at `management/api/Dockerfile`. CI and `scripts/local-env.sh` follow.

A path that isn't a file gets `index.html`, except under `/api/`, which keeps its JSON `404`. A path that resolves outside the folder never gets a file. Without a built UI, as in tests of the API alone, `/` gives a `404` that says so.

Alternative: a separate web server image. Rejected, as the issue says it is served by the management API image.

### The secret stays in memory

The secret stays in a reference inside the provider component, and is used for fetching and refreshing tokens. Nothing goes to browser storage or a cookie, so reloading the page leaves admin mode, as intended.

A token is refreshed 30 seconds before it expires. A `401` on a call fetches a new one, and tries once more. If a scheduled refresh fails, admin mode ends and the user enters it again.

Alternative: asking again at each expiry. Rejected, as the issue asks for refreshed tokens.

### What admin actions do

| Action | Call |
|---|---|
| Register, set reachability | `POST /api/participants` |
| Demo | `POST /api/demo` |
| Show credentials | `GET /api/participants/{id}/credentials` |
| Delete, after a confirmation | `DELETE /api/participants/{id}` |
| Approve, deny | `POST /api/participants/{provider}/approvals`, which replaces any decision |
| Reset | `PATCH /api/participants/{provider}/approvals/{id}`, only with a decision to reset |

Approve and deny use `POST` instead of `PATCH`, as `PATCH` gives `409` on a resolved request, and these buttons are for changing a decision too.

### Dependencies

`react` and `react-dom` at runtime. `vite`, its React plugin and `@playwright/test` for development. No router or state library, as three screens don't need one.

### Browser tests

Tests run a real browser against the real API code with the built UI. Behind the API are the in-memory stand-ins that its own tests use, reached through its real HTTP clients. A test-only server adds routes for setting up a test, and is not part of the image. So CI needs no cluster. `UI_BASE_URL` runs the same tests against a deployment, skipping those that need the stand-ins.

`@playwright/test` is pinned exactly, as a version needs its own browser build.

## Conflicts

`AGENTS.md` asks for the `spec-approved` label before implementation. A maintainer approved this milestone outside GitHub and the label is pending, as the Pull Request states.
