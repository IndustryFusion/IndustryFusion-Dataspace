# Spec Delta

## Purpose

The deployment guide moves to `helm/README.md`.

## MODIFIED Requirements

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
