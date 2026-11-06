# Tasks

## 1. Image

- [x] 1.1 Add the modules and build the image on Java 21; verify the image builds and the connector starts against PostgreSQL
- [x] 1.2 Add the key seeding extension; verify the connector logs that it generated the pair, and no startup error about missing keys
- [x] 1.3 Add a template for `connector.properties`; verify ports 8081, 8082, 8083 and 8084 answer as configured, and that the management API refuses a request with no key

## 2. Transfer

- [x] 2.1 Add `scripts/connector-transfer-check.py`, and the local manifests for two connectors; verify a negotiation and an `HttpData-PUSH` transfer complete, and the same bytes arrive
- [x] 2.2 Restart a connector with an asset registered; verify the asset is still there
- [x] 2.3 Confirm no route offered to other participants goes to the control port; verify the DSP callback address and the Service definitions
- [x] 2.4 Check each scenario in the delta spec and report the result per scenario in the Pull Request; verify the report covers every scenario

## 3. Review follow-up

- [x] 3.1 Record the mock DSP identity as a known limit in `architecture.md`; verify by reading the EDC Connector section
- [x] 3.2 Add the licence header to the service registration file; verify the connector image builds and starts with its extension

## Workflow follow-up

- After merge, archive with the other milestone changes in a follow-up Pull Request with `Closes #8`.
