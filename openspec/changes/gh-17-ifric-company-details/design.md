# Design

## Context

`management-api.md`, "IFRIC details", gives the contract. The issue fixes the field names, the client and the cache. The registry's route returns a plain array of companies, with `company_ifric_id`, `company_name`, `company_category`, `company_city` and `company_country`, and any of the last four can be absent.

## Decisions

### One lookup, shared and cached

A single fetch answers all reads. Concurrent reads wait for it, so an expiry causes one call to the registry. A read never waits more than the 5 second timeouts of the token and company calls.

**A failure is cached too, for a shorter time, up to 30 seconds.** Otherwise each read would wait out the timeouts while IFRIC is down, and the screens depend on these reads. Alternatives: keeping the last good result after a failure, which the issue's "those fields are left out" rules out; caching a failure for the full time, which would hide a recovered service for 5 minutes.

### Fields are left out, not null

A read has a field only if IFRIC gave a value. `participant_id`, and the rest of the record, come from the registry as before. Only reads are enriched: `GET /api/participants`, `/api/participants/{id}` and `/api/participants/compatible/{id}`. The answer to `POST /api/participants` is what was written, so a re-registration through the UI can't carry these into the participant registry.

### Configuration

IFRIC counts as configured only with `IFRIC_BACKEND_URL`, `IFRIC_READER_CLIENT_ID` and `IFRIC_READER_CLIENT_SECRET` all set. Tokens come from the same Keycloak, at `KEYCLOAK_URL`, through the client-credentials grant.

### A token with no roles

The `dataspace-ifric-reader` client has none, as `keycloak.md` says. The registry documents this route as readable with any valid token.

## Architectural implications

None for the agent path. This only adds to reads on the management API, and the rest of a read doesn't depend on IFRIC.

## Risks

- The registry runs separately, and its token check isn't exercised here unless an installation has one. End-to-end checks use a stand-in for it with real Keycloak tokens.
- Every company is read on each refresh. This matches the route the issue names.

## Conflicts

`AGENTS.md` asks for the `spec-approved` label before implementation. A maintainer approved this milestone outside GitHub and the label is pending, as the Pull Request states.
