# Tasks

## 1. Retention

- [ ] 1.1 Stop retention deleting conversations; verify with a test that an idle conversation remains after retention runs, while its messages' content and rows are removed on time, and that the test fails with the old behaviour
- [ ] 1.2 Show that a closed conversation past the row retention period refuses a message without `reopen`; verify with a test

## 2. The answer time

- [ ] 2.1 Add `replied_at` to message rows, through the schema check for existing tables; verify with a test against a table made without the column
- [ ] 2.2 Store the time when a received reply is accepted, and when the receiver accepts a sent reply, keeping the first; verify with tests, including refused replies on both sides, a second reply, and a reply naming a request this adapter doesn't have
- [ ] 2.3 Read `replied_at` from the stored time first, and leave answered requests out of `outstanding_requests`; verify with tests that remove the reply's row, on the side that sent the request and on the side that received it, and that these tests fail without the stored time
- [ ] 2.4 Store the time correctly when replies to the same request are accepted concurrently; verify with a test that runs them at once and checks one time is kept

## 3. Old conversations

- [ ] 3.1 Read a conversation whose message rows are all gone; verify with a test of the state, outcome and empty `messages`
- [ ] 3.2 Continue such a conversation on both sides; verify with the two-sided tests, and on a local cluster with retention periods shortened

## 4. Documents

- [ ] 4.1 Update `protocol.md` "Known limits" and `gateway-api.md` `GET /conversations/{id}`; verify by reading them against the behaviour
