# Design

## Context

- **The chart.** `helm/charts/management/templates/ingress.yaml` renders one Ingress, `management`, routing `/` to the management Service on port 3000. It requires `ingress.management.allowFrom` for `nginx.ingress.kubernetes.io/whitelist-source-range`. It also carries the body size (`MAX_JSON_BYTES`), the read timeout for a registration, and the optional cert-manager annotation.
- **The service.** Management serves the UI and its static files under `/`, the API under `/api`, and a probe at `/health`.
- **Token handling.** `require_admin` in `management/api/app/tokens.py` refuses anything but `Bearer <token>`. The read routes run it whenever an `Authorization` header is present (`shown_as_token_allows` in `main.py`), so any header other than an admin's Bearer token gives `401` or `403` today, including `Basic`. `management-api.md` says so: "Any other token gives `401` or `403`, rather than being treated as none."
- **Browsers.** After a basic-auth login, a browser sends `Authorization: Basic …` with every request to the same host whose path lies under the protected one, `/`. That includes `/api`. When the UI's code sets `Authorization: Bearer …` itself, in admin mode, the browser sends that instead.
- **The local cluster.** `scripts/local-env.sh` writes `allowFrom: "0.0.0.0/0"`, which allows everyone.

## Decisions

The maintainer decided:
- nginx basic auth on the management UI only, on `/`;
- `/api` and `/health` have no basic auth and keep the Keycloak admin token;
- management treats a non-Bearer `Authorization` header as no token;
- the credentials live in the secrets file, `secrets.managementBasicAuth.user` and `.password`, and the chart writes only a bcrypt htpasswd hash into a Secret;
- `ingress.management.basicAuth.enabled` turns the login on;
- the allowlist is optional, and when set it applies to both management Ingress objects;
- no rate limit on `/api/admin/token`, and no oauth2-proxy.

The sections below say how.

### Two Ingress objects, split by path

ingress-nginx merges the Ingress objects of one host into one server, and applies auth and allowlist annotations to the locations of the Ingress that carries them. So:

| Ingress | Paths | Basic auth | Other annotations |
|---|---|---|---|
| `management` | `/api` (Prefix), `/health` (Exact) | never | body size `MAX_JSON_BYTES`, the registration read timeout, the allowlist if set, cert-manager if set |
| `management-ui` | `/` (Prefix) | when `basicAuth.enabled` | the allowlist if set |

- nginx picks the longest matching path, so `/api/...` and `/health` go to `management`, and everything else to `management-ui`.
- **Static files.** The UI's files (`/`, `/index.html`, `/assets/...`) are under `/`. They get the login, and the browser sends the remembered credentials with each.
- **`/health`** answers the cluster's probes inside the cluster, not through the Ingress. It is routed through the Ingress without a login so that an outside monitor can reach it, as it says nothing but `ok`.
- **The existing name.** `management` keeps its name and now routes the API. The UI moves to the new `management-ui`. An install upgraded from one Ingress gets the API on the existing object, so it doesn't lose the route an external adapter uses. The UI's route moves to the new object in the same release.
- **When the login is off,** the split stays the same, so turning it on or off changes only annotations and the Secret.
- **TLS.** Both objects list the same host and TLS Secret. The cert-manager annotation goes only on `management`. With it on both, cert-manager's ingress shim would make two Certificates for one Secret, which conflict.
- **Basic auth annotations** on `management-ui`: `nginx.ingress.kubernetes.io/auth-type: basic`, `auth-secret: management-basic-auth`, `auth-secret-type: auth-file`, and `auth-realm: "Dataspace management"`.

Alternatives:
- **One Ingress with a server snippet** that turns auth off for `/api`. Snippets are disabled by default in ingress-nginx for security, and wouldn't be portable. Rejected.
- **`auth-url` to a small checker.** This would put a new component in front, which is out of scope. Rejected.

### The credentials and the Secret

- The username and password come from `secrets.managementBasicAuth.user` and `.password`, in the secrets file, which isn't committed. `secrets.yaml.example` lists both, empty.
- With `ingress.management.basicAuth.enabled` true, `required` stops rendering when either is empty, naming `secrets.managementBasicAuth.user` or `.password`. With it false, nothing is read, and no Secret or annotation is rendered.
- The Secret `management-basic-auth` in the management chart holds one key, `auth`, an htpasswd line `<user>:<bcrypt hash>`, from Helm's `htpasswd` function, which uses bcrypt. No rendered object holds the plain password. `check-helm-values.py` checks this by rendering with a canary password and searching every object for it.

### A stable hash

Helm's `htpasswd` picks a new random salt on every render. So the Secret's data would change on every `helmfile apply`, `helmfile diff` would always show it, and nginx would reload it each time. Helm has no bcrypt with a given salt, and no way to compare a password with a hash.

