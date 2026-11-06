# Tasks

## 1. Service

- [x] 1.1 Implement token validation with cached signing keys and one refetch; verify tests for a missing token, wrong signature, wrong issuer and a rotated key
- [x] 1.2 Implement the registry lookup with a 30 second cache; verify tests for the cache, its expiry and an unregistered participant
- [x] 1.3 Implement the health and compatible participants routes; verify tests
- [x] 1.4 Implement the catch-all route; verify a token reaches only its own adapter, with method, query, body and header passed through
- [x] 1.5 Block `internal/*`; verify tests for each way of writing the path
- [x] 1.6 Implement the peer route; verify it reaches the named receiver with any valid token
- [x] 1.7 Map each error to its status; verify a test for each of 401, 403, 502, 503 and 504

## 2. End to end

- [x] 2.1 Change `scripts/message-exchange-check.py` to use only the gateway; verify two agents exchange messages both ways on the local cluster
- [x] 2.2 Verify on the local cluster that one participant's token can't read the other's inbox, and that `internal/*` gives `404`
- [ ] 2.3 Check each scenario in the delta spec and report the result per scenario in the Pull Request; verify the report covers every scenario

## Workflow follow-up

- After merge, archive with the other milestone changes in a follow-up Pull Request with `Closes #10`.
