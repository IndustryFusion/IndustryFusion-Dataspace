# Design

## Context

The repository holds only documents. `gateway-api.md` and `architecture.md` set the stack: Python 3.12 and FastAPI for services, EDC 0.9.0 on Java 21 for the connector, on Kubernetes.

## Goals / Non-Goals

**Goals:**

- A contributor goes from a clean machine to a working environment with one command.
- The local environment cannot touch any other cluster.

**Non-Goals:**

- A production deployment, which is #15.

## Decisions

**One directory and image per service, with no shared package.** Each service has its own `pyproject.toml`, tests and `Dockerfile`, so services build and release independently. Alternative: a shared library for common code such as token checks, rejected for now because it couples the images while the services are few and small.

**pytest and Ruff.** Common choices with little configuration. Alternative: flake8 with Black, which is two tools for one job.

**kind for the local cluster, with its own kubeconfig.** kind needs only a container runtime. The script writes a kubeconfig under `.local/` and uses only that, so it cannot act on another cluster. Alternative: k3d, which would also work; kind is the more common choice. Alternative: docker-compose, rejected because #5 settled on Kubernetes and hosted provisioning has no compose equivalent.

**Small local stand-ins for infrastructure, with the platform's service names.** The script deploys one PostgreSQL, one SeaweedFS and one Keycloak in namespace `iff`, using the names `acid-cluster`, `seaweedfs` and `keycloak-service` from `architecture.md`. Alternative: installing the whole IndustryFusion/DigitalTwin stack, which brings Kafka, Flink and an operator the dataspace doesn't use, and takes far longer to start. Services see the same addresses either way, so configuration carries over.

**A fixed Keycloak issuer.** Keycloak runs with a fixed hostname, so its issuer is `http://keycloak-service.iff:8080/auth` wherever a token is minted from. Services in the cluster use that URL, so tokens minted through a port-forward also match. Alternative: an Ingress with host entries, which needs root on the machine for every run.

**Generated credentials, kept outside git.** The script generates passwords into `.local/`, which is ignored, and into Kubernetes Secrets. Alternative: fixed development passwords in the repository, which would make "no credentials committed" unverifiable.

**Realm setup through the Admin REST API.** It is safe to repeat and adds no dependency. Alternative: a realm import file, which is awkward for service account role mappings and only applies to an empty realm.

## Architectural implications

None. This change adds the layout `architecture.md` assumes. No conflict with `manifest.md` or `architecture.md`.

## Risks / Trade-offs

- [Stand-ins differ from the platform] → Same names and ports, and #15 installs against the platform.
- [First-time image pulls are slow] → Only on first use.
- [The connector image takes minutes to build in CI] → Accepted; it runs in its own job.

## Open Questions

None.