**Decision: keep the existing hash while the credentials are the same, with `lookup`.**
- The Secret carries an annotation, `dataspace.industryfusion.org/credentials-sha256`. It is the SHA-256 of `<user>:<password>`.
- On render, the template looks up the existing `management-basic-auth`. If its annotation matches the new one, it keeps the existing `auth` value. Otherwise it writes a new hash, as for a new install or changed credentials.
- `lookup` reaches the cluster during `helm install` and `helm upgrade`, which `helmfile sync` and `apply` run. So the Secret stays the same across repeated installs.
- Without a cluster, as in `helmfile template` and the checks, `lookup` returns nothing and a fresh hash is written. That doesn't matter there.
- `helmfile diff` uses helm-diff, which only calls `lookup` against the cluster with `--dry-run=server`. The implementation sets that through the release defaults in `helmfile.yaml.gotmpl`, if the pinned versions allow it, so a diff shows no change. Otherwise the README says that the Secret shows as changed in a diff, and why.

**Why a SHA-256 of the credentials is acceptable here:**
- It sits on the same Secret as the bcrypt hash, readable with the same rights.
- Anyone with those rights can already read the plain password from the Helm release record in the same namespace, which holds the release's values in its own Secret.
- So it gives an attacker nothing new.
- It still keeps the plain password out of every rendered object, as the issue requires.

Alternatives:
- **A new hash on each render.** This is simple and works, but gives a spurious Secret change and an nginx reload on every apply. It stays as the fallback described above.
- **A stable salt.** Helm can't compute bcrypt with a given salt. Running an external tool from `values.yaml.gotmpl` would add a dependency to every render. Rejected.
- **An explicit rotation value** that keeps the old hash until it changes. A forgotten bump would keep the old password working without anyone noticing. Rejected.

### The API ignores basic credentials

A new helper in `tokens.py` reads a bearer token from the header. It returns nothing when the header is missing or its scheme isn't `Bearer`. The read routes use it: no bearer token means the public view. A `Bearer` header that is malformed, expired or without the admin role is refused, as today. Admin routes keep `require_admin`, so a `Basic` header gives `401` "Missing token", as no header does. `POST /api/admin/token` reads no header, and is unaffected.

`management-api.md` changes "Any other token gives `401` or `403`, rather than being treated as none" to say that a header with another scheme, such as `Basic`, counts as none.

### The allowlist

`whitelist-source-range` is added to both Ingress objects inside `with .Values.ingress.management.allowFrom`. Empty means any address. The README says when an allowlist still helps: management only from known networks, with external adapters' addresses included. It also says nginx must see the client's real address for the allowlist to work, for example through `externalTrafficPolicy: Local` on the controller's Service, or the PROXY protocol.

### Running helmfile

The README gains a short section:
- Run helmfile from `helm/` after `source ./env.sh`, or from elsewhere with `-f helm/helmfile.yaml.gotmpl`.
- Keep the file's `.gotmpl` name. Under another name, such as `helmfile.yaml`, helmfile reads it as plain YAML and the template doesn't parse. With both files present, helmfile refuses to start.
- The implementation checks these statements against the pinned helmfile, offline, and the README says only what holds.

### The local cluster

- **Credentials.** `local-env.sh` generates a basic-auth password once, the same way as its other credentials. It keeps it in `.local/credentials.env` with the user `admin`, writes it into `.local/helm-secrets.yaml`, and sets `ingress.management.basicAuth.enabled: true` in `.local/helm-values.yaml`.
- **No allowlist.** It stops writing `allowFrom`.
- **`ingress-check.py`** gains checks through the Ingress, reading the password from the generated files:
  - `/` without credentials gives `401`, and with them the UI loads;
  - `/api` answers without basic credentials;
  - a `Basic` header on a read gives the public view, and on a change gives `401`.
- **`management-check.py` and the contract suite** reach management through a port-forward to its Service, not the Ingress. They are run with the login on, to show nothing else changed, and the README says which paths each covers.

### The checks

`check-helm-values.py`:
- **Without an allowlist:** the chart renders, and neither Ingress has `whitelist-source-range`.
- **With one:** both carry exactly the value.
- **The login on:** `management-ui` has the four auth annotations, `management` has none, and the Secret has an `auth` line for the user with a bcrypt hash.
- **The login on, without a user or password:** rendering fails, naming it.
- **`/api` and `/health`:** they are on `management`, without basic auth.
- **No plain password** appears in any object, with a canary password.
- **Moved from the single Ingress:** the existing checks (the body size, the registration timeout, and the TLS section with one cert-manager annotation) now apply to the right object.
- **The secrets-key check** also reads the basic-auth keys.

## Conflicts with existing documents and specs

- **`security-hardening`, "Management Ingress needs an allowlist",** requires the refusal. It is renamed "Management Ingress access" and modified, as the issue asks.
- **`management-api` and `management-api.md`** say a token other than an admin's gives `401` or `403` on a read. A non-Bearer header now counts as no token. A Bearer token that isn't an admin's is still refused.
- **`architecture.md`, "What is and is not publicly reachable",** says the management GUI is for the operations team only, behind a VPN or an IP allowlist. The row changes to: the UI behind the optional login, the API behind the Keycloak admin token, and an optional allowlist.

## Risks

- **An exposed token route.** Without an allowlist, anyone who reaches the host can try client secrets at `POST /api/admin/token`, which Keycloak answers. This is the same exposure as Keycloak's own public token endpoint. The maintainer decided against a rate limit.
- **Basic auth over plain HTTP** sends the password in clear text. The README says to use TLS with the login.
- **`lookup` and RBAC.** `lookup` runs with the deploying user's rights, which can read Secrets in the release's namespace. Without those rights it returns nothing, and a new hash is written each time, which still works.
