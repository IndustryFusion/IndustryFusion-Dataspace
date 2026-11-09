# Design

## Context

- **The chart.** `helm/charts/management/templates/ingress.yaml` sets `nginx.ingress.kubernetes.io/whitelist-source-range` with `required`, so a management Ingress without `ingress.management.allowFrom` fails to render. `helm/common.yaml` describes the setting as required with the Ingress.
- **The checks.** `scripts/check-helm-values.py` checks that a management Ingress without an allowlist is refused. It also leaves the allowlist annotation out of its IP-address check, because an allowlist is addresses by its nature.
- **The local cluster.** `scripts/local-env.sh` writes `allowFrom: "0.0.0.0/0"` into `.local/helm-values.yaml`, which allows everyone.
- **Management's own access control:**
  - Registering, the demo, credentials, capabilities, approvals, policy and removal need a Keycloak token with the admin role.
  - `GET /api/participants` and `GET /api/participants/{id}` without a token give the public view, which external adapters read.
  - `POST /api/admin/token` exchanges the admin client's secret for a token.

## Decisions

### The annotation only when the allowlist is set

The template adds `whitelist-source-range` inside `{{- with .Values.ingress.management.allowFrom }}`, with the value quoted as it is today. Empty or missing means no annotation, and nginx then admits any address. Nothing else in the Ingress changes.

Alternatives:
- **A separate switch, such as `ingress.management.allowlist.enabled`.** That is a second setting with the same meaning as a non-empty `allowFrom`. Rejected.
- **Keeping it required, and documenting `0.0.0.0/0`.** This keeps the friction the issue is about, and a list that allows everything is no clearer than none. Rejected.

### What protects management without an allowlist

The admin token, which management checks on every change. The UI holds no secret, because it asks for the admin client's secret and exchanges it for a token. The public reads are public by design. So with no allowlist, the same requests are possible as with an allowlist that includes the caller.

The maintainer decided:
- **No basic auth.** It would use the same `Authorization` header as the admin token, so the two couldn't be used together, and external adapters would need a shared password too.
- **No rate limit on `POST /api/admin/token`.** It stays as it is. Guessing is bounded by the client secret's length, which Keycloak generates.

### When an allowlist helps, and what it needs

The README says to use an allowlist when management should only be reachable from known networks, such as an office or a VPN. Every external participant's adapter address must then be included, because adapters read participants there. nginx must see the client's real address, or the list matches the load balancer instead. On most clouds that means `externalTrafficPolicy: Local` on the controller's Service, or the PROXY protocol with `use-proxy-protocol` in the controller's ConfigMap.

### Running helmfile

The README gains a short section: run helmfile from `helm/` after `source ./env.sh`, or from elsewhere with `-f helm/helmfile.yaml.gotmpl`. Keep the file's `.gotmpl` name. Under another name such as `helmfile.yaml`, helmfile reads it as plain YAML, and the template doesn't parse. With both files present, helmfile refuses to start. The implementation checks the last two statements with the pinned helmfile, offline, and the README says only what holds.

### The checks

In `check-helm-values.py`:
- the check that "a management Ingress without an allowlist was accepted" is replaced by two:
  - with the Ingress on and `allowFrom` empty, rendering succeeds and the management Ingress has no `whitelist-source-range`;
  - with `allowFrom=10.0.0.0/8`, the annotation is exactly `10.0.0.0/8`;
- the IP-address check keeps leaving the allowlist annotation out.

### The local cluster

`local-env.sh helm-values` stops writing `allowFrom`, so the local Ingress has no allowlist, as the default does. `scripts/check-helm-layout.py` is unaffected: main no longer has `deploy/helm`, so it reports nothing to compare.

## Conflicts with existing documents and specs

- **`security-hardening`, "Management Ingress needs an allowlist".** It requires the refusal. This change renames and modifies it, as the issue asks.
- **`architecture.md`, "What is and is not publicly reachable",** says the management GUI is for the operations team only, "behind VPN or separate Ingress with IP allowlist". The row changes to: reachable through its Ingress, protected by the Keycloak admin login, with an optional allowlist or VPN.
- **`management-api.md`,** step 1 of connecting an external participant, says to add its address to `ingress.management.allowFrom`. It changes to: if an allowlist is set.

## Risks

- **An exposed admin token route.** Without an allowlist, anyone who can reach the management host can try client secrets at `POST /api/admin/token`, which Keycloak answers. This is the same exposure as Keycloak's own token endpoint, which is already public. The maintainer decided against a rate limit here.
- **Exposed public reads.** The public view of participants is readable by anyone who reaches management. It is the view external adapters already get, and it holds no secret.
