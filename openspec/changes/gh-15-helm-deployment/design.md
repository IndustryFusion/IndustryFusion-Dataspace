# Design

## Context

`architecture.md` gives the topology and service names, and the issue gives the release layout. `gateway-api.md` requires an Ingress to allow at least `MAX_UPLOAD_BYTES`.

## Decisions

### One chart, one release per service

A single chart renders a part chosen with the value `component`, and each release sets it. `dataspace-common` holds the Secret, the management service account and its RBAC. The others follow with `needs`: the registry, then the gateway and DSP gateway, then management. The registry needs only what `dataspace-common` created, and retries its database until it answers, so it never waits on a later release.

Alternatives: one chart per service, which repeats the same Deployment five times; one release for everything, which the issue's release order rules out.

Service names stay fixed by the component, as `architecture.md` lists them. They don't take the release name.

### Limits have one source

`limits.maxUploadBytes` and `limits.maxJsonBytes` fill the services' variables and the Ingress annotations, so they can't disagree. The chart refuses an upload limit below the JSON limit.

| Ingress | Body size |
|---|---|
| Gateway | Exactly `maxUploadBytes`, the largest request the gateway accepts |
| Management | Exactly `maxJsonBytes`. Its bodies are small, and this is the only limit in front of it |

On the gateway, request and response buffering are off, so that a 1 GiB upload streams, as the gateway itself does, instead of being kept on the controller's disk, and timeouts are `ingress.gateway.transferTimeoutSeconds`.

Requests over `MAX_JSON_BYTES` on other routes are left to the gateway, which answers with the contract's body.

**A request over `maxUploadBytes` gets the Ingress's own `413`, with its own body.** The status is right but it isn't the standard `{"detail": ...}`. The alternatives:

- Allow more at the Ingress than at the gateway, so that the gateway answers. A request larger than that margin still gets the Ingress's body, and the limits no longer agree.
- No limit at the Ingress, so that the gateway answers. Every request reaches the gateway however large, which an edge limit is there to prevent.
- Custom error pages. These need a default backend and are controller-specific.

This uses the plain limit, and `gateway-api.md` gains a note that clients should go by the status.

### An Ingress controller is assumed to be ingress-nginx

The annotations are ingress-nginx's. `ingress.className` and `ingress.annotations` let another controller be used, but its body limit is then up to the operator. Stated in `deploy/README.md`.

### Secrets

`values/secrets.yaml` is ignored by git and its `.example` holds empty values. The chart renders it into the Secret `service-credentials`, which pods read through `secretKeyRef`. Participants' Secrets are made by management, as #14 delivers. A changed secret needs a restart of the pods, as stated in the procedure.

Alternative: an `existingSecret` value, to work with external secret operators. Left out until someone needs it.

### Keycloak networking

`dependencies.keycloak.url` is the only setting, and it is both the address services reach and the issuer they compare with. No addresses are fixed, as there are no `hostAliases`. `scripts/check-helm-values.py` fails on an IP address in any rendered object.

### Removal

`deploy/helm/bootstrap.sh down` runs `helmfile destroy`, deletes the objects management labelled, and deletes both namespaces. The participants' databases, buckets and Keycloak clients are outside these namespaces. The script says so if participants remain, and the procedure says to delete them through the API first.

Alternative: a Helm pre-delete hook that calls the API. It would need an admin credential stored for the hook.

### Tools

`helmfile` is the one tool a cluster operator may lack, so `bootstrap.sh` downloads a pinned version and checks its SHA-256. `kubectl` and `helm` are required.

### Local verification

The acceptance checks run on the local cluster with `deploy/helm/values/environments/local.yaml`, using ingress-nginx and the local stand-ins for the dependencies. This environment isn't a real cloud: it has no real domain, certificate or load balancer.

## Risks

- The chart's cert-manager and TLS settings render, and aren't run against a certificate authority here.
- `helm uninstall` of a single release can remove the Secret while others use it. Use the procedure.

## Conflicts

`AGENTS.md` asks for the `spec-approved` label before implementation. A maintainer approved this milestone outside GitHub and the label is pending, as the Pull Request states.
