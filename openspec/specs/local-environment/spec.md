# local-environment Specification

## Purpose
Defines how a contributor gets a working environment on one machine.

## Requirements

### Requirement: One command to bring up infrastructure
A contributor SHALL be able to bring up a local Kubernetes cluster with PostgreSQL, S3-compatible storage and Keycloak with one documented command, needing only a container runtime and the documented tools.

#### Scenario: Clean machine
- **WHEN** a contributor runs the documented command with no local cluster present
- **THEN** the namespaces `dataspace`, `dataspace-participants` and `iff` exist, and PostgreSQL, S3 storage and Keycloak are ready

#### Scenario: Removal
- **WHEN** a contributor runs the documented removal command
- **THEN** the local cluster and generated files are gone

### Requirement: Isolated from other clusters
The local environment commands SHALL act only on their own local cluster.

#### Scenario: Other cluster configured
- **WHEN** the contributor's shell points at another cluster and they run a local environment command
- **THEN** that other cluster is not touched

### Requirement: Scripted realm
The realm setup in the identity document SHALL be scripted, and SHALL be safe to repeat.

#### Scenario: Realm contents
- **WHEN** the setup has run
- **THEN** the realm `dataspace`, the role `dataspace-admin` and the client `dataspace-admin-cli` exist, and the client's service account holds the documented roles

#### Scenario: Run twice
- **WHEN** the setup runs a second time
- **THEN** it succeeds and changes nothing

### Requirement: Token issuer matches
A token minted from the local realm SHALL carry the issuer that services are configured with.

#### Scenario: Token minted through a port-forward
- **WHEN** a contributor mints a token from their machine through a forwarded port
- **THEN** its issuer equals the Keycloak URL used by services in the cluster

### Requirement: Host entries script
A script SHALL add and remove local host entries for the environment.

#### Scenario: Adding twice
- **WHEN** the script adds entries twice
- **THEN** each entry appears once

#### Scenario: Removing
- **WHEN** the script removes entries
- **THEN** its entries are gone, and other lines are unchanged
