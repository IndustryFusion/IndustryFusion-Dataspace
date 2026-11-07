# Tasks

## 1. Demo participants

- [ ] 1.1 Give `DEMO_PARTICIPANTS` its default for unset or empty, read the JSON form and the comma-separated form, and treat `[]` as none; verify with unit tests for each form, the default and `[]`
- [ ] 1.2 Stop the service at start for a value that can't be used, logging the setting and the problem; verify with tests for each kind of bad value, and by starting the image with one and reading its exit status and log
- [ ] 1.3 Stop the local environment's settings from overriding the default; verify with `scripts/check-helm-values.py` and by reading the rendered environment

## 2. Reachability

- [ ] 2.1 Register a hosted participant left without the flag as reachable, and an external one as not; verify with tests, including a repeated registration without the flag
- [ ] 2.2 Register as not reachable where a peer address is missing, with `warnings` in the answer and in each `POST /api/demo` record, and none on reads; verify with tests for each missing setting, explicit `true`, the default and the demo
- [ ] 2.3 Start the UI form's reachability box ticked; verify with a browser test that the request carries `true`, and `false` once unticked

## 3. IFRIC reader

- [ ] 3.1 Default `IFRIC_READER_CLIENT_ID` to `dataspace-ifric-reader`; verify with tests that the token is asked for with that id, and that nothing is called without the URL or the secret

## 4. End to end

- [ ] 4.1 On a fresh install on a local cluster without `DEMO_PARTICIPANTS`, call `POST /api/demo`, and have the factory owner exchange a message with each machine builder through the gateway; verify on a local cluster
- [ ] 4.2 Register a hosted participant without the flag, and exchange a message with files and a capability request with an external participant from `scripts/external-demo.py`; verify on a local cluster

## 5. Documents

- [ ] 5.1 Update `management-api.md`, `keycloak.md`, `architecture.md` and `deploy/README.md` for the defaults, the JSON form, `warnings` and the hop that reachability adds; verify by reading them against the behaviour
