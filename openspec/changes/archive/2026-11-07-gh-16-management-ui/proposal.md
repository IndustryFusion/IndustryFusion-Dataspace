# Proposal

Issue: #16

## Why

Administrators have only HTTP routes for the dataspace. They need screens for its health, its participants and its policies.

## What Changes

- Add a React 18 and Vite application in `management/ui`, with Health, Participants and Policies screens.
- Serve the built files from the management API, and build them into its image.
- Add admin mode: tokens fetched and refreshed through `/api/admin/token`, with the secret held in memory only.
- Add browser tests that drive each screen against the API, and run them in CI.

## Capabilities

### New Capabilities

- `management-ui`: The screens, admin mode, and how the UI is served.

### Modified Capabilities

None.

## Out of Scope

- Logging in as a user. Admin mode uses the `dataspace-admin-cli` client, as the issue says.
- Capability defaults and the raw per-participant capability routes, which the issue's Policies screen doesn't list.
- Restricting who can read the screens (#20).
- A new API route. Setting reachability uses the existing `POST /api/participants`.

## Impact

- `manifest.md`: none affected.
- `architecture.md`, "Management GUI": delivered as written.
- `management-api.md`: none changed.
