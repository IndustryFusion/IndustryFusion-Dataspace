# Tasks

## 1. OpenSpec configuration

- [ ] 1.1 Run `openspec init --tools claude` and commit the generated skills and commands; verify `.claude/commands/opsx/propose.md` and `.claude/skills/openspec-propose/SKILL.md` are tracked
- [ ] 1.2 Fill `openspec/config.yaml` with project context and artifact rules (issue reference, out-of-scope, testable scenarios, architectural impact, verification per task); verify `openspec instructions proposal --change gh-2-bootstrap-openspec` shows them
- [ ] 1.3 State in the project context that `architecture.md` describes a target system whose code is not in the repository yet, and name the differences between the documents listed in `design.md`; verify by reading the context against `design.md`

## 2. Agent instructions

- [ ] 2.1 Write `AGENTS.md` covering lifecycle, inspecting existing specs, conflict reporting, the `spec-approved` gate, not altering approved requirements, tests, and verification against acceptance criteria; verify each item is present
- [ ] 2.2 Add `CLAUDE.md` pointing to `AGENTS.md`; verify the reference resolves

## 3. GitHub integration

- [ ] 3.1 Add `.github/workflows/openspec-validate.yml` with the licence header, running `openspec validate --all --strict` with a pinned, checksum-verified binary on Pull Requests and pushes touching `openspec/`; verify the workflow runs green on this Pull Request and the checksum matches the release's `SHA256SUMS`
- [ ] 3.2 Add `.github/ISSUE_TEMPLATE/feature.yml`; verify it parses as YAML
- [ ] 3.3 Add `.github/pull_request_template.md` with issue link, change ID and automated-versus-human checklist; verify the fields are present

## 4. Contributor documentation

- [ ] 4.1 Write `CONTRIBUTING.md` documenting each lifecycle step and whether it is automated or manual, including how to propose a feature with a GitHub Issue only; verify it covers proposing, approval, implementation, verification and archive
- [ ] 4.2 Link `CONTRIBUTING.md` from `README.md`; verify the link resolves and the diff leaves the badges and licence information unchanged

## 5. Integration check

- [ ] 5.1 Run `openspec validate --all --strict` and `openspec status --change gh-2-bootstrap-openspec`; verify validation passes and all artifacts are complete
- [ ] 5.2 Confirm a requirement without a scenario, and a scenario with three hashes instead of four, each fail strict validation (temporary, not committed); record the result in the Pull Request
- [ ] 5.3 Confirm the Pull Request adds no application code and leaves `manifest.md`, `architecture.md` and `LICENSE` unchanged, unless maintainers decide otherwise on Open Question 4; verify with `git diff --stat` against `main`
- [ ] 5.4 Check each scenario in the delta spec and report the result per scenario in the Pull Request; verify the report covers every scenario

## Workflow follow-up

- After merge, run `/opsx:archive gh-2-bootstrap-openspec` in a follow-up Pull Request; verify `openspec/specs/spec-driven-workflow/spec.md` exists.
