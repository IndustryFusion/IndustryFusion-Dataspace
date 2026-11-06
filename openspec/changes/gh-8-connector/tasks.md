# Tasks

## 1. Image

- [ ] 1.1 Add the modules and build the image on Java 21; verify the image builds and the connector starts against PostgreSQL
- [ ] 1.2 Add the key seeding extension; verify the connector logs that it generated the pair, and no startup error about missing keys
- [ ] 1.3 Add a template for `connector.properties`; verify ports 8081, 8082, 8083 and 8084 answer as configured, and that the management API refuses a request with no key

## 2. Transfer

- [ ] 2.1 Add `scripts/connector-transfer-check.py`, and the local manifests for two connectors; verify a negotiation and an `HttpData-PUSH` transfer complete, and the same bytes arrive
- [ ] 2.2 Restart a connector with an asset registered; verify the asset is still there
- [ ] 2.3 Confirm no route offered to other participants goes to the control port; verify the DSP callback address and the Service definitions
- [ ] 2.4 Check each scenario in the delta spec and report the result per scenario in the Pull Request; verify the report covers every scenario

## Workflow follow-up

- After merge, archive with the other milestone changes in a follow-up Pull Request with `Closes #8`.
