# Spec Delta

## Purpose

The UI registers a hosted participant as reachable unless the administrator says otherwise, as the API does.

## ADDED Requirements

### Requirement: Registration form starts reachable

The Participants screen's registration form SHALL start with reachability ticked, and SHALL send the value shown.

#### Scenario: Registering with the starting value
- **WHEN** an administrator registers a hosted participant without touching the reachability box
- **THEN** the request has `externally_reachable` true

#### Scenario: Unticking it
- **WHEN** an administrator unticks the box and registers
- **THEN** the request has `externally_reachable` false
