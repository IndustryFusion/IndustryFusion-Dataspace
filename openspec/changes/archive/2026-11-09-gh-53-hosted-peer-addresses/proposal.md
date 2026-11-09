# Proposal

Issue: #53

## Why

Since #40, a hosted participant is externally reachable by default when the gateway and DSP gateway peer addresses are set, as they are in the local cluster. For such a participant, `GET /participants/compatible` returns its `dsp_url` on the DSP gateway, as the gateway is meant to. The contract suite's check "A hosted peer's addresses inside the hub are left out" still requires every hosted entry's `dsp_url` to be empty. So `contract_test.py --local` reports one failure on main, which #50 recorded as open.

## What Changes

- **The contract suite's check on hosted peers** in `GET /participants/compatible` follows the rule. For each hosted entry:
  - `adapter_url` is null.
  - `dsp_url` is null when `externally_reachable` is false.
  - When `externally_reachable` is true, `dsp_url` is the participant's address on the DSP gateway: the deployment's DSP gateway peer address, one path segment, then `/api/v1/dsp`.
- **The check's name** says what it checks.
- **Where the suite gets the peer address:**
  - With `--local`, it reads `DSP_GATEWAY_PEER_URL` from the management Deployment through the local cluster's own kubeconfig.
  - Against another deployment, a new option `--dsp-gateway-peer-url` gives it.
  - Without either, the part of the check that needs the address is reported as not run, and the rest still runs.
- **`--self-test`** shows that the check refuses each wrong entry: an `adapter_url`, a `dsp_url` while not reachable, and a `dsp_url` that isn't on the DSP gateway.
- **`gateway-api.md`** states the same rule for `GET /participants/compatible`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `contract-tests`: the check on hosted peers' addresses, and how the suite gets the DSP gateway's peer address.
- `api-gateway`: "Compatible participants" says what a reachable hosted peer's `dsp_url` is.

## Out of Scope

- How reachability is decided (#40).
- Storage isolation (#38).
- Any change to the gateway, management or registry, unless the check finds the gateway showing an address that only works inside the hub. In that case the gateway is fixed, not the test.

## Impact

- `manifest.md`: none affected.
- `architecture.md`: none affected.
- `gateway-api.md`: the paragraph after the `GET /participants/compatible` example.
- `CONTRIBUTING.md`: the contract tests section names `--dsp-gateway-peer-url`.
- `scripts/contract_test.py`: the check in `discovery`, a new option, and new self-test cases.
