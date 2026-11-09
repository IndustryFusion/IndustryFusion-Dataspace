# Tasks

## 1. Chart and values

- [ ] 1.1 Add `whitelist-source-range` to the management Ingress only when `ingress.management.allowFrom` is set, and describe it as optional in `helm/common.yaml`; verify by rendering offline with and without it
- [ ] 1.2 Stop writing `allowFrom` in `scripts/local-env.sh helm-values`; verify by reading the generated file

## 2. Checks

- [ ] 2.1 In `scripts/check-helm-values.py`, replace the check that refuses a management Ingress without an allowlist with checks that it renders without the annotation, and that a set allowlist is carried exactly; verify it passes, and that it fails against a chart that still requires the allowlist or drops a set one

## 3. Local cluster

- [ ] 3.1 On a local kind cluster, through an explicit kubeconfig and with no allowlist, check that the management UI and API answer through the Ingress, that `ingress-check.py` passes, and that a change without an admin token gets `401`; verify on the local cluster, and delete it afterwards

## 4. Documents

- [ ] 4.1 Update `helm/README.md`: the allowlist as optional, when to use one, the client's real address (`externalTrafficPolicy: Local` or the PROXY protocol), and running helmfile from `helm/` or with `-f helm/helmfile.yaml.gotmpl`, keeping the `.gotmpl` name; check the statements about the file's name with the pinned helmfile offline; verify by reading
- [ ] 4.2 Update `architecture.md`'s row for the management GUI, and step 1 of connecting an external participant in `management-api.md`; verify with a search for `allowFrom` and "allowlist"
