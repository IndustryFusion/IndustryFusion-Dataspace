# Spec Delta

## Purpose

Defines how changes to the IndustryFusion Dataspace move from a GitHub Issue through
an OpenSpec change proposal, maintainer approval, implementation and verification to
an archived specification, while staying traceable throughout.

## ADDED Requirements

### Requirement: Change originates from a GitHub Issue
Every OpenSpec change SHALL reference exactly one originating GitHub Issue with an `Issue: #<number>` line in its `proposal.md`.

#### Scenario: Proposal references its issue
- **WHEN** a change proposal is created for GitHub Issue 42
- **THEN** its `proposal.md` contains the line `Issue: #42`

### Requirement: Stable change identifiers
Every change directory under `openspec/changes/` SHALL be named `gh-<issue>-<kebab-summary>`, where `<issue>` is the originating issue number and `<kebab-summary>` is a short kebab-case description.

#### Scenario: Change ID follows the convention
- **WHEN** a change is proposed for issue 42 about adding inbox expiry
- **THEN** the change directory is `openspec/changes/gh-42-add-inbox-expiry/`

### Requirement: Proposal completeness
A change proposal SHALL contain a proposal with motivation and out-of-scope items, delta specifications whose requirements each have at least one WHEN/THEN scenario, a design covering architectural implications, and a task list with a verification step per task.

#### Scenario: Complete proposal passes strict validation
- **WHEN** `openspec validate <change-id> --strict` runs on a complete proposal
- **THEN** validation succeeds

#### Scenario: Requirement without scenario is rejected
- **WHEN** a delta specification contains a requirement with no scenario
- **THEN** `openspec validate <change-id> --strict` fails

### Requirement: Specification approval gates implementation
Implementation of a change SHALL start only after a maintainer has added the `spec-approved` label to the Pull Request that contains the change proposal.

#### Scenario: Agent waits for approval
- **WHEN** an agent is asked to implement a change whose Pull Request lacks the `spec-approved` label
- **THEN** the agent does not modify source code and reports that specification approval is pending

#### Scenario: Agent implements after approval
- **WHEN** the Pull Request carries the `spec-approved` label
- **THEN** the agent implements the change's tasks in the same Pull Request

### Requirement: Approved requirements are authoritative
Implementation SHALL NOT change approved requirements. When implementation reveals that a requirement must change, the agent SHALL stop and propose the specification change for maintainer review.

#### Scenario: Conflict found during implementation
- **WHEN** an agent finds during implementation that an approved requirement cannot be met as written
- **THEN** the agent stops, describes the conflict, and edits the specification only after maintainer agreement

### Requirement: Project context separates target from current state
The project context SHALL state that the architecture document describes a target system, and SHALL name the known differences between the project documents.

#### Scenario: Agent checks before assuming code exists
- **WHEN** an agent proposes a change affecting a component described in the architecture document
- **THEN** the project context tells it to check whether that component is in the repository before assuming it exists

#### Scenario: Change touches an undecided difference
- **WHEN** a proposed change depends on a point where the project documents differ and no maintainer has decided it
- **THEN** the change's design states the difference and presents the alternatives instead of choosing one silently

### Requirement: Pull Requests reference their change
Every Pull Request that contains an OpenSpec change SHALL name the change ID and link the originating issue.

#### Scenario: Pull Request description links change and issue
- **WHEN** a Pull Request for change `gh-42-add-inbox-expiry` is opened
- **THEN** its description names `gh-42-add-inbox-expiry` and references issue 42

### Requirement: Pull Requests come from forks
Every contributor, including maintainers, SHALL open Pull Requests from a branch on their own fork and not from a branch in this repository. Opening an issue SHALL NOT require a fork.

#### Scenario: Contributor opens a Pull Request
- **WHEN** a contributor opens a Pull Request against this repository
- **THEN** its source branch is on the contributor's own fork

#### Scenario: Contributor opens an issue
- **WHEN** a contributor wants to propose a feature or report a problem
- **THEN** they open the issue directly in this repository without creating a fork

### Requirement: Merging the archive closes the issue
The originating issue SHALL stay open until the change is archived. Specification and implementation Pull Requests SHALL reference the issue without a closing keyword, and the archive Pull Request SHALL close it with a closing keyword. When an issue is delivered through several changes, only the archive Pull Request that completes the last of them SHALL close it.

#### Scenario: Implementation is merged
- **WHEN** the Pull Request containing a change's specification and implementation is merged
- **THEN** the originating issue stays open

#### Scenario: Archive is merged
- **WHEN** the archive Pull Request for a change is merged
- **THEN** the originating issue is closed automatically

#### Scenario: Issue delivered through several changes
- **WHEN** an archive Pull Request is merged and another change for the same issue is not yet archived
- **THEN** the originating issue stays open

### Requirement: Automated artifact validation
Every Pull Request that modifies files under `openspec/` or the validation workflow SHALL run `openspec validate --all --strict` in CI, and a validation failure SHALL fail the check.

#### Scenario: Malformed change fails CI
- **WHEN** a Pull Request adds a delta specification with a scenario using three hashes instead of four
- **THEN** the OpenSpec validation check fails

#### Scenario: Unrelated change does not run the check
- **WHEN** a Pull Request modifies no files under `openspec/` and not the validation workflow
- **THEN** the OpenSpec validation check is not triggered

### Requirement: Archived history remains accessible
After a change is merged, it SHALL be archived with OpenSpec, which merges its delta specifications into `openspec/specs/` and keeps the proposal, design and tasks under `openspec/changes/archive/`.

#### Scenario: Archive preserves history
- **WHEN** a merged change is archived
- **THEN** its requirements appear in `openspec/specs/` and its original artifacts are found under `openspec/changes/archive/`

### Requirement: Discoverable agent instructions
The repository SHALL provide agent-independent instructions in `AGENTS.md` describing the lifecycle, and each supported agent SHALL be able to reach them from its native instruction mechanism.

#### Scenario: Claude Code discovers the workflow
- **WHEN** Claude Code starts in the repository
- **THEN** `CLAUDE.md` directs it to `AGENTS.md` and the OpenSpec `/opsx:*` commands are available

### Requirement: Contributor guide states automation boundaries
The repository SHALL provide a contributor guide that explains each lifecycle step and states for each step whether it is automated or requires manual action.

#### Scenario: Contributor without local tooling
- **WHEN** a contributor without OpenSpec installed wants to propose a feature
- **THEN** the guide explains how to do so by opening a GitHub Issue only

### Requirement: Source files carry the licence header
Every CI workflow and other source file added to the repository SHALL start with the Apache-2.0 header of the IndustryFusion Foundation, in the comment style of its file type.

#### Scenario: Workflow file has the header
- **WHEN** the OpenSpec validation workflow is added
- **THEN** the file starts with the IndustryFusion Foundation Apache-2.0 header
