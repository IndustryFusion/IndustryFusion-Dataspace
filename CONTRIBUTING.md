# Contributing

The IndustryFusion Dataspace uses specification-driven development with
[OpenSpec](https://github.com/Fission-AI/OpenSpec). Every change is specified
and approved before it is implemented, and every change is traceable from its
GitHub Issue to its Pull Request and archived specification.

## Lifecycle

| # | Step | Who | Automated? |
|---|---|---|---|
| 1 | Open a feature issue | Contributor | Manual |
| 2 | Create the OpenSpec change proposal, in a Pull Request from a fork | Agent, started by a contributor or maintainer | Agent-assisted |
| 3 | Review the specification | Maintainers | Manual |
| 4 | Approve: add the `spec-approved` label | Maintainer | Manual |
| 5 | Implement the tasks in the same Pull Request | Agent, started by a contributor or maintainer | Agent-assisted |
| 6 | Verify | CI + maintainers | Partly: CI validates artifacts; humans review behavior |
| 7 | Merge | Maintainer | Manual |
| 8 | Archive the change in a follow-up Pull Request, which closes the issue | Agent or maintainer | Agent-assisted (`/opsx:archive`) |

### 1. Propose a feature

Open an issue directly in this repository with the **Feature request** form.
Describe the problem, the desired outcome and, if you can, how to tell that it
works. You do not need a fork, code or OpenSpec for this.

### 2. Create the change proposal

Pull Requests always come from your own fork, including for maintainers. See
[Pull Requests come from forks](#pull-requests-come-from-forks).

Ask a coding agent to create a proposal from the issue, for example in Claude Code:

```
/opsx:propose Issue #42
```

The agent follows [AGENTS.md](AGENTS.md). It creates
`openspec/changes/gh-42-<summary>/` containing:

- `proposal.md`: why, what changes, out of scope; starts with `Issue: #42`
- `specs/<capability>/spec.md`: requirements, each with WHEN/THEN scenarios that serve as acceptance criteria
- `design.md`: architectural implications, decisions and alternatives
- `tasks.md`: implementation checklist, each task with its verification

The Pull Request contains only the proposal and uses `Refs #42`.

### 3–4. Review and approve

Maintainers review the proposal in the Pull Request like any other document:
inline comments, requested changes, revisions (`/opsx:update`). When the
specification is accepted, a maintainer adds the **`spec-approved`** label.
Agents must not implement before the label is present.

### 5. Implement

Ask the agent to continue on the same Pull Request:

```
/opsx:apply gh-42-<summary>
```

The agent works through `tasks.md`, adds or updates tests, and keeps
implementation commits separate from specification commits. It must not
change approved requirements; if one cannot be met, it stops and the
specification goes back to review.

### 6. Verify

- **Automated:** the `OpenSpec validate` workflow runs
  `openspec validate --all --strict` on every Pull Request touching
  `openspec/` or the workflow itself. It checks the structure of artifacts (for
  example, that every requirement has a scenario), not whether the code is correct.
- **Human review:** maintainers check that each spec scenario is met, that tests
  cover them, and that security and policy constraints hold. The Pull Request lists
  verification results per scenario.

GitHub may ask a maintainer to approve the workflow run for a first-time contributor.

### 7–8. Merge and archive

Merging the implementation leaves the issue open. Then run
`/opsx:archive gh-42-<summary>` (or `openspec archive`) in a follow-up Pull Request
from your fork, with `Closes #42` in its description. This merges the delta specs
into `openspec/specs/`, which is the authoritative description of the system, and
moves the change to `openspec/changes/archive/`, preserving its history. Merging
that Pull Request closes the issue.

If an issue is delivered through several changes, only the archive Pull Request
that completes the last of them uses `Closes #42`. The earlier ones use `Refs #42`.

## Conventions

- **Change ID:** `gh-<issue>-<kebab-summary>`.
- **Proposal:** `Issue: #<number>` as its first line.
- **Pull Request:** names the change ID and references the issue (template provided).
- **Closing an issue:** specification and implementation Pull Requests use
  `Refs #<issue>`; the archive Pull Request uses `Closes #<issue>`.
- **Licence header:** every source file starts with the Apache-2.0 header of the
  IndustryFusion Foundation in that file type's comment style; copy it from an
  existing file of the same type.

## Pull Requests come from forks

Everyone, including maintainers, opens Pull Requests from a branch on their own
fork, not from a branch in this repository:

```bash
gh repo fork IndustryFusion/IndustryFusion-Dataspace --clone
cd IndustryFusion-Dataspace
git switch -c gh-42-<summary>
git push -u origin gh-42-<summary>
gh pr create -R IndustryFusion/IndustryFusion-Dataspace --head <your-account>:gh-42-<summary>
```

Issues do not need a fork; open them directly in this repository.

## Working on a service

Each service has its own directory, `pyproject.toml`, tests and `Dockerfile`. For a Python service (`gateway`, `registry`, `adapter`, `dsp-gateway`, `management/api`):

```bash
cd <service>
python3.12 -m venv .venv && . .venv/bin/activate
pip install ".[dev]"
ruff check .     # lint
pytest           # test. Set TEST_POSTGRES_HOST, and _PORT, _USER and _PASSWORD if needed, to include tests needing PostgreSQL
docker build .   # image, except management/api, as below
```

The connector is built with `docker build connector`, which runs Gradle on Java 21 inside the build. The management image includes the UI, so it is built with `docker build -f management/api/Dockerfile management`. See [management/ui/README.md](management/ui/README.md) for the UI and its browser tests.

## Local environment

`scripts/local-env.sh` brings up a local Kubernetes cluster with PostgreSQL, S3-compatible storage and Keycloak, and sets up the realm as [keycloak.md](keycloak.md) describes. It needs a container runtime, `kind`, `kubectl`, `openssl`, `curl` and `python3`.

```bash
scripts/local-env.sh up       # create everything
scripts/local-env.sh status   # show pods
scripts/local-env.sh check    # mint a token and check its issuer
scripts/local-env.sh images   # build the images and load them into the cluster
scripts/local-env.sh services # build the services and deploy them to the cluster
scripts/local-env.sh down     # remove the cluster and generated files
```

It uses only its own kubeconfig, `.local/kubeconfig`, so your other clusters aren't touched. Generated credentials are in `.local/`, which git ignores.

With the services deployed, `scripts/message-exchange-check.py` runs two agents exchanging messages through the gateway, `scripts/connector-transfer-check.py` tests two connectors on their own, `scripts/management-check.py` onboards and removes participants through the management API, with real failures at each step, and `scripts/ifric-check.py` checks company details with real Keycloak tokens and a stand-in for the IFRIC registry.

`scripts/security-check.py` tries what participants must not be able to do to each other, from real pods: reading a payload, injecting a message, reaching components, using another's credentials, and a connector with the wrong identity.

`scripts/external-demo.py up` deploys two self-hosted participants, each in its own namespace with its own PostgreSQL, S3 storage, adapter and connector, and a NetworkPolicy limiting it to the public routes. `down` removes them. See "External participants" in [management-api.md](management-api.md).

To try the Helm install from [deploy/README.md](deploy/README.md) instead of `services`, run `scripts/local-env.sh images`, install an Ingress controller, and use `-e local` with the file that `scripts/local-env.sh helm-secrets` writes as `DATASPACE_SECRETS_FILE`. `scripts/ingress-check.py` then checks the install through the Ingress, including an upload at the limit.

### Contract tests

`scripts/contract_test.py` checks a deployment against [gateway-api.md](gateway-api.md) and [flow.md](flow.md): each route, field, status value and error shape, each flow, and the worked scenario for an agent application. It creates its own participants through the management API, and removes them.

```bash
scripts/local-env.sh up && scripts/local-env.sh services
python3 scripts/contract_test.py --local
```

`--local` also works on a Helm install on that cluster. For another deployment, give its addresses:

```bash
python3 scripts/contract_test.py --gateway-url <url> --keycloak-url <url> \
  --management-url <url> --admin-secret <dataspace-admin-cli secret>
```

Or use existing participants, with `--owner <id>:<secret>` and `--builder <id>:<secret>`.

External participants' flows run with `--local` once `scripts/external-demo.py up` has run. Against another deployment, give `--external-owner <adapter url>,<id>,<secret>` and `--external-builder` the same way. Without any, they are listed as not run.

`--self-test` needs no deployment and runs in CI. It shows that each shape refuses a wrong answer. `--tamper 'GET /conversations/*:outcome'` removes a field from a route's real answers, and the run must then fail. A change can also set a value, as in `:outcome="nonsense"`, or be `messages:flip` or `messages:swap`, and a rule that matches no route fails the run. `--only` limits a run to named sections, and `--max-json-bytes` and `--max-upload-bytes` give a deployment's own limits. A maintainer can run the suite in CI with the `Contract tests` workflow, from the Actions tab.

### Client and mock agent

`scripts/dataspace_client.py` is a client for the agent API, for use from Python or the command line. `scripts/mock_agent.py` answers messages as an agent would, through the gateway. Both take their settings from the options or the environment:

```bash
export DATASPACE_GATEWAY_URL=<url> DATASPACE_KEYCLOAK_URL=<url> \
  DATASPACE_CLIENT_ID=<participant id> DATASPACE_CLIENT_SECRET=<secret>
python3 scripts/dataspace_client.py compatible
python3 scripts/dataspace_client.py send <receiver> --performative request --payload '{"summary": "..."}'
python3 scripts/dataspace_client.py inbox --status received
python3 scripts/mock_agent.py
```

`scripts/setup-local-hosts.sh add` adds host entries for reaching the environment by name, and `remove` takes them out.

## Working locally (optional)

You only need OpenSpec locally if you are driving an agent:

```bash
curl -fsSL https://openspec.dev/cli/install.sh | sh   # or: npm install -g @fission-ai/openspec
openspec list            # in-flight changes
openspec list --specs    # approved capabilities
openspec validate --all --strict
```

## Supported agents

All agents read [AGENTS.md](AGENTS.md). Claude Code is the starting point and
has native OpenSpec skills and `/opsx:*` commands in `.claude/`. To add native
support for another agent, run for example:

```bash
openspec init --tools cursor,github-copilot,codex
```

and commit the generated files. `openspec init --help` lists all tool IDs.

## Current limitations

- Proposal creation, implementation and archiving are started manually; nothing runs automatically from issues.
- Who may add `spec-approved` is not enforced yet. `CODEOWNERS` and branch protection are recommended, and need repository admin settings.
- The fork rule is checked in review, not technically blocked. Someone with write access can still open a Pull Request from a branch in this repository.
- CI validates specifications, and lints, tests and builds the services. It does not run the end-to-end scripts, so functional correctness and security still require human review.
- The project documents differ on several points that maintainers have not decided. They are listed in `openspec/config.yaml`.
