# Tasks

## 1. Decisions and existing documents

- [x] 1.1 Remove the second copy of the text from `manifest.md`; verify the file has one title and that the removed text was identical to the first copy
- [x] 1.2 Update `manifest.md` for the deployment target, connector layout and storage, and replace its message model and adapter API with references to `protocol.md` and `gateway-api.md`; verify by reading sections 3, 7, 8, 9 and 11 against the decisions in `design.md`
- [x] 1.3 Update `architecture.md`: storage, DSP gateway in every listed section, the public-exposure statement, capability routes, Policies tab, participant fields, delivery by polling; verify by searching for each term
- [x] 1.4 Remove the resolved differences from `openspec/config.yaml`, and name the leading documents; verify `openspec instructions proposal --change gh-5-documents-and-contract` shows the new context

## 2. New documents

- [x] 2.1 Write `protocol.md`: performatives, outcomes, conversation states, validity rules, state rules, advisory capability access and known limits; verify against the scenarios in the delta spec
- [x] 2.2 Write `gateway-api.md`: authentication, every agent route, fields, status values and error shapes for #9, #10, #11, #12 and #13; verify each route in those issues appears
- [x] 2.3 Write `management-api.md` for every route in #14 and #17; verify each route in those issues appears
- [x] 2.4 Write `keycloak.md`: realm, roles, clients, claims, issuer and IFRIC identifier convention; verify against #6, #14 and #17
- [x] 2.5 Write `flow.md`, walking through a request, reply, file transfer and close; verify every route it uses is in `gateway-api.md`
- [x] 2.6 Write `asyncapi.yaml` naming `protocol.md` as the source of truth; verify it parses and its fields match `gateway-api.md`

## 3. Integration check

- [x] 3.1 Check `gateway-api.md` against IndustryFusion/XANA-AI-PDT#26, and list any gaps in the Pull Request; verify the list is present, even if empty
- [ ] 3.2 Run `openspec validate --all --strict`; verify it passes locally and in CI
- [x] 3.3 Confirm no service code was added; verify with `git diff --stat` against `main`
- [ ] 3.4 Check each scenario in the delta spec and report the result per scenario in the Pull Request; verify the report covers every scenario

## Workflow follow-up

- After merge, run `/opsx:archive gh-5-documents-and-contract` in a follow-up Pull Request from a fork, with `Closes #5` in its description.
