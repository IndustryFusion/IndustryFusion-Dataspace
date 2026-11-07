# Tasks

## 1. Service

- [x] 1.1 Add configuration and token checks; verify tests for each admin route without a token, with a wrong signature, issuer and expiry, and without the role
- [x] 1.2 Add the token route; verify tests for good and wrong credentials and an unreachable Keycloak
- [x] 1.3 Add the database, Keycloak, Kubernetes, registry and storage steps; verify tests for each, on real PostgreSQL for the databases
- [x] 1.4 Add registration with undo; verify a test injecting a failure at every step, for a new and an existing participant, checking what remains
- [x] 1.5 Complete half-finished clients, and refuse foreign clients and slug collisions; verify tests
- [x] 1.6 Serialise requests per participant; verify a test with two concurrent registrations, one failing
- [x] 1.7 Add removal; verify tests for hosted, external, unknown, a failing step and a repeat
- [x] 1.8 Add reads and credentials; verify tests
- [x] 1.9 Add capability routes and the policy view; verify tests, including that the internal key never goes to an external address, and against real adapters in 3.4
- [x] 1.10 Add health; verify tests with a component down, and that details hold no credentials

## 2. Local environment

- [x] 2.1 Add the service and its RBAC to `scripts/local-env.sh services`; verify it starts on the local cluster

## 3. End to end

- [x] 3.1 Script: register two participants through the API, exchange a message through the gateway, delete them, and check for orphans in Kubernetes, PostgreSQL, Keycloak and storage; verify on the local cluster
- [x] 3.2 Inject failures at each step on the local cluster with a wrong image and a stopped dependency; verify nothing remains
- [x] 3.3 Check that existing participants' objects don't change when one is added; verify by comparing resource versions on the local cluster
- [x] 3.4 Reset through the management routes on the local cluster; verify access goes back to the default

## 4. Documents

- [x] 4.1 Update `management-api.md`, `keycloak.md` and `CONTRIBUTING.md`; verify they match the routes and configuration
- [x] 4.2 Check each scenario in the delta specs and report the result per scenario in the Pull Request; verify the report covers every scenario
