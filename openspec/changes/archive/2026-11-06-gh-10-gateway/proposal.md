# Proposal

Issue: #10

## Why

Agents need one public address, and a guarantee that a token reaches only its own participant's adapter. The gateway provides both, and with it the first milestone meets the definition of done in `manifest.md`.

## What Changes

- Implement the API Gateway: health, compatible participants, the peer notification route, and the catch-all route to the caller's own adapter.
- Validate tokens against the realm's signing keys, with an exact issuer match, and refetch the keys once on a failure.
- Cache registry lookups for 30 seconds.
- Run the end-to-end exchange through the gateway only.

## Capabilities

### New Capabilities

- `api-gateway`: The single public entry point for agents.

### Modified Capabilities

None.

## Impact

- `gateway/`, `deploy/local/`, `scripts/`.
- `architecture.md`: "API Gateway" is implemented as described. No section changes. `manifest.md`: section 14, Definition of Done, is met for the local environment.

## Out of Scope

- An Ingress, in #15. The local environment reaches the gateway through a port-forward.
- Limits on large bodies through an Ingress, in #11 and #15.
- Authentication of the registry, in #20.
