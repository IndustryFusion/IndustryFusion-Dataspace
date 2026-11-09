# Proposal

Issue: #56

## Why

Today the chart refuses to render a management Ingress without `ingress.management.allowFrom`. This is the `security-hardening` requirement "Management Ingress needs an allowlist". An operator often can't know the right addresses before deploying:
- home and mobile addresses change;
- behind a cloud load balancer, nginx often sees the load balancer's address, not the client's.

Operators want a simple login in front of the UI instead. Basic auth can't cover the API: the UI and external adapters call `/api` with `Authorization: Bearer <token>`, which is the same header, and adapters can't answer a password prompt. So the login goes on the UI, and `/api` keeps the Keycloak admin token that already protects every change.

## What Changes

- **Two Ingress objects for the management host:**
  - `management-ui` routes `/`, the UI and its static files, with nginx basic auth when `ingress.management.basicAuth.enabled` is true.
  - `management` routes `/api` and `/health`, with no basic auth.

  Both share the host and TLS settings.
- **Credentials.**
  - The username and password go in the secrets file, as `secrets.managementBasicAuth.user` and `.password`, and `secrets.yaml.example` lists them.
  - The chart writes only a bcrypt htpasswd hash, into a Secret `management-basic-auth`.
  - With the login on, rendering stops when either is empty, naming it.
  - The hash stays the same across installs and upgrades while the credentials don't change (see the design).
- **The management API ignores basic credentials.** An `Authorization` header whose scheme isn't `Bearer` counts as no token. Reads give the public view, and changes give `401`, as without a token. A malformed or non-admin `Bearer` token is refused as today.
- **The allowlist is optional.** `whitelist-source-range` is added only when `ingress.management.allowFrom` is set. When it is set, both management Ingress objects carry it.
- **Checks and tests:**
  - `scripts/check-helm-values.py` covers each case, and checks that no plain password appears in any rendered object.
  - The management API tests cover a `Basic` header on a read and on a change.
- **The local cluster.** `scripts/local-env.sh` stops writing `allowFrom: "0.0.0.0/0"`. It turns the UI login on, with a generated password kept in `.local/`. `scripts/ingress-check.py` checks the UI login through the Ingress.
- **Documents:**
  - `helm/README.md` and `architecture.md` describe the UI login, the token on `/api`, the optional allowlist, when an allowlist still helps, and that nginx must see the client's real address for it to work.
  - The README covers running helmfile from `helm/` after `source ./env.sh`, or with `-f helm/helmfile.yaml.gotmpl`. It warns against duplicating or renaming `helmfile.yaml.gotmpl` as `helmfile.yaml`.
  - `management-api.md` changes its step for external participants, and says how a `Basic` header is treated.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `security-hardening`: "Management Ingress needs an allowlist" becomes "Management Ingress access": the UI login, `/api` without basic auth, and the optional allowlist.
- `management-api`: basic credentials are treated as no token.

## Out of Scope

- A Keycloak login in front of management, such as oauth2-proxy or nginx `auth-url`.
- A rate limit on `POST /api/admin/token`.
- The gateway and DSP gateway Ingresses.

## Impact

- `manifest.md`: none affected.
- `architecture.md`: the row for the management GUI in "What is and is not publicly reachable".
- `helm/README.md`, `helm/common.yaml`, `helm/environment/secrets.yaml.example`, and the management chart's templates.
- `management-api.md`: "Authentication", "What is public" under "Reads", and step 1 of connecting an external participant.
- `management/api` (`tokens.py` and the read routes in `main.py`), and its tests.
- `scripts/check-helm-values.py`, `scripts/local-env.sh` and `scripts/ingress-check.py`.
