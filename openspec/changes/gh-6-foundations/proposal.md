# Proposal

Issue: #6

## Why

The services in `architecture.md` need somewhere to live, a way to be built and tested, and a local environment to run in. Setting that up once, before the first service, keeps the following changes focused on behaviour.

## What Changes

- Add the service layout, with a skeleton for each service that answers its health route.
- Record test, lint and build conventions.
- Add CI that lints, tests and builds an image for every service.
- Add a script that brings up a local Kubernetes cluster with PostgreSQL, S3-compatible storage and Keycloak, and a realm set up as `keycloak.md` describes.
- Add a script that manages local host entries.

## Capabilities

### New Capabilities

- `project-foundations`: How services are laid out, built and tested.
- `local-environment`: How a contributor gets a working environment on one machine.

### Modified Capabilities

None.

## Impact

- New: `gateway/`, `registry/`, `adapter/`, `connector/`, `dsp-gateway/`, `management/`, `scripts/`, `deploy/local/`, `.github/workflows/services.yml`, `.gitignore`.
- `CONTRIBUTING.md` and `openspec/config.yaml` gain the conventions.
- `architecture.md` and `manifest.md`: no sections are affected.

## Out of Scope

- Service behaviour beyond a health route, delivered in #7, #8, #9, #10 and #14.
- Helm charts, in #15.
- The management UI, in #16. Its directory holds a note until then.
