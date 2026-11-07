# Tasks

## 1. UI

- [ ] 1.1 Add the application and the Health screen; verify browser tests, including a component going down and the 15-second timing on a fake clock
- [ ] 1.2 Add the Participants screen; verify browser tests for each action and each error
- [ ] 1.3 Add the Policies screen; verify browser tests for approve, deny and reset, and an external side
- [ ] 1.4 Add admin mode; verify browser tests for the actions being absent, storage being empty, a reload, refreshing and a refused token

## 2. Serving

- [ ] 2.1 Serve the built files from the API; verify tests, including paths outside the folder
- [ ] 2.2 Build the UI into the image; verify on the local cluster that the running image serves it
- [ ] 2.3 Run the browser tests in CI; verify a run, and that a deliberately broken screen fails them

## 3. End to end

- [ ] 3.1 Run the browser tests against a deployment on the local cluster, with real participants; verify register, credentials, reachability and delete through the browser

## 4. Report

- [ ] 4.1 Check each scenario in the delta specs and report the result per scenario in the Pull Request; verify the report covers every scenario
