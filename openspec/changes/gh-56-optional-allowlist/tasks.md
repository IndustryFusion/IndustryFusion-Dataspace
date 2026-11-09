# Tasks

## 1. Chart and values

- [x] 1.1 Split the management Ingress into `management` (`/api`, `/health`, no basic auth, body size, timeout, cert-manager) and `management-ui` (`/`), sharing the host and TLS; verify by rendering offline that each path goes to the right object and the other objects are unchanged
- [x] 1.2 Add `ingress.management.basicAuth.enabled`, `secrets.managementBasicAuth.user` and `.password` to `common.yaml` and `secrets.yaml.example`, the Secret `management-basic-auth` with a bcrypt htpasswd line, the auth annotations on `management-ui`, and `required` for empty credentials; verify by rendering with and without them
- [ ] 1.3 Keep the hash while the credentials are unchanged, with `lookup` and a fingerprint in `data` salted by the htpasswd line, keep `helmfile diff` quiet with `--dry-run=server`, and check helm-diff is 3.9.4 or later in `bootstrap.sh`; verify with two `helmfile sync` runs on a local cluster showing the same Secret, and a changed stored fingerprint showing a new line, as a password change would
- [x] 1.4 Add `whitelist-source-range` to both Ingress objects only when `allowFrom` is set, and describe it as optional in `common.yaml`; verify by rendering both cases
- [ ] 1.5 Limit the login's tries on `management-ui` only, with `limit-rps` and `limit-connections` from `ingress.management.basicAuth.limitRps` and `limitConnections`, defaults 5 and 10; verify by rendering, and on a local cluster that quick tries get `503` while `/health` doesn't

## 2. Checks

- [x] 2.1 In `scripts/check-helm-values.py`, cover: no allowlist, an allowlist on both objects, the login on, the login on without a user or without a password, `/api` and `/health` without basic auth, no plain password in any rendered object, the moved body size, timeout and TLS checks, and the basic-auth secret keys; verify it passes, and fails against a chart that puts basic auth on `/api`, leaks the password, or drops the allowlist from one object

## 3. Management API

- [x] 3.1 Treat a non-Bearer `Authorization` header as no token on the read routes, keep refusing a bad or non-admin Bearer token, and keep `401` on admin routes; verify with API tests for a `Basic` header on a read and on a change, and a non-admin Bearer token on a read, and that the read test fails against the old code
- [ ] 3.2 Normalise the path in management's page route before refusing `api` and `health`, so `//api/x` and `/./api/x` don't get the page; verify with unit tests that fail against the old route, and through the Ingress in `ingress-check.py`

## 4. Local cluster

- [x] 4.1 In `scripts/local-env.sh`, stop writing `allowFrom`, turn the UI login on, and generate a basic-auth password kept in `.local/credentials.env` and written to `.local/helm-secrets.yaml`; verify on a new local cluster
- [x] 4.2 Extend `scripts/ingress-check.py` to check `/` with and without the login, `/api` without it, and a `Basic` header on a read and on a change; verify on a local cluster with an Ingress controller, through an explicit kubeconfig
- [x] 4.3 With the login on, run `ingress-check.py`, `management-check.py` and `contract_test.py --local`; verify all pass, and delete the cluster afterwards

## 5. Documents

- [x] 5.1 Update `helm/README.md`: the UI login and its settings, TLS with it, the token on `/api`, the optional allowlist and when it helps, the client's real address, the Secret in `helmfile diff`, and running helmfile from `helm/` or with `-f`, warning against duplicating or renaming `helmfile.yaml.gotmpl` as `helmfile.yaml`; check the helmfile statements with the pinned version offline; verify by reading
- [x] 5.2 Update `architecture.md`'s row for the management GUI, and `management-api.md` ("Authentication", "What is public", and step 1 for external participants); verify with a search for `allowFrom`, "allowlist" and "Any other token"
