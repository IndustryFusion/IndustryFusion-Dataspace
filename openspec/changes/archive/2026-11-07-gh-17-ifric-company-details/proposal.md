# Proposal

Issue: #17

## Why

An administrator sees participants only as identifiers. A participant onboarded from the IFRIC registry already has a company name, category and place there, under the same identifier.

## What Changes

- The management API reads `GET /company/get-all-companies` from the IFRIC registry, with a token from an optional `dataspace-ifric-reader` client, and caches the result for `IFRIC_LOOKUP_CACHE_SECONDS`, by default 300.
- Participant reads gain `company_name`, `company_category`, `city` and `country`, when known. If IFRIC is unreachable or not configured, they are left out, and nothing else changes.
- The Helm chart gains these settings, with the reader's credentials in the Secret.
- `keycloak.md` and `architecture.md` document that such a participant's `participant_id` is its `company_ifric_id`, with no mapping table, how the realm is shared, and that other participant ids must never equal a real `company_ifric_id`.

## Capabilities

### New Capabilities

- `ifric-company-details`: Company details on participant reads.

### Modified Capabilities

None.

## Out of Scope

- Automatic onboarding from IFRIC company registration, and deriving roles from company categories.
- Any change to the IFRIC registry.
- Checking at registration that a `participant_id` doesn't equal a real `company_ifric_id`. `keycloak.md` leaves this to the administrator.

## Impact

- `manifest.md`: none affected.
- `architecture.md`, "Adding a Participant": gains the rule for identifiers.
- `management-api.md`: delivered as written.
- `keycloak.md`: the shared realm's setup is added.
