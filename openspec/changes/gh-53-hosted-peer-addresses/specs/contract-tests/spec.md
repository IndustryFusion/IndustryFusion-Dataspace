# Spec Delta

## Purpose

The contract suite checks hosted peers' addresses as they are since hosted participants became reachable by default.

## ADDED Requirements

### Requirement: Hosted peers' addresses

For each hosted entry in `GET /participants/compatible`, the contract suite SHALL require a null `adapter_url`, a null `dsp_url` when not `externally_reachable`, and otherwise a `dsp_url` under the DSP gateway peer address, with one path segment and `/api/v1/dsp`. With `--local` it SHALL read that address from management's `DSP_GATEWAY_PEER_URL` through the local kubeconfig, else from `--dsp-gateway-peer-url`, and else report that part as not run.

#### Scenario: Reachable hosted peers on the local cluster
- **WHEN** `contract_test.py --local` runs on a local cluster with the default settings, where hosted participants are reachable
- **THEN** the check passes, and the suite has no failures

#### Scenario: Hosted peers that aren't reachable
- **WHEN** the peer addresses are unset on management, and the suite runs
- **THEN** it requires each hosted peer's `dsp_url` to be null, and passes

#### Scenario: A cluster address that is the configured peer address
- **WHEN** the configured DSP gateway peer address is a cluster Service name, as on the local cluster
- **THEN** a `dsp_url` under it is accepted, and any `dsp_url` not under it is refused, such as the connector's or adapter's own address

#### Scenario: A wrong entry
- **WHEN** a hosted entry has an `adapter_url`, a `dsp_url` while not reachable, or a `dsp_url` that isn't under the DSP gateway peer address in that form
- **THEN** the check fails, naming the participant and the field

#### Scenario: The self-test
- **WHEN** `contract_test.py --self-test` runs
- **THEN** each of those wrong entries is refused, and a valid reachable and a valid unreachable entry are accepted

#### Scenario: Another deployment
- **WHEN** the suite runs against another deployment with `--dsp-gateway-peer-url`
- **THEN** it checks reachable hosted peers against that address

#### Scenario: No peer address known
- **WHEN** the suite runs against another deployment without `--dsp-gateway-peer-url`
- **THEN** the null checks still run, and the address check is reported as not run, naming the option

#### Scenario: Only the local kubeconfig
- **WHEN** `--local` reads management's settings
- **THEN** it uses `.local/kubeconfig`, and no other cluster is contacted
