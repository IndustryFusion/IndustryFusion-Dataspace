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
- **A rate limit on the login,** added after review. Each try costs a bcrypt check in the shared nginx worker, so `management-ui` gets `limit-rps` (default 5) and `limit-connections` (default 10) per client address, set by `ingress.management.basicAuth.limitRps` and `limitConnections`. Over them nginx answers `503`. `/api` gets none, as the maintainer decided against a rate limit on `/api/admin/token`.
- **Paths nginx normalises.** nginx merges slashes and resolves dot segments before it picks the Ingress, but passes the raw path on. So `//api/x` reaches the no-login `management` object, and management's page route would serve the UI's page for it. The route normalises the path first, and refuses anything under `api` or `health`.

Alternatives:
- **One Ingress with a server snippet** that turns auth off for `/api`. Snippets are disabled by default in ingress-nginx for security, and wouldn't be portable. Rejected.
- **`auth-url` to a small checker.** This would put a new component in front, which is out of scope. Rejected.

### The credentials and the Secret

- The username and password come from `secrets.managementBasicAuth.user` and `.password`, in the secrets file, which isn't committed. `secrets.yaml.example` lists both, empty.
- With `ingress.management.basicAuth.enabled` true, `required` stops rendering when either is empty, naming `secrets.managementBasicAuth.user` or `.password`. With it false, nothing is read, and no Secret or annotation is rendered.
- The Secret `management-basic-auth` in the management chart holds one key, `auth`, an htpasswd line `<user>:<bcrypt hash>`, from Helm's `htpasswd` function, which uses bcrypt. No rendered object holds the plain password. `check-helm-values.py` checks this by rendering with a canary password and searching every object for it.

### A stable hash

Helm's `htpasswd` picks a new random salt on every render. So the Secret's data would change on every `helmfile apply`, `helmfile diff` would always show it, and nginx would reload it each time. Helm has no bcrypt with a given salt, and no way to compare a password with a hash.

**Decision: keep the existing hash while the credentials are the same, with `lookup`.** This was revised after review.
- The Secret's `data` holds, beside `auth`, a `fingerprint`: the SHA-256 of the htpasswd line followed by the password. It is salted by the line's own random bcrypt salt. It is kept in `data`, which helm-diff masks, and not in an annotation, so no plain or unsalted fast hash of the password is shown anywhere.
- On render, the template looks up the existing `management-basic-auth`. It keeps the existing line only if the Secret has both `auth` and `fingerprint`, the line is for the same user, and the SHA-256 of that line with the new password equals the stored fingerprint. Otherwise it writes a new line and fingerprint.
- A user containing `:` stops rendering, as it would end the user early in the htpasswd line.
- `lookup` reaches the cluster during `helm install` and `helm upgrade`, which `helmfile sync` and `apply` run, so the Secret stays the same across repeated installs. Without a cluster, as in `helmfile template`, `lookup` returns nothing and a new line is written.
- `helmfile.yaml.gotmpl` sets `diffArgs: ["--dry-run=server"]`, so helm-diff renders against the cluster and a diff doesn't show the Secret as changed. This needs helm-diff 3.9.4 or later, which `bootstrap.sh` checks.

An earlier draft kept an unsalted SHA-256 of `user:password` in an annotation. Review found that helm-diff and `helmfile template` print annotations, which would help anyone cracking a weak password offline, so it was replaced as above.

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
- **No plain password, and no unsalted MD5, SHA-1 or SHA-256 of it or of `user:password`,** appears in any object's text or in any Secret value once decoded, with a canary password. The Secret has no annotations, and its fingerprint is salted by its line.
- **The login's rate limit** is on `management-ui` only.
- **A user with a colon** stops rendering.
- **Moved from the single Ingress:** the existing checks (the body size, the registration timeout, and the TLS section with one cert-manager annotation) now apply to the right object.
- **The secrets-key check** also reads the basic-auth keys.

## Conflicts with existing documents and specs

- **`security-hardening`, "Management Ingress needs an allowlist",** requires the refusal. It is renamed "Management Ingress access" and modified, as the issue asks.
- **`management-api` and `management-api.md`** say a token other than an admin's gives `401` or `403` on a read. A non-Bearer header now counts as no token. A Bearer token that isn't an admin's is still refused.
- **`architecture.md`, "What is and is not publicly reachable",** says the management GUI is for the operations team only, behind a VPN or an IP allowlist. The row changes to: the UI behind the optional login, the API behind the Keycloak admin token, and an optional allowlist.

## Risks

- **An exposed token route.** Without an allowlist, anyone who reaches the host can try client secrets at `POST /api/admin/token`, which Keycloak answers. This is the same exposure as Keycloak's own public token endpoint. The maintainer decided against a rate limit.
- **Basic auth over plain HTTP** sends the password in clear text. The README says to use TLS with the login.
- **`lookup` and RBAC.** `lookup` runs with the deploying user's rights, which have to include reading Secrets in the release's namespace. A missing Secret gives an empty result. A refused read (Forbidden) is an error, and the install stops. The deploying user already manages Secrets there, so this holds for any user who can install the charts.
