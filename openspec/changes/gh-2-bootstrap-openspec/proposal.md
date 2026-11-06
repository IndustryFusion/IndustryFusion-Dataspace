# Proposal

Issue: #2

## Why

The dataspace is about to move from documents to code. The repository has no
specification workflow, no agent instructions and no CI, so nothing yet connects
a requirement to the decisions and code that follow from it. Setting up the
workflow now means the first line of dataspace code can already go through it.

## What Changes

- Initialize OpenSpec (default `spec-driven` schema) with `openspec/specs/` as
  the authoritative specification location and `openspec/changes/` for change
  proposals. `openspec/specs/` starts empty.
- Add project context and artifact rules in `openspec/config.yaml`, derived from
  `manifest.md` and `architecture.md`.
- Add agent-independent instructions (`AGENTS.md`) and a pointer for Claude Code
  (`CLAUDE.md`), and commit the native OpenSpec skills and commands generated
  for Claude Code.
- Define the lifecycle Issue → Proposal → Specification review → Implementation
  → Verification → Merge → Archive, with a `spec-approved` Pull Request label
  gating implementation.
- Define traceability: change IDs `gh-<issue>-<kebab-summary>` and an
  `Issue: #N` line in every proposal. Specification and implementation Pull
  Requests use `Refs #N`, and the merged archive Pull Request closes the issue
  with `Closes #N`.
- Require every contributor to open Pull Requests from their own fork. Issues are
  opened directly in this repository and need no fork.
- Add a GitHub Actions workflow validating OpenSpec artifacts, a feature request
  form, a Pull Request template and a contributor guide.
- Record the differences between `manifest.md` and `architecture.md` as decisions
  for maintainers.

## Capabilities

### New Capabilities

- `spec-driven-workflow`: How changes to this repository are proposed, specified,
  approved, implemented, verified and archived, and how they stay traceable to
  GitHub Issues and Pull Requests.

### Modified Capabilities

None.

## Impact

- New files: `openspec/`, `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `.claude/`,
  `.github/`. `README.md` gains a link to the contributor guide; its badges and
  licence information stay unchanged.
- No application code or runtime dependency is added. The CI job downloads a
  pinned, checksum-verified OpenSpec binary.
- No CI exists today, so no existing workflow is affected.
- `architecture.md`: no section changes. The Overview, Deployment Topology
  (Kubernetes), Component Breakdown and Technology Stack sections are the source
  of the project context.
- `manifest.md`: no section changes under this proposal unless maintainers decide
  otherwise (see Open Questions in `design.md`).

## Out of Scope

- Any dataspace implementation: gateway, registry, adapter, EDC configuration,
  deployment files or management UI.
- Changes to other repositories.
- Autonomous issue-to-merge execution, multi-agent orchestration, custom agent
  frameworks and automatic approval.
- Enforcing who may apply the `spec-approved` label (`CODEOWNERS`, branch
  protection). These need repository admin settings and are documented as
  recommendations only.
- Technically blocking Pull Requests from branches in this repository. The fork
  rule is documented and checked in review.
- Test and lint conventions for code that does not exist yet.
