# Tasks

## 1. Service

- [x] 1.1 Implement configuration, storage and the database tables; verify unit tests, and that a dropped table is recreated by the monitor
- [x] 1.2 Implement token checks for agents and peers; verify tests for a missing token, wrong issuer, wrong signature and wrong role
- [x] 1.3 Implement the connector client; verify unit tests including polling, a terminated negotiation and a timeout
- [x] 1.4 Implement the outbox routes and send flow; verify tests for each status, an unregistered receiver, an incompatible receiver and both of `payload` and `content_ref`
- [x] 1.5 Implement the internal routes and receive flow; verify tests for a wrong sender, a wrong receiver, a duplicate id and an empty payload
- [x] 1.6 Implement the inbox routes; verify tests for the filter, order, repeated acknowledge and field set
- [x] 1.7 Make inbox status updates conditional; verify a test where a late status update doesn't overwrite `received`
- [x] 1.8 Implement retention; verify tests with shortened intervals, for content and for rows, including that rows that aren't final are kept

## 2. End to end

- [x] 2.1 Add `scripts/message-exchange-check.py`; verify two adapters on the local cluster exchange JSON in both directions through their connectors, including an empty payload
- [x] 2.2 Check each scenario in the delta spec and report the result per scenario in the Pull Request; verify the report covers every scenario

## 3. Review follow-up

- [x] 3.1 Keep every concurrent message on a new conversation, and report only a repeated message id as a duplicate; verify concurrent tests on a real PostgreSQL, and a burst through real connectors
- [x] 3.2 Let concurrent sends open one conversation, and leave no object behind when saving fails; verify a concurrent test on a real PostgreSQL and a test that drops the table
- [x] 3.3 Move a row to `error` on any failure in a background task; verify tests with `KeyError`, `ValueError` and database failures
- [x] 3.4 Add the restart limit to `protocol.md`, as `design.md` states; verify by reading its known limits
- [x] 3.5 Use this adapter's clock for an inbox row's time; verify tests with stated times in 1970 and 2999
- [x] 3.6 Keep a row while its content remains; verify a test with an expiry 10 years away
- [x] 3.7 Refuse unsafe peer message ids and quote ids in addresses; verify tests for each unsafe form and a registry address test
- [x] 3.8 Keep late content from replacing acknowledged or purged content; verify two tests
- [x] 3.9 Require `exp` and only RS256; verify two tests
- [x] 3.10 Answer 503 for a storage outage, and keep a list working when one object can't be read; verify tests for each case
- [x] 3.11 Record `edc_transfer_id` when the provider serves content; verify unit tests and the status after a real transfer
- [x] 3.12 Run the schema and retention loops in tests, and test the file marker, conversation purge and initial status; verify the tests

## Workflow follow-up

- After merge, archive with the other milestone changes in a follow-up Pull Request with `Closes #9`.
