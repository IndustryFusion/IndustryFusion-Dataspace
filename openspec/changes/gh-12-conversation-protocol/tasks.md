# Tasks

## 1. Rules

- [x] 1.1 Implement the validity rules as one function; verify a table-driven test of every performative against every field
- [x] 1.2 Implement the state rules as one function; verify a table-driven test of every performative against every state, and each side

## 2. Sender

- [x] 2.1 Apply validity and state in `POST /outbox/messages` and `POST /outbox/files`, under a row lock; verify tests for each scenario in "Conversation state rules"
- [x] 2.2 Store a refused message for audit, and remove its content; verify tests for the row, the body and that nothing reaches the receiver
- [x] 2.3 Deliver one conversation's messages in the order accepted; verify a test that holds the first delivery and checks the order

## 3. Receiver

- [x] 3.1 Apply validity, state and counterpart at notification; verify tests for each refusal, the audit row and no transfer
- [x] 3.2 Honour `sender_applied`, and settle simultaneous `close` and `escalate`; verify tests for each order of ids
- [x] 3.3 Add the new column to an existing table on start; verify a test that upgrades an older table

- [x] 3.4 Apply the role rules at notification; verify tests
- [x] 3.5 Carry `based_on`, settle any crossing steps, and refuse to reopen a settled state; verify deterministic tests for each id order and for a forged step
- [x] 3.6 Let a repeat replace a failed step, at accept and at delivery; let the other side's step win over a failed one; take the receiver's copy from its answer; verify tests with notifications that fail
- [x] 3.7 Keep a refused row refused, and hide the conversation from another counterpart; verify tests
- [x] 3.8 Resolve the delivery gate when accepting is cancelled; verify a test

## 4. Routes

- [x] 4.1 Add `GET /conversations` and `GET /conversations/{id}`; verify tests for the fields, the filter in any case, unknown ids, `replied_at` and `outstanding_requests`
- [x] 4.2 Check inbox fields, including a grant's authorization; verify a test

## 5. Two-sided tests on PostgreSQL

- [x] 5.1 Build a harness with two real adapter apps, each on its own PostgreSQL database, notifying each other; verify it fails if the receiver's rules are removed
- [x] 5.2 Verify both end in the same state for request and reply, grant, deny, cancel, close, escalate and deescalate, reopen, and simultaneous close
- [x] 5.3 Verify a refused message shows `rejected` at the sender, and the resulting difference matches `protocol.md`
- [x] 5.4 Verify bursts and races: messages on one conversation, closes racing on one side, and messages racing with a close

## 6. Documents

- [x] 6.1 Update `protocol.md` with settlement, ordering, the refusal difference and the states it doesn't name; update `gateway-api.md` with the additive fields; verify by reading against the delta spec

## 7. End to end

- [x] 7.1 Extend `scripts/message-exchange-check.py` with each flow, simultaneous close and concurrent bursts on one conversation; verify on the local cluster
- [x] 7.2 Check each scenario in the delta spec and report the result per scenario in the Pull Request; verify the report covers every scenario

## Workflow follow-up

- After merge, archive in a follow-up Pull Request with `Closes #12`.
