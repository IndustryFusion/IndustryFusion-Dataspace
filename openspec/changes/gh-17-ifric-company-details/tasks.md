# Tasks

## 1. Service

- [x] 1.1 Add the lookup with its cache; verify tests for IFRIC available, unavailable, refusing, not configured, a bad answer, cache expiry, concurrent reads and recovery after a failure
- [x] 1.2 Add the fields to the three reads; verify tests, including that the rest of the record is unchanged, and that a write doesn't carry them

## 2. Deployment and documents

- [x] 2.1 Add the settings to the chart, with the credentials in the Secret; verify `scripts/check-helm-values.py`
- [x] 2.2 Document identifiers and the shared realm in `keycloak.md` and `architecture.md`; verify against the requirement

## 3. End to end

- [x] 3.1 On the local cluster, with real Keycloak and a stand-in for the registry that checks the reader's token: available, then unavailable, then not configured; verify with a script
- [ ] 3.2 Run against a real IFRIC registry. Needs that service and its dependencies, and any token check of its own

## 4. Report

- [x] 4.1 Check each scenario in the delta specs and report the result per scenario in the Pull Request; verify the report covers every scenario
