# Tasks

## 1. Demo participants

- [x] 1.1 Give `DEMO_PARTICIPANTS` its default for unset or empty, read the JSON form and the comma-separated form, and treat `[]` as none; verify with unit tests for each form, the default and `[]`
- [x] 1.2 Stop the service at start for a value that can't be used, logging the setting and the problem; verify with tests for each kind of bad value, and by starting the image with one and reading its exit status and log
- [x] 1.3 Stop the local environment's settings from overriding the default; verify with `scripts/check-helm-values.py` and by reading the rendered environment

## 2. Reachability

- [x] 2.1 Register a hosted participant left without the flag as reachable, and an external one as not; verify with tests, including a repeated registration without the flag
- [x] 2.2 Register as not reachable where a peer address is missing, with `warnings` in the answer and in each `POST /api/demo` record, and none on reads; verify with tests for each missing setting, explicit `true`, the default and the demo
- [x] 2.3 Start the UI form's reachability box ticked; verify with a browser test that the request carries `true`, and `false` once unticked
- [x] 2.4 Show the `warnings` of registering, "Make reachable" and the demo participants on the Participants screen, as text only; verify with browser tests where the answer has a warning, has none, or has one that isn't text

## 3. IFRIC reader

- [x] 3.1 Default `IFRIC_READER_CLIENT_ID` to `dataspace-ifric-reader`; verify with tests that the token is asked for with that id, and that nothing is called without the URL or the secret

## 4. End to end

- [x] 4.1 On a fresh install on a local cluster without `DEMO_PARTICIPANTS`, call `POST /api/demo`, and have the factory owner exchange a message with each machine builder through the gateway; verify on a local cluster
- [x] 4.2 Register a hosted participant without the flag, and exchange a message with files and a capability request with an external participant from `scripts/external-demo.py`; verify on a local cluster

## 5. Documents

- [x] 5.1 Update `management-api.md`, `keycloak.md`, `architecture.md` and `deploy/README.md` for the defaults, the JSON form, `warnings` and the hop that reachability adds; verify by reading them against the behaviour
- [x] 5.2 Correct `keycloak.md` and `architecture.md` to say that a participant's id is its company's `company_ifric_id`; verified by reading them, and by a search showing no document, code or test states or enforces the opposite
