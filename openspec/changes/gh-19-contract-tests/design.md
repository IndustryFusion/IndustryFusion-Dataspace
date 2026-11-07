# Design

## Context

`gateway-api.md` leads on the contract, and `flow.md` on the flows. Scripts here use only the Python standard library, so that they run anywhere without installing anything.

## Decisions

### Three files

| File | What it is |
|---|---|
| `scripts/dataspace_client.py` | The client: a class for use from Python, and a command line over it. It knows nothing of the cluster |
| `scripts/mock_agent.py` | Polls and answers through the client, as an agent does. It takes the same credentials |
| `scripts/contract_test.py` | The suite. It takes credentials, or creates its own participants through the management API, and removes them |

### Shapes are exact, and written out

Each answer is checked against a table copied by hand from `gateway-api.md`: each field's type, whether it may be null, and allowed values. **A field that isn't listed fails too.** So an unintended addition is seen, and adding a field to the contract means adding it here. Alternative: generating these from `asyncapi.yaml`, which covers less than `gateway-api.md` and doesn't lead on this contract.

### Showing that it can fail

Two ways, as the issue requires a wrong shape to fail:

- `--self-test` needs no deployment, and runs in CI on every Pull Request. For each table it builds a valid answer, shows it passes, then removes each field, changes its type and adds a field, and shows each of those fails.
- `--tamper <route>:<field>` runs the suite through a small proxy in front of the gateway, that removes a field from one route's real answers. The run must fail, naming that field.

### Deployments

`--local` uses the environment from `scripts/local-env.sh`, reaching services by port-forward, whether it was deployed with `services` or by Helm. Otherwise the suite takes URLs. With `--management-url` and an admin secret it creates its own participants. With `--owner` and `--builder` it uses existing ones.

A suite run creates new conversations, so it can repeat against the same participants.

### What is not run

External flows are listed as not run, and don't count as a pass or a failure. A report line says so, as those flows need #18.

### CI job

`.github/workflows/contract.yml` runs on `workflow_dispatch` only, as it builds every image and creates a cluster. It can't be run from a branch until it reaches the default branch, as GitHub requires.

## Conflicts

`AGENTS.md` asks for the `spec-approved` label before implementation. A maintainer approved this milestone outside GitHub and the label is pending, as the Pull Request states.
