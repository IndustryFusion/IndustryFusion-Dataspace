# edc-connector Specification

## Purpose
Defines the connector each participant runs: how it is packaged and configured, and how it negotiates and transfers data with other connectors.

## Requirements

### Requirement: One image for control and data plane
There SHALL be one connector image, running control plane and data plane in one process.

#### Scenario: Connector starts
- **WHEN** the image starts with a configuration file and a reachable database
- **THEN** the connector becomes ready, and its management, DSP, control and public ports answer

### Requirement: Separate configuration and storage
Each connector SHALL be configured from a mounted file and environment variables, and SHALL keep its state in its own database.

#### Scenario: State survives a restart
- **WHEN** an asset is registered and the connector restarts
- **THEN** the asset is still there

### Requirement: Protected management API
The management API SHALL require the configured key.

#### Scenario: Request with no key
- **WHEN** a request reaches the management API with no key or a wrong key
- **THEN** it is refused

#### Scenario: Request with the key
- **WHEN** a request carries the configured key
- **THEN** it is served

### Requirement: Key pair generated at start
The connector SHALL generate a new RSA key pair for its data plane in its in-memory vault at each start.

#### Scenario: Fresh start
- **WHEN** the connector starts with an empty vault
- **THEN** it starts with no missing-key error

### Requirement: Negotiation and transfer between connectors
Two connectors SHALL complete a contract negotiation and a push transfer over HTTP.

#### Scenario: Transfer
- **WHEN** one connector offers an asset backed by an HTTP source, and the other negotiates it and requests a push to an HTTP destination
- **THEN** the negotiation finalizes, the transfer completes, and the destination receives the same bytes as the source

### Requirement: Control port not offered to participants
No route offered to other participants SHALL lead to a connector's control port.

#### Scenario: Addresses given to other participants
- **WHEN** a connector's addresses for other participants are inspected
- **THEN** they use the DSP and public ports only
