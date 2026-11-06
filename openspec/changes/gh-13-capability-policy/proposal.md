# Proposal

Issue: #13

## Why

Each participant needs to state which data it shares with whom, and others need a way to ask for access. Applications connecting to the dataspace also need to know that this check is theirs to make.

## What Changes

- Add the capability catalogue, and the agent routes `GET /capabilities/access`, `POST /capabilities/requests`, `GET /capabilities/requests`, `PATCH /capabilities/requests/{id}` and `POST /capabilities/policy`.
- Add the internal routes `GET /internal/capabilities`, `POST /internal/capabilities/approvals`, `PATCH /internal/capabilities/approvals/{id}` and `PATCH /internal/capabilities/{capability}`, using `X-Internal-Key` or a peer token that sees only that peer's own approvals.
- Store state in `capability_policies` and `capability_approvals`.
- Hosted adapters reach each other's capability routes directly, at the provider's `adapter_url`.
- Record the decisions in the issue in `gateway-api.md`: an incompatible role gets `403`, and a decision's note is stored and returned.
- State in `protocol.md`, `architecture.md` and `manifest.md` that access is advisory.

## Capabilities

### New Capabilities

- `capability-policy`: Who may access what, how to ask, and how it is decided.

### Modified Capabilities

None.

## Out of Scope

- Enforcing capability policy on messages. Access is advisory, and #20 keeps this out of scope too.
- The management API routes under `/api/participants/{id}/...`, and the Policies tab. #14 and #17 deliver them on top of the internal routes here.
- `GET /api/policy`.
- Carrying capability calls through the gateway's peer route for external participants. #18 owns this.
- Authentication of the internal routes beyond `X-Internal-Key` and a peer token, tracked in #20.

## Impact

- `architecture.md`, "Dataspace Adapter" and "Security Layers": gain a statement that access is advisory.
- `manifest.md`, "governed" communication: already states this; checked and aligned.
- `protocol.md`, "Capability access": states what the rules are for a repeated request and a capability offered automatically.
- `gateway-api.md`, "Capabilities" and "Errors": `403` for an incompatible role, `decision_note`, and the answer for a capability the provider doesn't have.
- Services: adapter.
