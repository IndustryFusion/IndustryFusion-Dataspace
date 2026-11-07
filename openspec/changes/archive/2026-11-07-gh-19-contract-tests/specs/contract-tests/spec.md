## ADDED Requirements

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
- **WHEN** it runs against the local environment or a deployment from `deploy/README.md`
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
