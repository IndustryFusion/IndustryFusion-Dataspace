# Tasks

## 1. Services

- [x] 1.1 Add a skeleton for `gateway`, `registry`, `adapter`, `dsp-gateway` and `management` with a health route, tests, `pyproject.toml` and `Dockerfile`; verify each passes Ruff and pytest and its image builds
- [x] 1.2 Add a `connector` skeleton that builds on Java 21; verify its image builds
- [x] 1.3 Add a note in `management/ui/`; verify it is present
- [x] 1.4 Record conventions in `CONTRIBUTING.md` and `openspec/config.yaml`; verify by reading them

## 2. CI

- [ ] 2.1 Add `.github/workflows/services.yml`, with the licence header, running lint and tests for each Python service and building each image; verify in CI on this Pull Request, or by running the same steps locally if GitHub does not trigger it from a fork

## 3. Local environment

- [x] 3.1 Add `scripts/local-env.sh` and `deploy/local/infra.yaml` for the cluster, namespaces, PostgreSQL, S3 storage and Keycloak; verify `up` from nothing reaches ready, and `down` removes it
- [x] 3.2 Add `scripts/setup-keycloak.py` for the realm, role, client and service account roles; verify running it twice succeeds and the result matches `keycloak.md`
- [x] 3.3 Mint a token from the local realm through a port-forward; verify its issuer equals the URL services are configured with
- [x] 3.4 Add `scripts/setup-local-hosts.sh`; verify it adds, repeats safely and removes entries, against a temporary file

## 4. Integration check

- [x] 4.1 Search the repository for credentials; verify none are committed, and that `.local/` is ignored
- [ ] 4.2 Check each scenario in the delta specs and report the result per scenario in the Pull Request; verify the report covers every scenario

## Workflow follow-up

- After merge, archive with the other milestone changes in a follow-up Pull Request with `Closes #6`.
