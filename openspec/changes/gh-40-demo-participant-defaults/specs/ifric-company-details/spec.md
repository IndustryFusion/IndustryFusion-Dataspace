# Spec Delta

## Purpose

The IFRIC reader's client id has a default.

## MODIFIED Requirements

### Requirement: IFRIC unavailable or not configured

If IFRIC is unreachable, refuses or is not configured, the fields SHALL be left out and nothing else SHALL change. `IFRIC_READER_CLIENT_ID` SHALL default to `dataspace-ifric-reader` when unset or empty.

#### Scenario: Not configured
- **WHEN** `IFRIC_BACKEND_URL` or `IFRIC_READER_CLIENT_SECRET` is missing
- **THEN** reads return plain records, and no call goes to Keycloak or IFRIC

#### Scenario: The default client id
- **WHEN** `IFRIC_BACKEND_URL` and `IFRIC_READER_CLIENT_SECRET` are set, and `IFRIC_READER_CLIENT_ID` is unset or empty
- **THEN** the reader's token is asked for with the client id `dataspace-ifric-reader`, and reads have the company details

#### Scenario: Unreachable
- **WHEN** IFRIC doesn't answer, or answers with an error
- **THEN** reads return `200` with plain records

#### Scenario: The reader's token is refused
- **WHEN** Keycloak refuses the reader's credentials
- **THEN** reads return `200` with plain records, and the secret isn't logged or returned

#### Scenario: An answer that isn't a list of companies
- **WHEN** IFRIC answers with something else, or with entries lacking an id
- **THEN** reads return `200`, with the details of whatever entries were usable
