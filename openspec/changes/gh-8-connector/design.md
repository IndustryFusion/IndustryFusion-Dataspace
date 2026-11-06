# Design

## Context

#5 settled on one combined control and data plane per participant. `architecture.md` lists the ports: 8080 default, 8081 management, 8082 DSP, 8083 control, 8084 public.

## Goals / Non-Goals

**Goals:**

- One image, configured per participant from a mounted file and environment variables.

**Non-Goals:**

- Identity beyond the mock, in #20.

## Decisions

**A single shadow JAR built with Gradle inside the image build.** Contributors need only a container runtime. Alternative: building the JAR on the host, which adds a Java 21 and Gradle requirement.

**Modules picked individually.** The image includes only what `#8` names, plus what those modules require at startup. Alternative: EDC's larger bill-of-materials bundles, which bring in identity and other features we don't use.

**The schema is created by EDC's `sql-bootstrapper`, with `edc.sql.schema.autocreate=true`.** It needs no tool beyond the connector. The project never touches that schema directly, as `architecture.md` says. Alternative: separate migrations for EDC's tables, which would have to track every EDC release.

**One small extension generates the data plane's key pair at start.** A new RSA pair goes into the in-memory vault under the aliases named in configuration. Keys aren't persisted, so a restart generates a new pair, and it only signs tokens for the data plane's own use. Alternative: mounting a fixed key pair, which adds a secret to manage with no benefit at this stage.

**The connector's own database is separate.** The connection comes from `EDC_DATASOURCE_DEFAULT_*`, for one database per connector.

**Local two-connector test on Kubernetes, with a small HTTP server standing in for the adapter.** `scripts/connector-transfer-check.py` drives the management API through port-forwards, and checks that the bytes arrive. It needs nothing from #9. Alternative: waiting for the adapter, which would leave this image unproven on its own.

## Architectural implications

None. No conflict with `architecture.md`.

## Risks / Trade-offs

- [Mock identity: connectors don't verify each other] → Known limit in `protocol.md`, addressed in #20.
- [Restart loses in-flight transfers that depend on the vault's key] → Acceptable for this stage, as the state survives and a transfer can be started again.

## Open Questions

None.
