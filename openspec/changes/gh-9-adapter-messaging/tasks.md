# Tasks

## 1. Service

- [ ] 1.1 Implement configuration, storage and the database tables; verify unit tests, and that a dropped table is recreated by the monitor
- [ ] 1.2 Implement token checks for agents and peers; verify tests for a missing token, wrong issuer, wrong signature and wrong role
- [ ] 1.3 Implement the connector client; verify unit tests including polling, a terminated negotiation and a timeout
- [ ] 1.4 Implement the outbox routes and send flow; verify tests for each status, an unregistered receiver, an incompatible receiver and both of `payload` and `content_ref`
- [ ] 1.5 Implement the internal routes and receive flow; verify tests for a wrong sender, a wrong receiver, a duplicate id and an empty payload
- [ ] 1.6 Implement the inbox routes; verify tests for the filter, order, repeated acknowledge and field set
- [ ] 1.7 Make inbox status updates conditional; verify a test where a late status update doesn't overwrite `received`
- [ ] 1.8 Implement retention; verify tests with shortened intervals, for content and for rows, including that rows that aren't final are kept

## 2. End to end

- [ ] 2.1 Add `scripts/message-exchange-check.py`; verify two adapters on the local cluster exchange JSON in both directions through their connectors, including an empty payload
- [ ] 2.2 Check each scenario in the delta spec and report the result per scenario in the Pull Request; verify the report covers every scenario

## Workflow follow-up

- After merge, archive with the other milestone changes in a follow-up Pull Request with `Closes #9`.
