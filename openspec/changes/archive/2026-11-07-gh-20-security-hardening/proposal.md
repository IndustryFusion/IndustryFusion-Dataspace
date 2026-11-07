# Proposal

Issue: #20

## Why

The system works, and has known gaps that matter once real participants use it. Any pod in the cluster can read a payload or inject a message. Participants share a database user, an S3 identity and an internal key. Connectors can't tell which participant they are talking to. Management reads show who asked for what, and internal addresses.

## What Changes

- `GET /internal/payload/{id}` and `POST /internal/inbox-receive/{id}` need a token for that one message.
- NetworkPolicies limit who reaches adapters, connectors and the registry.
- Each hosted participant gets its own PostgreSQL user, its own S3 identity and its own internal key, replacing the shared `ADAPTER_INTERNAL_KEY`.
- Connectors prove who they are with a Keycloak token instead of the mock identity, and refuse a connector that can't.
- `GET /api/participants/{id}/capabilities` and `GET /api/policy` need an admin token. Other public reads, and the gateway's `/participants/compatible`, leave out internal addresses.
- A management Ingress needs an allowlist.

## Capabilities

### New Capabilities

- `security-hardening`: Each of the above.

### Modified Capabilities

- `api-gateway`: `/participants/compatible` leaves out internal addresses.

## Out of Scope

- Enforcing capability policy on messages. #13 defines access as advisory.
- How adapters authenticate to each other. Replaying a bearer token between peers is recorded in `keycloak.md` as a maintainer's decision, and stays so. A connector's token has the same exposure, and `keycloak.md` says so.
- Connector policies. They still permit any authenticated participant.
- Limiting what a hub connector or adapter may call outside the hub, as external participants' addresses aren't known in advance.

## Impact

- `manifest.md`: none affected.
- `architecture.md`: "EDC Connector", "What is and is not publicly reachable", "Security Layers".
- `management-api.md`, `gateway-api.md`, `protocol.md`, `keycloak.md`, `deploy/README.md`, `CONTRIBUTING.md`: updated.
