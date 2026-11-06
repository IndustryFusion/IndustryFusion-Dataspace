# Tasks

## 1. Service

- [x] 1.1 Implement role normalization and compatibility; verify unit tests for all three spellings, unknown roles and a one-directional third role
- [x] 1.2 Implement the PostgreSQL store, creating the database if missing; verify against a real PostgreSQL that records survive a restart of the store
- [x] 1.3 Implement the routes and errors; verify API tests cover every route
- [x] 1.4 Connect in the background, retrying every 5 seconds; verify a test where the database is unavailable at first, and that the service answers health and gives `503` until it connects

## 2. Delivery

- [x] 2.1 Build the image and deploy it to the local environment with `scripts/local-env.sh`; verify the routes through a port-forward, and that a pod restart keeps records
- [x] 2.2 Confirm the deployment has no Ingress; verify by listing Ingress objects
- [x] 2.3 Run the tests needing PostgreSQL in CI; verify in CI, or by running the same steps locally
- [x] 2.4 Check each scenario in the delta spec and report the result per scenario in the Pull Request; verify the report covers every scenario

## 3. Review follow-up

- [x] 3.1 Report the service as unavailable when the database goes away after startup; verify tests with lost-connection errors on every route, and one that terminates the connections on a real PostgreSQL

## Workflow follow-up

- After merge, archive with the other milestone changes in a follow-up Pull Request with `Closes #7`.
