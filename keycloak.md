# Identity Setup

This document leads on how Keycloak is set up for the dataspace. #6 scripts the realm setup, and #14 automates what is needed per participant.

The dataspace uses an existing Keycloak, such as the one in the [IndustryFusion DigitalTwin](https://github.com/IndustryFusion/DigitalTwin) stack, and does not deploy its own.

## One-time setup

Do this once per installation:

| Item | Setting |
|---|---|
| Realm | `dataspace` |
| Realm role | `dataspace-admin` |
| Client | `dataspace-admin-cli`: confidential, service account enabled |
| Its service account | Realm role `dataspace-admin`, plus `manage-clients`, `manage-realm` and `manage-users` from `realm-management` |
| Client, optional | `dataspace-ifric-reader`: confidential, service account enabled, no roles. Used to read company details from the IFRIC registry |

Keep client secrets in a Kubernetes Secret or a secret manager, not in the repository.

## Per participant

The management API creates this at registration, for hosted and external participants:

| Item | Setting |
|---|---|
| Realm role | `participant:<participant_id>` |
| Client | Client id equal to `participant_id`, client credentials only |
| Claim mapper | Hardcoded claim `participant_id` with the participant's id |
| Role assignment | The realm role on the client's service account |

## What a participant token carries

```json
{
  "iss": "<KEYCLOAK_URL>/realms/dataspace",
  "participant_id": "urn:example:machine-builder-1",
  "realm_access": { "roles": ["participant:urn:example:machine-builder-1"] }
}
```

| Check | By | Requires |
|---|---|---|
| Signature and issuer | Gateway, adapter | RS256 against the realm's signing keys, and an exact issuer match. The audience is not checked |
| `participant_id` claim | Gateway | Present, and registered |
| `participant:<id>` role | Adapter | Matches the adapter's own participant |

A user login is not a substitute. A user's token can be given a `participant_id` claim, which would pass the gateway, but it would not hold the realm role the adapter requires. Agents use the participant's client.

## A token sent to a peer can be replayed

An adapter authenticates to a peer's adapter with its own token, on notifications and capability calls, and the audience isn't checked. So a peer that keeps such a token can use it at the sender's own adapter, as the sender, until it expires. For example, a machine builder could use a factory owner's token at that factory owner's `POST /capabilities/policy`, and approve itself.

Inside the hub the operator runs every adapter, and the traffic stays in the cluster. It matters most for an `adapter_url` or `peer_notify_url` outside the hub, which #18 introduces. Changing this affects tokens across the platform, so it is recorded here as an open decision.

## The issuer must match

Services compare a token's issuer exactly with the URL they are configured with. So mint tokens through that same URL. A token minted through a different address for the same Keycloak is refused.

## Participant identifiers

A participant onboarded from the IFRIC registry has a `participant_id` equal to its `company_ifric_id`, with no mapping table. The realm can then be shared with the [IFRIC registry](https://github.com/IndustryFusion/ifric-registry-service-oss), which matches a `participant_id` token against its companies.

Any other participant id must never equal a real `company_ifric_id`, or the registry would treat it as that company.

The dataspace does not check this at registration, so the administrator is responsible for it.

## Removal

`DELETE /api/participants/{id}` removes the client and the role. See [management-api.md](management-api.md).
