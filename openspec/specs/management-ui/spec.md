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

The Health screen SHALL show a summary line, each component's status, detail and response time, and the time of the check, refreshed every 15 seconds and on a Refresh button, without signing in.

#### Scenario: All healthy
- **WHEN** the screen is opened
- **THEN** each component shows its status and response time, with the time of the check and a summary line of how many components are ok

#### Scenario: A component goes down
- **WHEN** a component goes down while the screen is open
- **THEN** within 15 seconds the screen shows it, with the detail message, and the summary line counts it

#### Scenario: Refreshing by hand
- **WHEN** the Refresh button is pressed
- **THEN** the health is read again at once, and the time of the check changes

#### Scenario: A component that isn't configured
- **WHEN** a component has no response time
- **THEN** its response time is shown as empty, not as zero

#### Scenario: Leaving the screen
- **WHEN** another screen is opened
- **THEN** the refreshing stops

### Requirement: Participants screen

The Participants screen SHALL list participants without signing in, with each one's adapter and DSP addresses and an "(external)" marker for an external participant, and SHALL offer a Refresh button. In admin mode it SHALL let an administrator register hosted or external participants, create demo participants, show credentials with copy buttons, set reachability and delete.

#### Scenario: Reading
- **WHEN** the screen is opened without signing in
- **THEN** participants are listed

#### Scenario: Addresses
- **WHEN** participants are listed
- **THEN** each shows its adapter and DSP address as the API returned them, and an address the API withheld reads as not public

#### Scenario: Addresses in admin mode
- **WHEN** participants are listed in admin mode
- **THEN** a hosted participant shows its adapter and DSP address

#### Scenario: External marker
- **WHEN** a participant is external
- **THEN** it is marked "(external)", and a hosted one is not

#### Scenario: Refreshing
- **WHEN** a participant is added by another client, and the Refresh button is pressed
- **THEN** it is listed

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

#### Scenario: Copying credentials
- **WHEN** credentials are shown, and the copy button of the client id or the secret is pressed
- **THEN** that value is on the clipboard, and the screen says it was copied

#### Scenario: No secret unless asked
- **WHEN** the screen is open, in or out of admin mode, and no credentials were asked for or returned by a registration
- **THEN** no client secret is in the page, and no copy button is offered

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

The Policies screen SHALL show a factory owner and machine builder pair to an administrator, with each capability's data classification and the conversation its decision was made in, including an external provider's capabilities, and SHALL offer approve, deny and reset for a hosted provider.

#### Scenario: Viewing a pair
- **WHEN** an administrator chooses a hosted pair
- **THEN** each capability shows, in both directions, its provider, consumer, data classification, status, source and conversation

#### Scenario: Without admin mode
- **WHEN** the screen is opened without admin mode
- **THEN** it says that reading who has access needs admin mode, and no policy is read

#### Scenario: Choosing a pair
- **WHEN** the lists are opened
- **THEN** each offers only participants of its type

#### Scenario: Approve, deny and reset
- **WHEN** an administrator approves, denies and resets a capability of a hosted provider
- **THEN** its status changes each time, ending at the default

#### Scenario: Nothing to reset
- **WHEN** a capability has no decision
- **THEN** reset isn't available

#### Scenario: An external side
- **WHEN** a side of the pair is external and its policies can be read
- **THEN** its capabilities are shown with the other side's, without approve, deny or reset

#### Scenario: An external side that can't be read
- **WHEN** a side of the pair is external and its policies can't be read
- **THEN** the hosted side is shown, and a note names the external side with the reason

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

### Requirement: Registration form starts reachable

The Participants screen's registration form SHALL start with reachability ticked, and SHALL send the value shown.

#### Scenario: Registering with the starting value
- **WHEN** an administrator registers a hosted participant without touching the reachability box
- **THEN** the request has `externally_reachable` true

#### Scenario: Unticking it
- **WHEN** an administrator unticks the box and registers
- **THEN** the request has `externally_reachable` false

### Requirement: Registration warnings are shown

The Participants screen SHALL show each warning in the answer to registering a participant, to changing its reachability and to creating the demo participants, with the participant it concerns. A warning SHALL be shown as text only, and a value that isn't text SHALL NOT be shown.

#### Scenario: A registration that can't be reachable
- **WHEN** an administrator registers a hosted participant and the answer has a warning that it isn't reachable from outside
- **THEN** the screen shows that warning with the participant's id

#### Scenario: Making a participant reachable
- **WHEN** an administrator uses "Make reachable" and the answer has a warning
- **THEN** the screen shows that warning with the participant's id

#### Scenario: Creating the demo participants
- **WHEN** an administrator creates the demo participants and the answer's records have warnings
- **THEN** the screen shows each record's warnings with its participant's id

#### Scenario: No warnings
- **WHEN** the answer has no warnings
- **THEN** no warning is shown

#### Scenario: A warning that isn't text
- **WHEN** a warning in the answer is not text
- **THEN** the screen still renders, and that warning isn't shown
