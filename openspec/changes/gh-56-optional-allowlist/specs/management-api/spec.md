# Spec Delta

## Purpose

Credentials of another scheme, such as those a browser sends after a basic-auth login, count as no token.

## ADDED Requirements

### Requirement: Basic credentials are treated as no token
The service SHALL treat an `Authorization` header whose scheme isn't `Bearer` as no token: a read SHALL give the public view, and a change SHALL give `401`, as without a header. A `Bearer` token that is malformed, invalid or without `dataspace-admin` SHALL be refused as today.

#### Scenario: A read with basic credentials
- **WHEN** `GET /api/participants` or `GET /api/participants/{id}` is called with `Authorization: Basic …`
- **THEN** the answer is the public view, as without a token

#### Scenario: A change with basic credentials
- **WHEN** an admin route, such as `POST /api/participants`, is called with `Authorization: Basic …`
- **THEN** the answer is `401`, and nothing is changed

#### Scenario: A bearer token that isn't an admin's
- **WHEN** a read is called with a `Bearer` token that is invalid or lacks `dataspace-admin`
- **THEN** it is refused with `401` or `403`, as today
