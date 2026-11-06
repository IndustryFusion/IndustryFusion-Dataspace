# Proposal

Issue: #5

## Why

Every service in this project builds on `manifest.md` and `architecture.md`, and those documents disagree. They differ on the deployment target, the connector layout and the message model, and the agent API is not written down anywhere. Agent applications, starting with XANA AI PDT, need a contract to build against. Settling this first means later changes don't each have to raise the same questions.

## What Changes

- Record decisions on the deployment target, connector layout, leading documents, duplicate text and object storage, closing the open questions from `gh-2-bootstrap-openspec`.
- Add `gateway-api.md`, `management-api.md`, `protocol.md`, `keycloak.md`, `flow.md` and `asyncapi.yaml`.
- Correct `architecture.md` and `manifest.md` to match the decisions and the new documents.
- Remove the resolved differences from the project context in `openspec/config.yaml`.

## Capabilities

### New Capabilities

- `project-documents`: Which documents exist, which one leads on what, and what each must cover, so they stay consistent as the project grows.

### Modified Capabilities

None.

## Impact

- Documentation only. No service code or deployment files.
- `architecture.md`: Overview, Deployment Topology, Kubernetes Service Names, Component Breakdown, Request Flow (external participant), Security Layers, Participant Types and Communication Rules, Technology Stack.
- `manifest.md`: sections 3, 7, 8, 9 and 11, and removal of the duplicated text.
- `openspec/config.yaml`: project context.
- The contract is the input for the service changes that follow, and for the connection work in IndustryFusion/XANA-AI-PDT#26.

## Out of Scope

- Any service code, tests or deployment files.
- Security changes, which are covered by #20.
- Changes to other repositories.
