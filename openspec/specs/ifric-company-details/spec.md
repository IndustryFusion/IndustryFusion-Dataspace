# ifric-company-details Specification

## Purpose
Adds a participant's company details from the IFRIC registry to participant reads, without making the dataspace depend on IFRIC being available.

## Requirements

### Requirement: Company details on participant reads

Participant reads SHALL add `company_name`, `company_category`, `city` and `country` from the IFRIC registry, for a participant whose `participant_id` equals a company's `company_ifric_id`.

#### Scenario: A known company
- **WHEN** `GET /api/participants`, `/api/participants/{id}` or `/api/participants/compatible/{id}` returns a participant that IFRIC knows
- **THEN** the record has those four fields, and its other fields are unchanged

#### Scenario: A participant IFRIC doesn't know
- **WHEN** a participant's id is not a `company_ifric_id`
- **THEN** its record has none of those fields

#### Scenario: A company with some details missing
- **WHEN** IFRIC has no value for a field
- **THEN** that field is left out, and the others are there

#### Scenario: A write
- **WHEN** a participant is registered
- **THEN** none of those fields are written to the participant registry

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

### Requirement: The cache

The result SHALL be cached for `IFRIC_LOOKUP_CACHE_SECONDS`, by default 300.

#### Scenario: Within the time
- **WHEN** reads happen within the time
- **THEN** IFRIC is called once

#### Scenario: After the time
- **WHEN** a read happens after the time
- **THEN** IFRIC is called again, and a change there shows

#### Scenario: Concurrent reads
- **WHEN** many reads arrive as the cache expires
- **THEN** IFRIC is called once

#### Scenario: After a failure
- **WHEN** a call has failed
- **THEN** no further call goes within 30 seconds, or the cache time if shorter, and a later one recovers

### Requirement: Identifiers and the shared realm are documented

`keycloak.md` and `architecture.md` SHALL say that a participant's `participant_id` is its company's `company_ifric_id`, with no mapping table, because the IFRIC registry's access control matches participant ids to `company_ifric_id`. `keycloak.md` SHALL describe the setup of the shared realm.

#### Scenario: Reading the documents
- **WHEN** an administrator sets up a shared realm from `keycloak.md`
- **THEN** it says which client to create, how to give the service its credentials, and that each participant is registered with its company's `company_ifric_id` as `participant_id`

#### Scenario: No statement of the opposite
- **WHEN** the documents are read
- **THEN** none says that a participant id must differ from a `company_ifric_id`
