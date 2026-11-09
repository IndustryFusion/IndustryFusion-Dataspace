# Spec Delta

## Purpose

The management UI can sit behind a login at the Ingress, the API keeps the Keycloak admin token, and the IP allowlist is optional.

## RENAMED Requirements

- FROM: `### Requirement: Management Ingress needs an allowlist`
- TO: `### Requirement: Management Ingress access`

## MODIFIED Requirements

### Requirement: Management Ingress access
The management UI's route `/` SHALL have nginx basic auth when `ingress.management.basicAuth.enabled` is true, from credentials in the secrets file stored only as a bcrypt hash. `/api` and `/health` SHALL have no basic auth and keep the admin token. Both management Ingress objects SHALL carry `ingress.management.allowFrom` when it is set, and render without an allowlist when it is empty.

#### Scenario: No allowlist
- **WHEN** the Ingress is enabled and `ingress.management.allowFrom` is empty
- **THEN** the chart renders, and neither management Ingress has `nginx.ingress.kubernetes.io/whitelist-source-range`

#### Scenario: An allowlist
- **WHEN** `ingress.management.allowFrom` is set
- **THEN** both management Ingress objects carry exactly that value as their allowlist

#### Scenario: The UI login on
- **WHEN** `ingress.management.basicAuth.enabled` is true with a user and password in the secrets file
- **THEN** `/` asks for them, giving `401` without them and the UI with them, and no rendered object holds the plain password

#### Scenario: The login on without credentials
- **WHEN** `ingress.management.basicAuth.enabled` is true and `secrets.managementBasicAuth.user` or `.password` is empty
- **THEN** rendering fails, naming the setting

#### Scenario: /api without basic auth
- **WHEN** the login is on, and `/api` or `/health` is called without basic credentials
- **THEN** it is answered, and an external adapter's participant read works

#### Scenario: A change without an admin token
- **WHEN** a client the allowlist admits, or any client without an allowlist, sends a change to `/api` through the Ingress without an admin token, with or without basic credentials
- **THEN** it is refused with `401`

#### Scenario: A client outside the allowlist
- **WHEN** `ingress.management.allowFrom` is set, and a client outside it calls `/` or `/api`
- **THEN** nginx refuses it with `403`

#### Scenario: Too many tries at the login
- **WHEN** the login is on, and a client sends more requests to `/` than `ingress.management.basicAuth.limitRps` allows
- **THEN** nginx refuses the excess, and `/api` isn't limited
