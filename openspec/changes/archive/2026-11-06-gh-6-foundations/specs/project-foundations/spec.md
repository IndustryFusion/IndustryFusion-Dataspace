# Spec Delta

## Purpose

Defines how services in this repository are laid out, built and tested.

## ADDED Requirements

### Requirement: One directory per service
The repository SHALL have one directory per service, each with its own tests and image build.

#### Scenario: Service directories exist
- **WHEN** a contributor looks at the repository root
- **THEN** there are directories for the gateway, registry, adapter, connector, DSP gateway and management service

#### Scenario: Skeleton answers
- **WHEN** a service image built from this change is started
- **THEN** its health route answers successfully, or for the connector the process starts

### Requirement: Recorded conventions
The test, lint and build conventions SHALL be recorded in the contributor guide and the project context.

#### Scenario: Contributor finds the conventions
- **WHEN** a contributor reads the contributor guide
- **THEN** it states how to lint, test and build a service

### Requirement: CI for services
CI SHALL lint and test every Python service, and build an image for every service.

#### Scenario: Failing test fails CI
- **WHEN** a change makes a service's test fail
- **THEN** the CI check for that service fails

#### Scenario: All images are built
- **WHEN** a Pull Request touches a service
- **THEN** CI builds that service's image

### Requirement: No committed credentials
The repository SHALL contain no credentials, and files generated with credentials SHALL be ignored by version control.

#### Scenario: Generated files are ignored
- **WHEN** the local environment has been brought up
- **THEN** version control shows no generated credential files
