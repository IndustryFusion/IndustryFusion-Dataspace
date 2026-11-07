# Tasks

## 1. DSP gateway

- [x] 1.1 Route `/{slug}/api/v1/dsp/{path}` and `/{slug}/api/v1/public/{path}` to a connector's ports, with `PARTICIPANTS_NAMESPACE`; verify with tests, including refused slugs and paths that try to leave the prefix
- [x] 1.2 Add the optional Ingress to the chart; verify what it renders with `scripts/check-helm-values.py`
- [ ] 1.3 Reach a connector through the Ingress. Needs an Ingress controller, whose install was refused here. What it renders is checked, and the API server accepts it in a dry run

## 2. Gateway

- [x] 2.1 Add the capability and content peer routes, and remove `X-Internal-Key`; verify with tests, including that a token isn't needed only on the content route, which needs its header
- [x] 2.2 Show that `sender_applied` and `kept_step` pass through; verify with tests

## 3. Adapter

- [x] 3.1 Use `peer_notify_url` for capability calls; verify with tests that a provider with only that address answers
- [x] 3.2 Name the peer route as the destination when this adapter has a peer address, with a transfer token, and check the token on arrival; verify with tests, including a wrong token and another message's token

## 4. Management

- [x] 4.1 Give a reachable hosted participant its addresses, restart its connector when that changes, and refuse it when a peer address isn't configured; verify with tests

## 5. Demo

- [ ] 5.1 Add the template and the script; verify `up` and `down` on a local cluster
- [x] 5.2 Show the NetworkPolicy is active; verify from a pod that hosted adapters and connectors, the registry and the shared PostgreSQL can't be reached, and that the public routes can

## 6. End to end

- [x] 6.1 Messages and files in both directions between an external and a hosted participant, with the NetworkPolicy active; verify on a local cluster
- [x] 6.2 Capability requests in both directions in the same setup; verify on a local cluster
- [x] 6.3 Conversation steps that use `sender_applied` and `kept_step` across the two sides; verify on a local cluster
- [x] 6.4 Hosted-only without the DSP gateway; verify messages and files with it scaled to zero
- [x] 6.5 The contract suite runs the external flows; verify a run with none not run, and a run where a broken flow fails

## 7. Documents

- [x] 7.1 Cover onboarding in `management-api.md`, and update `architecture.md`, `keycloak.md`, `protocol.md`, `deploy/README.md` and `CONTRIBUTING.md`; verify by reading them against the behaviour

## 8. Report

- [ ] 8.1 Check each scenario in the delta specs and report the result per scenario in the Pull Request; verify the report covers every scenario
