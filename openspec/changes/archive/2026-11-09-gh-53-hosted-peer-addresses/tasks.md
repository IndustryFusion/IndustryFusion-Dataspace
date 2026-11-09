# Tasks

## 1. The check

- [x] 1.1 Replace the check in `discovery` with one that applies the three rules to each hosted entry, names the participant and field on failure, and has the new name; verify with the self-test cases in 1.3 and a local run
- [x] 1.2 Read the DSP gateway peer address with `--local` from the management Deployment through `local_cluster.kubectl`, add `--dsp-gateway-peer-url`, strip a trailing slash, and report the address rule as `NOT RUN` without either; verify with a local run, a run with the option, and the case without either in the self-test, as a run against another deployment would need the admin secret by hand
- [x] 1.3 Add self-test cases for an `adapter_url`, a `dsp_url` while not reachable, a `dsp_url` under another address, a `dsp_url` with two segments, and one without `/api/v1/dsp`, plus valid reachable and unreachable entries; verify each wrong case is refused and the valid ones accepted, and that the cases fail against the old check

## 2. Verification

- [x] 2.1 On a local kind cluster with the default settings, run `contract_test.py --local`; verify it has no failures
- [x] 2.2 On that cluster, empty `GATEWAY_PEER_URL` and `DSP_GATEWAY_PEER_URL` on management with `kubectl --kubeconfig .local/kubeconfig`, and run the suite again; verify the hosted peers aren't reachable and the suite passes
- [x] 2.3 Change the gateway temporarily to show a hosted peer's connector address; verify the check fails, naming the participant and `dsp_url`. Then revert

## 3. Documents

- [x] 3.1 State the rule in `gateway-api.md` after the `GET /participants/compatible` example, and name `--dsp-gateway-peer-url` in `CONTRIBUTING.md`'s contract tests section and in the suite's docstring; verify by reading them against the check
