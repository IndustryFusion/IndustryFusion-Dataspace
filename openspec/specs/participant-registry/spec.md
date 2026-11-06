# participant-registry Specification

## Purpose
Defines the directory of participants and the rules for which roles may communicate.

## Requirements

### Requirement: Participant records
The registry SHALL create or update, read, list and delete participant records holding the participant id, type, adapter URL, DSP URL, hosted flag, external reachability and peer notification URL.

#### Scenario: Create and read
- **WHEN** a participant is created and then read by id
- **THEN** the same record is returned

#### Scenario: Update
- **WHEN** a participant is created again with the same id and a different adapter URL
- **THEN** one record exists, with the new adapter URL

#### Scenario: List by type
- **WHEN** participants of two types exist and the list is filtered by one type
- **THEN** only participants of that type are returned

#### Scenario: Unknown participant
- **WHEN** an unknown id is read or deleted
- **THEN** the answer is not found

#### Scenario: Delete
- **WHEN** a participant is deleted
- **THEN** reading it gives not found

### Requirement: Role names
The registry SHALL accept a role as a bare name, a prefixed name or a full IRI, store it as the full IRI, and reject unknown roles.

#### Scenario: Three spellings
- **WHEN** a participant is created with `machine_builder`, `ds:machine_builder` or the full IRI
- **THEN** the stored type is the same full IRI each time

#### Scenario: Unknown role
- **WHEN** a participant is created with a role that is not known
- **THEN** it is refused, and nothing is stored

### Requirement: Role compatibility
The registry SHALL decide compatibility from one list of directed role pairs.

#### Scenario: Compatible participants
- **WHEN** a factory owner asks who it may communicate with
- **THEN** machine builders are returned, and not itself or other factory owners

#### Scenario: One-directional rule
- **WHEN** a third role is added with a rule in one direction only
- **THEN** it appears for the role that may reach it, and that role does not appear for it

#### Scenario: Unknown participant
- **WHEN** compatibility is asked for an unknown id
- **THEN** the answer is not found

### Requirement: Durable storage
The registry SHALL keep records in its own database, and SHALL create that database if it is missing.

#### Scenario: Restart
- **WHEN** the service restarts
- **THEN** its records are still there

#### Scenario: Missing database
- **WHEN** the service starts and its database does not exist
- **THEN** it creates the database and works normally

### Requirement: Waits for the database
The registry SHALL keep running when its database is unavailable, retry every 5 seconds, and report that it is unavailable.

#### Scenario: Database down at start
- **WHEN** the service starts with its database unavailable
- **THEN** the process keeps running, the health route answers, and other routes answer service unavailable

#### Scenario: Database returns
- **WHEN** the database becomes available
- **THEN** the routes start working with no restart

### Requirement: Cluster-internal access
The registry SHALL have no public route.

#### Scenario: Deployment
- **WHEN** the registry is deployed
- **THEN** it is reachable only inside the cluster
