# Proposal

Issue: #19

## Why

Agent applications need to check their work against a working dataspace, and the dataspace needs a way to check that it still meets its published contract. Today only `scripts/message-exchange-check.py` exercises the routes, and it doesn't check each field.

## What Changes

- Add a command-line client in `scripts/`, covering token retrieval, sending, polling, acknowledging, downloading, conversations and capabilities.
- Add a mock agent that uses the gateway and normal authentication.
- Add a contract test suite that runs the client against a deployment, and checks each route, field, status value and error shape in `gateway-api.md`.
- Add scripted scenarios for every flow in `flow.md`, and the worked scenario the first agent application needs.
- Add a CI job that can be run on demand, and instructions in `CONTRIBUTING.md`.

## Capabilities

### New Capabilities

- `contract-tests`: The client, the mock agent and the contract suite.

### Modified Capabilities

None.

## Out of Scope

- The flows with external participants, which need #18. The suite reports them as not run.
- Testing the application in IndustryFusion/XANA-AI-PDT#26, which uses this client.
- Changing the published contract. A difference found is reported, as a failure.

## Impact

- `manifest.md`, `architecture.md`, `gateway-api.md`: none affected.
- `CONTRIBUTING.md`: gains instructions.
