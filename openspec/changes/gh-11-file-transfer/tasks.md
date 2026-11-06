# Tasks

## 1. Adapter

- [ ] 1.1 Add `POST /outbox/files`, reading the form after authentication; verify tests for several files, no files, no receiver, an incompatible and an unregistered receiver, and no token
- [ ] 1.2 Bundle files with safe names; verify tests for a path in a name, a repeated name and an empty name
- [ ] 1.3 Store and read content as streams, and serve the payload route as a stream; verify a test that the connector's read gets the same bytes
- [ ] 1.4 Store received content by kind, and mark `has_files`; verify tests that a ZIP arrives at `files/{id}.zip` and reads with `payload` `{"_bundle": true}`
- [ ] 1.5 Add `GET /inbox/messages/{id}/download`; verify tests for the same bytes, no files, not arrived, purged and another participant's message
- [ ] 1.6 Enforce `MAX_UPLOAD_BYTES` at the outbox and on arrival; verify tests with a stated length, with no stated length, and that nothing is stored
- [ ] 1.7 Confirm retention removes file content; verify a test
- [ ] 1.8 Confirm a storage failure leaves no message and no temporary file; verify a test
- [ ] 1.9 Show concurrent uploads each keep their own bytes; verify a test on PostgreSQL

## 2. Gateway

- [ ] 2.1 Stream request and answer bodies; verify existing forwarding tests still pass, and a new test with a body that arrives in parts
- [ ] 2.2 Enforce the limit; verify tests with a stated length and with no stated length

## 3. Documents and deployment

- [ ] 3.1 Update `gateway-api.md` with the limit and `413`, and `architecture.md` with the setting; verify by reading against the delta specs
- [ ] 3.2 Set `MAX_UPLOAD_BYTES` in the local deployment; verify on the local cluster that the gateway and adapter use it

## 4. End to end

- [ ] 4.1 Extend `scripts/message-exchange-check.py` to transfer several files and compare bytes, with a reply link; verify on the local cluster
- [ ] 4.2 Transfer a file near the limit through the gateway, and record the gateway's peak memory; verify on the local cluster
- [ ] 4.3 Verify a file through an Ingress at the configured body size. This needs #15
- [ ] 4.4 Check each scenario in the delta specs and report the result per scenario in the Pull Request; verify the report covers every scenario

## Workflow follow-up

- After merge, archive in a follow-up Pull Request with `Closes #11`.
