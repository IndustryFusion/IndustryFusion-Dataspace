# Tasks

## 1. Internal routes

- [x] 1.1 Require a token on `GET /internal/payload/{id}` and `POST /internal/inbox-receive/{id}`, and give it to the connector; verify with tests, including another message's token and the other route's token
- [x] 1.2 Ship NetworkPolicies for the chart and the local environment; verify on a local cluster from real pods
- [x] 1.3 Keep the registry to the gateway, management and adapters; verify on a local cluster from a pod

## 2. Credentials

- [x] 2.1 Give each hosted participant its own database user; verify with tests, and on a local cluster that one can't connect to another's database
- [x] 2.2 Give each hosted participant its own S3 identity; verify with tests, and on a local cluster that one can't read another's bucket
- [x] 2.3 Replace `ADAPTER_INTERNAL_KEY` with a key per participant; verify with tests, and on a local cluster that one's key is refused by another's adapter

## 3. Connector identity

- [x] 3.1 Replace the mock identity with Keycloak tokens; verify on a local cluster, with messages and files passing
- [x] 3.2 Show a connector with the wrong identity is refused; verify on a local cluster: no token, a mock token, another realm's token, and a real connector claiming to be someone else

## 4. Public reads

- [x] 4.1 Require an admin token on capability and policy reads; verify with tests and the browser tests
- [x] 4.2 Leave internal addresses out of public reads and `/participants/compatible`; verify with tests and the contract suite
- [x] 4.3 Require an allowlist on the management Ingress; verify with `scripts/check-helm-values.py`
- [ ] 4.4 Reach management through a restricted Ingress. Needs an Ingress controller, whose install was refused here. What it renders is checked in 4.3

## 5. End to end

- [x] 5.1 The end-to-end message and external participant tests pass with all of this active; verify the contract suite on a local cluster
- [x] 5.2 Add `scripts/security-check.py` with the negative tests; verify on a local cluster, and that each check fails when its protection is removed
- [x] 5.3 Run against a Helm install; verify a run on a local cluster, through the gateway's Service

## 6. Documents

- [x] 6.1 Update `architecture.md`, `management-api.md`, `gateway-api.md`, `protocol.md`, `keycloak.md`, `deploy/README.md` and `CONTRIBUTING.md`; verify by reading them against the behaviour

## 7. Report

- [x] 7.1 Check each scenario in the delta specs and report the result per scenario in the Pull Request; verify the report covers every scenario
