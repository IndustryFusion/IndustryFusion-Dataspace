# Proposal

Issue: #15

## Why

The dataspace can only run on the local environment's stand-in manifests. An operator needs a documented way to install it on a Kubernetes cluster, using the platform's existing PostgreSQL, S3 storage and Keycloak, and to remove it again.

## What Changes

- Add a Helm chart, a Helmfile and layered values under `deploy/helm`: common, per environment, and a secrets file with a committed `.example` only.
- Add a bootstrap script for the two namespaces and the tools, and for removal.
- Add an Ingress for the gateway and for management, with an optional cert-manager setting, and body sizes read from the same values as `MAX_UPLOAD_BYTES` and `MAX_JSON_BYTES`.
- Add RBAC for the management API in the participants namespace, and deliver credentials through a Kubernetes Secret.
- Document the procedure in `deploy/README.md`.

## Capabilities

### New Capabilities

- `helm-deployment`: Installing, configuring and removing the dataspace on Kubernetes.

### Modified Capabilities

None.

## Out of Scope

- Installing PostgreSQL, S3 storage, Keycloak, an Ingress controller or cert-manager. These are dependencies.
- Publishing images. No published images exist yet, and the procedure builds them.
- Routing external DSP traffic through an Ingress (#18). The DSP gateway is deployed, not exposed.
- Multiple replicas of the management API.

## Impact

- `manifest.md`: none affected.
- `architecture.md`, "Deployment Topology", "What is and is not publicly reachable" and "Kubernetes Service Names": delivered as written.
- `gateway-api.md`: `MAX_UPLOAD_BYTES` and the note about an Ingress stay as they are. A note is added on the body of an Ingress's `413`, see `design.md`.
- `management-api.md`: none affected.
