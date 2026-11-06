# Tasks

## 1. Rules

- [ ] 1.1 Implement the validity rules as one function; verify a table-driven test of every performative against every field
- [ ] 1.2 Implement the state rules as one function; verify a table-driven test of every performative against every state, and each side

## 2. Sender

- [ ] 2.1 Apply validity and state in `POST /outbox/messages` and `POST /outbox/files`, under a row lock; verify tests for each scenario in "Conversation state rules"
- [ ] 2.2 Store a refused message for audit, and remove its content; verify tests for the row, the body and that nothing reaches the receiver
- [ ] 2.3 Deliver one conversation's messages in the order accepted; verify a test that holds the first delivery and checks the order

## 3. Receiver

- [ ] 3.1 Apply validity, state and counterpart at notification; verify tests for each refusal, the audit row and no transfer
- [ ] 3.2 Honour `sender_applied`, and settle simultaneous `close` and `escalate`; verify tests for each order of ids
- [ ] 3.3 Add the new column to an existing table on start; verify a test that upgrades an older table

## 4. Routes

- [ ] 4.1 Add `GET /conversations` and `GET /conversations/{id}`; verify tests for the fields, the filter in any case, unknown ids, `replied_at` and `outstanding_requests`
- [ ] 4.2 Check inbox fields, including a grant's authorization; verify a test

## 5. Two-sided tests on PostgreSQL

- [ ] 5.1 Build a harness with two real adapter apps, each on its own PostgreSQL database, notifying each other; verify it fails if the receiver's rules are removed
- [ ] 5.2 Verify both end in the same state for request and reply, grant, deny, cancel, close, escalate and deescalate, reopen, and simultaneous close
- [ ] 5.3 Verify a refused message shows `rejected` at the sender, and the resulting difference matches `protocol.md`
- [ ] 5.4 Verify bursts and races: messages on one conversation, closes racing on one side, and messages racing with a close

## 6. Documents

- [ ] 6.1 Update `protocol.md` with settlement, ordering, the refusal difference and the states it doesn't name; update `gateway-api.md` with the additive fields; verify by reading against the delta spec

## 7. End to end

- [ ] 7.1 Extend `scripts/message-exchange-check.py` with each flow, simultaneous close and concurrent bursts on one conversation; verify on the local cluster
- [ ] 7.2 Check each scenario in the delta spec and report the result per scenario in the Pull Request; verify the report covers every scenario

## Workflow follow-up

- After merge, archive in a follow-up Pull Request with `Closes #12`.
