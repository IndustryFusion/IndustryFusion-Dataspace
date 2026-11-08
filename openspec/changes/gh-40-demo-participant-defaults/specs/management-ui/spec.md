# Spec Delta

## Purpose

The UI registers a hosted participant as reachable unless the administrator says otherwise, as the API does, and shows the warnings the API gives when it registers one.

## ADDED Requirements

### Requirement: Registration form starts reachable

The Participants screen's registration form SHALL start with reachability ticked, and SHALL send the value shown.

#### Scenario: Registering with the starting value
- **WHEN** an administrator registers a hosted participant without touching the reachability box
- **THEN** the request has `externally_reachable` true

#### Scenario: Unticking it
- **WHEN** an administrator unticks the box and registers
- **THEN** the request has `externally_reachable` false

### Requirement: Registration warnings are shown

The Participants screen SHALL show each warning in the answer to registering a participant, to changing its reachability and to creating the demo participants, with the participant it concerns. A warning SHALL be shown as text only, and a value that isn't text SHALL NOT be shown.

#### Scenario: A registration that can't be reachable
- **WHEN** an administrator registers a hosted participant and the answer has a warning that it isn't reachable from outside
- **THEN** the screen shows that warning with the participant's id

#### Scenario: Making a participant reachable
- **WHEN** an administrator uses "Make reachable" and the answer has a warning
- **THEN** the screen shows that warning with the participant's id

#### Scenario: Creating the demo participants
- **WHEN** an administrator creates the demo participants and the answer's records have warnings
- **THEN** the screen shows each record's warnings with its participant's id

#### Scenario: No warnings
- **WHEN** the answer has no warnings
- **THEN** no warning is shown

#### Scenario: A warning that isn't text
- **WHEN** a warning in the answer is not text
- **THEN** the screen still renders, and that warning isn't shown
