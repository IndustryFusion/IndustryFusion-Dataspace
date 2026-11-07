# Tasks

## 1. Chart and values

- [x] 1.1 Add the chart, Helmfile and layered values; verify `helm lint` and `helm template` for each component and environment
- [x] 1.2 Add a check of what is rendered: body sizes equal to limits, credentials only in Secrets, no IP addresses, secret keys that exist, no token on other services; verify it fails on a deliberately broken chart, and runs in CI
- [x] 1.3 Add `bootstrap.sh` and the procedure in `deploy/README.md`; verify by following them on a new cluster
- [x] 1.4 Add the note on an Ingress's `413` to `gateway-api.md`; verify it matches what the Ingress does

## 2. On a new local cluster, with ingress-nginx

- [x] 2.1 Install from the procedure, and show every pod ready with no other step; verify on the local cluster
- [x] 2.2 Repeat the install, and show no pod restarts; verify on the local cluster
- [ ] 2.3 Onboard participants through the management Ingress and exchange messages through the gateway Ingress; verify on the local cluster
- [ ] 2.4 Upload through the Ingress at exactly the limit and one byte over, and download the same bytes; verify on the local cluster
- [ ] 2.5 Show a body over `MAX_JSON_BYTES` gets the contract's body through the Ingress; verify on the local cluster
- [x] 2.6 Show that management can't act outside its namespace; verify with `kubectl auth can-i` as its service account
- [x] 2.7 Remove with a participant still there, show both namespaces are gone, and install again; verify on the local cluster

Tasks 2.3 to 2.5 stay open: installing an Ingress controller on the local cluster was refused here. The same flows and limits passed against the Services directly, with no Ingress involved, as the Pull Request reports.

## 3. What can't run here

- [ ] 3.1 Issue a real certificate through cert-manager on a real domain. Needs a real cluster, domain and certificate authority. The rendered annotation and TLS section are checked in 1.2
- [ ] 3.2 Install against the DigitalTwin stack's own PostgreSQL, S3 storage and Keycloak. Needs that stack. The local stand-ins use the same names, ports and setup

## 4. Report

- [x] 4.1 Check each scenario in the delta specs and report the result per scenario in the Pull Request; verify the report covers every scenario
