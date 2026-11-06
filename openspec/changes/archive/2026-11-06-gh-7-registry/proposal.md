# Proposal

Issue: #7

## Why

The gateway needs to find a participant's adapter, and adapters need to know who may talk to whom. The registry answers both, and is the one place role compatibility is decided.

## What Changes

- Implement the registry service: create, read, list, delete, compatibility and health routes.
- Store participants in the service's own PostgreSQL database, creating it if missing, and wait for the database rather than exit.
- Normalize role names to a full IRI, and reject unknown roles.
- Deploy it to the local environment, with no public route.

## Capabilities

### New Capabilities

- `participant-registry`: The directory of participants and the role compatibility rules.

### Modified Capabilities

None.

## Impact

- `registry/`, `deploy/local/`, `scripts/local-env.sh`, `.github/workflows/services.yml`.
- `architecture.md`: "Participant Registry" is implemented as described, with no section changed. `manifest.md`: not affected.

## Out of Scope

- Authentication on the registry, tracked in #20. It is reachable only inside the cluster.
- The separate IFRIC registry.
- Reads through the management API, in #14.
