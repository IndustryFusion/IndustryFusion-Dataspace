# Tasks

## 1. Client and mock agent

- [x] 1.1 Add the client; verify each subcommand against the local environment
- [x] 1.2 Add the mock agent; verify it answers a request and a close against the local environment

## 2. Suite

- [x] 2.1 Add a shape table for each answer in `gateway-api.md`; verify with `--self-test`, which also runs in CI
- [x] 2.2 Check each route, status value and error; verify against the local environment
- [x] 2.3 Add the flows in `flow.md`, and the worked scenario; verify against the local environment
- [x] 2.4 Show a wrong shape fails with `--tamper`; verify against the local environment, naming the route and field
- [ ] 2.5 Show that wrong values fail too, with `--tamper`: an inverted `applied`, swapped sides, a state, outcome or `conversation_state` the contract doesn't name, an `error_message` on success, a bad date-time, and a rule matching nothing; verify against the local environment

## 3. Deployments

- [x] 3.1 Pass against the local environment from `scripts/local-env.sh services`; verify a run
- [x] 3.2 Pass against a Helm install from `deploy/README.md`; verify a run
- [ ] 3.3 Pass through an Ingress. Needs an Ingress controller, whose install was refused here. The suite goes to the gateway's Service instead

## 4. Running it

- [x] 4.1 Add the workflow and the instructions; verify the workflow's steps by running the same commands by hand. It can't be started until it is on the default branch

## 5. Report

- [x] 5.1 Check each scenario in the delta specs and report the result per scenario in the Pull Request; verify the report covers every scenario
