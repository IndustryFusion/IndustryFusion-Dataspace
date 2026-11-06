# Design

## Context

`manifest.md` describes a minimal product, and `architecture.md` describes the target system. `gh-2-bootstrap-openspec` listed four differences between them as open questions. It also recommended docker-compose for the MVP as a proposal only, and this change does not follow that recommendation, for the reason below.

## Goals / Non-Goals

**Goals:**

- One clear answer to each open question.
- A contract precise enough to build services and clients from it.

**Non-Goals:**

- Settling how services are implemented beyond what the contract requires.

## Decisions

**Deployment target: Kubernetes.** Onboarding a hosted participant creates its adapter and connector through the Kubernetes API at runtime, as `architecture.md` describes under "Adding a Participant". Alternatives: docker-compose for the MVP, rejected because hosted onboarding has no compose equivalent and we would build a second provisioning path; supporting both, rejected for the same reason. Compose may still be used to build images.

**Connector: one combined control and data plane per participant.** Fewer components per participant, and it matches the Technology Stack table. Alternative: separate planes, as in `manifest.md`, which adds a deployment and a network path per participant with no need at the expected scale.

**Leading documents: each document leads on its own subject.** `architecture.md` on design, `manifest.md` on goals and definition of done, `protocol.md` on message semantics, `gateway-api.md` and `management-api.md` on their HTTP contracts. Alternatives: `architecture.md` leading on everything, which would bury the contract in a long document; `manifest.md` leading until the MVP is complete, rejected because it omits the gateway, registry and identity provider that the system needs.

**Object storage: S3-compatible, with SeaweedFS as the default.** SeaweedFS is what the IndustryFusion/DigitalTwin stack provides, and the services use a plain S3 interface, so another S3 store can be substituted. Alternative: MinIO as the documents say today, which would add a second store next to the platform's.

**Delivery to agents is by polling.** It is simple for an agent behind a firewall, and it is the only delivery the contract promises. Alternative: webhooks or a stream, which can be added later without breaking polling. `manifest.md`'s "notify local agent" is reworded to match.

**Capability access is advisory.** The dataspace records and reports access, and does not block messages; the sending application checks it. The reasoning and behaviour belong to #13, and the documents state it here so the contract is complete. Alternative: blocking on a denied capability, which #13 excludes. This qualifies "governed" in `manifest.md`, so the wording there is updated.

**Duplicate text: removed here.** The second copy in `manifest.md` is identical to the first, so nothing is lost. Alternative: a separate change, which adds overhead for a one-line outcome since this change already edits the file.

## Architectural implications

No component is added or removed. The DSP gateway is already part of the external participant flow in `architecture.md`, and this change adds it to the topology, service table, component breakdown, reachability table and technology stack. The statement that no DSP endpoint is ever publicly exposed conflicts with that flow; it is reworded so that hosted connectors are reached only through the DSP gateway, with no direct exposure.

## Risks / Trade-offs

- [The contract is written before the services exist] → Service changes that find a problem change the contract through their own proposal, rather than diverging from it.
- [Client needs may differ from the contract] → `gateway-api.md` is checked against IndustryFusion/XANA-AI-PDT#26, and gaps are listed in the Pull Request.
- [Known limits are made public] → Limits such as unauthenticated internal routes are documented alongside #20, which addresses them.

## Open Questions

None. All earlier open questions are closed by this change.
