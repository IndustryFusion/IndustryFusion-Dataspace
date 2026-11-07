# Proposal

Issue: #14

## Why

Onboarding a participant today means running a script against the cluster. `architecture.md` promises one API call that provisions everything, and one call that removes it again, and `management-api.md` publishes that contract. Nothing implements it yet.

## What Changes

- Implement every route in `management-api.md` under `/api`, on port 3000, except the IFRIC fields, which #17 adds.
- Provision a hosted participant in the published order: databases, Keycloak, Kubernetes objects, registry entry. Undo completed steps on failure. An external participant gets the Keycloak and registry steps only.
- Remove a participant completely with `DELETE /api/participants/{id}`.
- Admin routes check the caller's token, and use that same token for the Keycloak Admin API. The service stores no data of its own.
- Forward capability routes to a hosted participant's adapter, with `ADAPTER_INTERNAL_KEY`.
- Add the management service to the local environment, so that it can be verified on a cluster.

## Capabilities

### New Capabilities

- `management-api`: Administration routes, participant provisioning and removal, and the capability views for administrators.

### Modified Capabilities

None.

## Out of Scope

- IFRIC company details (#17), the management UI (#16), and Helm packaging (#15).
- The `peer` route for capability calls and using `peer_notify_url` for them (#18).
- Restricting the unauthenticated reads (#20).
- Routing in the DSP gateway (#18). The API only reports its health.

## Impact

- `manifest.md`: none affected.
- `architecture.md`, "Adding a Participant" and "Management GUI": delivered as written.
- `management-api.md`: delivered. Additions are listed in `design.md`: what `DEMO_PARTICIPANTS` and `RESOURCES_PARTICIPANT_*` hold, the shape of `GET /api/policy` and `GET /api/health`, and `409` in two more cases.
- `keycloak.md`: gains a note that a participant's client is marked, so that other clients in a shared realm are left alone.
