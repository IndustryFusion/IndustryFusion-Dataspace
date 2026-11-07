# Proposal

Issue: #8

## Why

Messages between participants travel through EDC connectors, so each participant needs one. A connector image with the right modules, ports and storage is what the adapter in #9 works against.

## What Changes

- Build a connector image on EDC 0.9.0 and Java 21, with control and data plane in one process.
- Include token authentication on the management API, DSP, the HTTP data plane, SQL stores and a mock DSP identity.
- Generate an RSA key pair into the in-memory vault at each start.
- Commit a template for `/config/connector.properties`.
- Add a script that shows two connectors completing a negotiation and an `HttpData-PUSH` transfer.

## Capabilities

### New Capabilities

- `edc-connector`: The connector each participant runs.

### Modified Capabilities

None.

## Impact

- `connector/`, `scripts/`, `deploy/local/`.
- `architecture.md`: the Technology Stack row for the connector is met. No section changes. The mock identity is already recorded in `protocol.md` under Known limits. `manifest.md`: not affected.

## Out of Scope

- A real DSP identity, and real access policies, in #20.
- The adapter's use of the connector, in #9.
- Provisioning a connector per participant at runtime, in #14.
