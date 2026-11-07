# Proposal

Issue: #18

## Why

`architecture.md` describes a participant that runs its own adapter and connector, and exchanges messages with hosted participants through two public doors. Neither door is complete. The DSP gateway answers only `/health`, the gateway's peer route carries only notifications, and a capability call to a provider with only a `peer_notify_url` gives `503`. The contract suite lists external flows as not run.

## What Changes

- The DSP gateway routes `/{slug}/api/v1/dsp/{path}` and `/{slug}/api/v1/public/{path}` to a hosted connector, with an optional Ingress.
- The gateway's peer route also carries capability reads and requests, and content pushed to a hosted adapter, and removes `X-Internal-Key` from what it forwards.
- A capability request and `GET /capabilities/access` use a provider's `peer_notify_url` where it is set.
- A hosted participant that is `externally_reachable` announces addresses that work from outside: the DSP gateway's for its connector, and the peer route for pushed content.
- Manifests and scripts deploy two self-hosted participants, each in its own namespace with its own PostgreSQL, S3 storage, adapter and connector, and a NetworkPolicy limiting it to the public routes.
- `management-api.md` covers onboarding an external participant, and the documents state what a peer can do with the token it receives.
- The contract suite runs the external flows.

## Capabilities

### New Capabilities

- `external-participants`: The DSP gateway, what hosted participants announce, capability calls through the peer route, the demo, and the suite's external flows.

### Modified Capabilities

- `api-gateway`: The peer route carries more than notifications.

## Out of Scope

- Changing how adapters authenticate to peers. An adapter sends its own bearer token, and no audience is checked. `keycloak.md` records this as a maintainer's decision, and this change states what it means for external participants.
- Authenticating `GET /internal/payload/{id}` and the rest of `POST /internal/inbox-receive/{id}` (#20).
- A real connector identity, per-participant credentials and hub NetworkPolicies (#20).
- Management routes reaching an external participant's capabilities. They keep giving `409`, as the internal key is never sent outside.

## Impact

- `manifest.md`: none affected.
- `architecture.md`: "API Gateway", "DSP Gateway", "Capability Access Is Advisory" and "Request Flow — External participant ↔ hosted participant". The peer route's single exception to blocking `internal/*` goes, as #13 recorded it would.
- `management-api.md`, `keycloak.md`, `protocol.md`, `deploy/README.md`, `CONTRIBUTING.md`: updated.
- `gateway-api.md`: none affected. It describes what an agent calls, and external participants' agents call their own adapter with the same routes.
