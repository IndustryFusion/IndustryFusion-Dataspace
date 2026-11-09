# Proposal

Issue: #56

## Why

Today the chart refuses to render a management Ingress without `ingress.management.allowFrom`, under the `security-hardening` requirement "Management Ingress needs an allowlist". IP allowlists are hard to keep right. Home and mobile addresses change, and behind a cloud load balancer nginx often sees the load balancer's address, not the client's. Then either everyone is refused or a wide range has to be allowed.

Management already authenticates every change with a Keycloak admin token. Reads without a token give only the public view, by design, because external adapters need it. The allowlist is an extra layer, not the access control.

## What Changes

- **The chart.** The management Ingress gets `nginx.ingress.kubernetes.io/whitelist-source-range` only when `ingress.management.allowFrom` is set. Without it, the Ingress renders with no allowlist instead of failing.
- **`helm/common.yaml`.** The comment says `allowFrom` is optional: empty means any address. An operator who sets it must include external participants' adapters.
- **`scripts/check-helm-values.py`.**
  - It checks both cases: no allowlist renders without the annotation, and a set allowlist is carried exactly.
  - The check that a management Ingress without an allowlist is refused goes away.
- **`scripts/local-env.sh`** stops writing `allowFrom: "0.0.0.0/0"` into the local cluster's values.
- **Documents:**
  - `helm/README.md` describes the allowlist as optional, explains when to use one, and says that nginx must see the client's real address for it to work, for example with `externalTrafficPolicy: Local` or the PROXY protocol.
  - The README also says to run helmfile from `helm/` after `source ./env.sh`, or with `-f helm/helmfile.yaml.gotmpl` from elsewhere, and to keep the file's `.gotmpl` name.
  - `architecture.md` ("What is and is not publicly reachable") says management is reachable through its Ingress, protected by the Keycloak admin login, with an optional allowlist.
  - `management-api.md` tells an external participant's operator to add its address to the allowlist only if one is set.
- **Spec.** In `security-hardening`, "Management Ingress needs an allowlist" becomes "Management Ingress allowlist", with a scenario for each case.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `security-hardening`: the management Ingress's allowlist is optional.

## Out of Scope

- Basic auth at the Ingress. The maintainer decided against it. It would use the same `Authorization` header as the admin token, and external adapters would need a shared password.
- A rate limit on `POST /api/admin/token`. The maintainer decided to leave it as it is.
- Authentication in front of management at the Ingress, such as oauth2-proxy or nginx `auth-url`.
- The gateway and DSP gateway Ingresses.
- Management's own token checks.

## Impact

- `manifest.md`: none affected.
- `architecture.md`: the row for the management GUI in "What is and is not publicly reachable".
- `helm/README.md`, `helm/common.yaml`, `management-api.md` (step 1 of connecting an external participant).
- `helm/charts/management/templates/ingress.yaml`, `scripts/check-helm-values.py` and `scripts/local-env.sh`.
