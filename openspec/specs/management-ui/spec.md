# management-ui Specification

## Purpose
A browser interface for the management API: health, participants and capability policies, with changes only in admin mode.

## Requirements

### Requirement: Serving the UI

The management API image SHALL serve the built UI on the service's port.

#### Scenario: The image holds the UI
- **WHEN** the image runs and `/` is requested
- **THEN** the answer is the UI's page, and its files load

#### Scenario: Other paths
- **WHEN** a path that isn't a file is requested
- **THEN** the answer is the page, unless the path is under `/api/`, which gives a JSON `404`

#### Scenario: Paths outside the UI
- **WHEN** a path resolves outside the UI's folder
- **THEN** no file from outside is returned

### Requirement: Health screen

The Health screen SHALL show each component's status, refreshed every 15 seconds, without signing in.

#### Scenario: All healthy
- **WHEN** the screen is opened
- **THEN** each component shows its status

#### Scenario: A component goes down
- **WHEN** a component goes down while the screen is open
- **THEN** within 15 seconds the screen shows it, with the detail message

#### Scenario: Leaving the screen
- **WHEN** another screen is opened
- **THEN** the refreshing stops

### Requirement: Participants screen

The Participants screen SHALL list participants without signing in, and in admin mode SHALL let an administrator register hosted or external participants, create demo participants, show credentials, set reachability and delete.

#### Scenario: Reading
- **WHEN** the screen is opened without signing in
- **THEN** participants are listed

#### Scenario: Registering a hosted participant
- **WHEN** an administrator registers one
- **THEN** it is listed, and its credentials are shown

#### Scenario: Registering an external participant
- **WHEN** an administrator clears "Hosted here" and gives its addresses
- **THEN** it is listed as not hosted, and its credentials are shown

#### Scenario: Creating demo participants
- **WHEN** an administrator creates them
- **THEN** they are listed, with their credentials shown

#### Scenario: Showing credentials
- **WHEN** an administrator asks for a participant's credentials
- **THEN** its client id and secret are shown

#### Scenario: Setting reachability
- **WHEN** an administrator changes it
- **THEN** the list shows the new value

#### Scenario: Deleting
- **WHEN** an administrator confirms a deletion
- **THEN** the participant is gone from the list

#### Scenario: Cancelling a deletion
- **WHEN** an administrator cancels the confirmation
- **THEN** the participant remains, and no call is made

#### Scenario: Company details
- **WHEN** participants have company details
- **THEN** they are shown, and when none do, the screen has no such columns

### Requirement: Policies screen

The Policies screen SHALL show a factory owner and machine builder pair, and in admin mode SHALL offer approve, deny and reset.

#### Scenario: Viewing a pair
- **WHEN** a hosted pair is chosen without signing in
- **THEN** each capability shows, in both directions, its provider, consumer, status and source

#### Scenario: Choosing a pair
- **WHEN** the lists are opened
- **THEN** each offers only participants of its type

#### Scenario: Approve, deny and reset
- **WHEN** an administrator approves, denies and resets a capability
- **THEN** its status changes each time, ending at the default

#### Scenario: Nothing to reset
- **WHEN** a capability has no decision
- **THEN** reset isn't available

#### Scenario: An external side
- **WHEN** a side of the pair is external
- **THEN** without admin mode the API's error is shown, and in admin mode the hosted side is shown with a note about the other

### Requirement: Admin mode

Admin mode SHALL use the `dataspace-admin-cli` client id and secret, fetch and refresh tokens through `/api/admin/token`, and not persist the secret in the browser.

#### Scenario: Without admin mode
- **WHEN** the screens are opened without admin mode
- **THEN** no admin action is offered

#### Scenario: A wrong secret
- **WHEN** a wrong secret is entered
- **THEN** the API's error is shown, and admin mode doesn't start

#### Scenario: The secret isn't kept
- **WHEN** admin mode has started
- **THEN** nothing is in browser storage or cookies, the secret isn't in the page, and a reload leaves admin mode

#### Scenario: Refreshing
- **WHEN** a token is about to run out
- **THEN** a new one is fetched through `/api/admin/token`, and admin mode continues

#### Scenario: A token refused
- **WHEN** a call is refused with `401`
- **THEN** a new token is fetched and the call is tried once more

#### Scenario: Leaving
- **WHEN** an administrator leaves admin mode
- **THEN** the actions are gone

### Requirement: Errors are shown

Errors from the API SHALL be shown to the user.

#### Scenario: An API error
- **WHEN** an action or a read gets an error with a message
- **THEN** the message is shown

#### Scenario: A validation error
- **WHEN** the API refuses a form's values
- **THEN** the field and its problem are shown

#### Scenario: An error from something in between
- **WHEN** an answer has no JSON body
- **THEN** its status is shown

#### Scenario: The API can't be reached
- **WHEN** a call can't reach the API
- **THEN** a message says so
