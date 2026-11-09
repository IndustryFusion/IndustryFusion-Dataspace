# contract-tests Specification

## Purpose
A command-line client, a mock agent and a contract suite that check a running dataspace against the published contract, from outside, as an agent would use it.

## Requirements

### Requirement: Command-line client

A command-line client in `scripts/` SHALL cover token retrieval, sending, polling, acknowledging, downloading, conversations and capabilities, through the gateway and Keycloak only.

#### Scenario: Each operation
- **WHEN** each subcommand runs with valid credentials
- **THEN** it prints the API's JSON answer, and exits with 0

#### Scenario: An error from the API
- **WHEN** the API refuses a request
- **THEN** it prints the API's answer to standard error, with the status, and exits with a non-zero code

#### Scenario: Credentials
- **WHEN** credentials are given in the environment
- **THEN** they are used, and never printed, other than by `token`, which prints a token on request

### Requirement: Mock agent

A mock agent SHALL use the gateway and normal authentication to answer messages for local testing.

#### Scenario: Answering a request
- **WHEN** a `request` reaches it
- **THEN** it acknowledges it, and replies with `inform` in the same conversation with `in_reply_to`

#### Scenario: A closed conversation
- **WHEN** a `close` reaches it
- **THEN** it acknowledges it, and doesn't reply

### Requirement: Contract suite

A contract suite SHALL run the client against a deployment, and check each route, field, status value and error shape in `gateway-api.md`.

#### Scenario: Against a deployment that meets the contract
- **WHEN** it runs against the local environment or a deployment from `helm/README.md`
- **THEN** it passes, and exits with 0

#### Scenario: A wrong response shape
- **WHEN** an answer lacks a field, has a wrong type or value, or has a field the contract doesn't name
- **THEN** it fails, naming the route and field, and exits with a non-zero code

#### Scenario: A self-test without a deployment
- **WHEN** it runs with `--self-test`
- **THEN** each shape's valid answer passes, and each changed one fails

#### Scenario: What wasn't run
- **WHEN** a flow can't run on this deployment
- **THEN** the report lists it as not run, and doesn't count it as passed

#### Scenario: What it leaves
- **WHEN** it created its own participants
- **THEN** it removes them, also after a failure

### Requirement: Scripted scenarios

The suite SHALL run every hosted flow in `flow.md`, and a worked scenario for the first agent application.

#### Scenario: The worked example
- **WHEN** the suite runs the flow in `flow.md`
- **THEN** each step answers as that document says, on both sides

#### Scenario: Other flows
- **WHEN** it runs escalation and reopening
- **THEN** each answers as `flow.md` says

#### Scenario: The worked scenario for an agent application
- **WHEN** a factory owner opens a request with a data file, the machine builder asks for more data, the factory owner grants it, and the conversation closes
- **THEN** each side reads the same conversation, the file arrives with the same bytes, and the grant carries its authorization

### Requirement: Running it

The suite SHALL be runnable by hand and by a CI job on demand, with instructions in `CONTRIBUTING.md`.

#### Scenario: By hand
- **WHEN** a contributor follows `CONTRIBUTING.md`
- **THEN** the suite runs against the local environment

#### Scenario: On demand
- **WHEN** a maintainer starts the workflow
- **THEN** it brings up the local environment, and runs the suite

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
