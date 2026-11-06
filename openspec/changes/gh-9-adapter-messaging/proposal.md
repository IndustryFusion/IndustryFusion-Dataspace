# Proposal

Issue: #9

## Why

The adapter is where the protocol lives, and the only part of the system that talks to the connector and to storage. With the registry and connector in place, this is what lets two participants exchange messages through the dataspace.

## What Changes

- Implement the outbox, inbox and acknowledge routes for agents, authenticated by JWT with the participant's realm role.
- Implement the send flow: compatibility check, payload storage, connector registration, peer notification.
- Implement the receive flow: sender verification, catalog, negotiation, push transfer.
- Implement retention and a schema monitor.
- Deploy two participants to the local environment and show messages going both ways.

## Capabilities

### New Capabilities

- `adapter-messaging`: How an agent sends and receives messages through its adapter.

### Modified Capabilities

None.

## Impact

- `adapter/`, `deploy/local/`, `scripts/`.
- `architecture.md`: "Dataspace Adapter" and "Request Flow" are implemented as described. No section changes. `manifest.md`: not affected.

## Out of Scope

- File transfer, in #11.
- Validity rules and the conversation state machine, and the `/conversations` routes, in #12. Every message is accepted as `applied` in state `OPEN` until then.
- Capability routes, in #13.
- The gateway, in #10. Tests here call adapters directly.
- Authentication on the routes the connector calls, in #20.
