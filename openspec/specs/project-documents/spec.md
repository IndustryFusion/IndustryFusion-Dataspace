# project-documents Specification

## Purpose
Defines which project documents exist, which one leads on each subject, and what each must cover, so that services and agent applications can be built from them.

## Requirements

### Requirement: Each document leads on its own subject
The project documents SHALL state which document leads on each subject: design, goals and definition of done, message semantics, the agent HTTP contract and the administration HTTP contract.

#### Scenario: Reader finds the leading document
- **WHEN** a reader wants the authoritative description of message semantics
- **THEN** the documents direct them to one document, and no other document gives a different description

### Requirement: Recorded deployment and component decisions
The project documents SHALL consistently describe Kubernetes as the deployment target, one combined control and data plane per participant, and S3-compatible object storage.

#### Scenario: Documents agree
- **WHEN** a reader compares the design document, the goals document and the project context on deployment, connector layout and storage
- **THEN** they give the same answer

#### Scenario: No open differences remain
- **WHEN** a contributor reads the project context
- **THEN** it lists no undecided difference between the project documents

### Requirement: No duplicated document text
The goals document SHALL contain its content once.

#### Scenario: Single copy
- **WHEN** a reader opens the goals document
- **THEN** its title and each section appear exactly once

### Requirement: Published agent contract
The project SHALL publish an agent HTTP contract covering authentication and every agent-facing route, field, status value and error shape.

#### Scenario: Client built from the contract
- **WHEN** a developer builds an agent client using only the contract
- **THEN** it describes how to get a token, discover peers, send a message or file, read send status, poll and acknowledge the inbox, read conversations and use capabilities

#### Scenario: Errors are specified
- **WHEN** a request is refused
- **THEN** the contract documents the status and body shape for that refusal, including conversation state violations and invalid messages

### Requirement: Published message protocol
The project SHALL publish a protocol document defining the performatives, outcomes, conversation states, validity rules and state rules, and a machine-readable description of the messages that names it as the source of truth.

#### Scenario: Validity of a message
- **WHEN** a reader wants to know whether a performative may carry a capability, a reply reference, an authorization or an outcome
- **THEN** the protocol document answers it for each performative

#### Scenario: Capability access is stated
- **WHEN** a reader wants to know what happens when a message names a denied capability
- **THEN** the protocol document states that access is advisory and that the sending application is responsible for checking it

#### Scenario: Known limits are stated
- **WHEN** a behaviour is deliberately not provided
- **THEN** the protocol document lists it as a known limit

### Requirement: Published administration contract
The project SHALL publish an administration contract covering every management route, its authentication, and the steps of participant provisioning and removal.

#### Scenario: Onboarding described
- **WHEN** an administrator wants to add a hosted or an external participant
- **THEN** the contract describes the call to make and what it creates for each type

### Requirement: Published identity setup
The project SHALL publish the identity provider setup: realm, roles, clients, claims, the token issuer requirement and the participant identifier convention.

#### Scenario: Realm set up from the document
- **WHEN** an administrator sets up a new realm by following the document
- **THEN** a token minted from it carries what the gateway and adapter require

### Requirement: Published message walkthrough
The project SHALL publish a step-by-step walkthrough of a message exchange using only routes in the agent contract.

#### Scenario: Walkthrough matches the contract
- **WHEN** a reader follows the walkthrough for a request, reply, file transfer and close
- **THEN** every route it names exists in the agent contract

### Requirement: Design document reflects the system
The design document SHALL include every component in its topology, service table, component breakdown, reachability table and technology stack, and SHALL state that delivery to agents is by polling.

#### Scenario: DSP gateway is described consistently
- **WHEN** a reader looks up the DSP gateway in the design document
- **THEN** it appears in each of those sections, and no statement about public exposure contradicts the external participant flow
