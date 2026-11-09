# Spec Delta

## Purpose

The management Ingress's IP allowlist is optional. The Keycloak admin token protects management.

## RENAMED Requirements

- FROM: `### Requirement: Management Ingress needs an allowlist`
- TO: `### Requirement: Management Ingress allowlist`

## MODIFIED Requirements

### Requirement: Management Ingress allowlist
The management Ingress SHALL carry `ingress.management.allowFrom` as its source allowlist when it is set, and SHALL render without an allowlist when it is empty. Management SHALL keep refusing every change without an admin token.

#### Scenario: No allowlist
- **WHEN** the Ingress is enabled and `ingress.management.allowFrom` is empty
- **THEN** the chart renders, and the management Ingress has no `nginx.ingress.kubernetes.io/whitelist-source-range` annotation

#### Scenario: An allowlist
- **WHEN** `ingress.management.allowFrom` is set
- **THEN** the management Ingress carries exactly that value as its allowlist

#### Scenario: A change without a token
- **WHEN** a change is sent to management through its Ingress without an admin token, and no allowlist is set
- **THEN** it is refused with `401`
