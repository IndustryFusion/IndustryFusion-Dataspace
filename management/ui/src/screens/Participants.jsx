/*
 * Copyright (c) 2026 IndustryFusion Foundation
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import React, { useCallback, useEffect, useState } from 'react';

import { useAdmin } from '../admin.jsx';
import { participantPath, request } from '../api.js';

const shortType = (type) => (type || '').split('#').pop();
const EMPTY_FORM = {
  participant_id: '',
  participant_type: 'factory_owner',
  hosted: true,
  // A hosted participant is reachable unless the administrator says otherwise, as in the API.
  externally_reachable: true,
  adapter_url: '',
  dsp_url: '',
  peer_notify_url: '',
};

function RegisterForm({ onDone, run, busy }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const set = (key) => (event) =>
    setForm({ ...form, [key]: event.target.type === 'checkbox' ? event.target.checked : event.target.value });
  const submit = async (event) => {
    event.preventDefault();
    const body = { ...form };
    for (const key of ['adapter_url', 'dsp_url', 'peer_notify_url']) {
      if (form.hosted || !form[key]) delete body[key];
    }
    // Reachability is for hosted participants. The API treats an external one as not reachable.
    if (!form.hosted) delete body.externally_reachable;
    if (await onDone(body)) setForm(EMPTY_FORM);
  };
  return (
    <form onSubmit={submit} className="panel" aria-label="Register a participant">
      <h3>Register a participant</h3>
      <label>
        Participant id
        <input value={form.participant_id} onChange={set('participant_id')} required />
      </label>
      <label>
        Type
        <select value={form.participant_type} onChange={set('participant_type')}>
          <option value="factory_owner">Factory owner</option>
          <option value="machine_builder">Machine builder</option>
        </select>
      </label>
      <label>
        <input type="checkbox" checked={form.hosted} onChange={set('hosted')} /> Hosted here
      </label>
      <label>
        <input type="checkbox" checked={form.externally_reachable} onChange={set('externally_reachable')} /> Reachable
        from outside
      </label>
      {!form.hosted && (
        <>
          <label>
            Adapter URL
            <input value={form.adapter_url} onChange={set('adapter_url')} required />
          </label>
          <label>
            DSP URL
            <input value={form.dsp_url} onChange={set('dsp_url')} required />
          </label>
          <label>
            Peer notify URL
            <input value={form.peer_notify_url} onChange={set('peer_notify_url')} />
          </label>
        </>
      )}
      <button type="submit" disabled={busy}>
        Register
      </button>
      <button type="button" disabled={busy} onClick={run}>
        Create demo participants
      </button>
      {busy && <span role="status"> Working. A registration waits for its pods, and can take minutes.</span>}
    </form>
  );
}

function CopyButton({ value, what }) {
  const [said, setSaid] = useState(null);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setSaid('Copied');
    } catch {
      setSaid('Could not copy. The browser allows it only on a secure page');
    }
  };
  return (
    <>
      <button type="button" onClick={copy} aria-label={`Copy ${what}`}>
        Copy
      </button>
      {said && <span role="status"> {said}</span>}
    </>
  );
}

function Credentials({ credentials, onClose }) {
  return (
    <div className="panel" role="region" aria-label="Credentials">
      <h3>Credentials</h3>
      {credentials.map((entry) => (
        <dl key={entry.client_id}>
          <dt>Client id</dt>
          <dd>
            {entry.client_id} <CopyButton value={entry.client_id} what="client id" />
          </dd>
          <dt>Client secret</dt>
          <dd>
            <code>{entry.client_secret}</code> <CopyButton value={entry.client_secret} what="client secret" />
          </dd>
        </dl>
      ))}
      <button type="button" onClick={onClose}>
        Close
      </button>
    </div>
  );
}

// A read without admin mode leaves out a hosted participant's addresses, which only work inside the hub.
const address = (value) => (typeof value === 'string' && value ? value : 'Not public');

// These come from another service, and anything but text would stop the page from drawing.
const asText = (value) => (typeof value === 'string' || typeof value === 'number' ? value : '');

// The warnings of answers to registering, as [participant id, warning] pairs, leaving out anything that isn't text.
const warningsOf = (records) =>
  (Array.isArray(records) ? records : [records]).flatMap((made) =>
    made && Array.isArray(made.warnings)
      ? made.warnings
          .filter((warning) => typeof warning === 'string' && warning)
          .map((warning) => [asText(made.participant_id), warning])
      : [],
  );

function Warnings({ warnings }) {
  return (
    <section className="panel" aria-label="Warnings">
      <h3>Warnings</h3>
      <ul>
        {warnings.map(([participant, warning], index) => (
          <li key={index}>
            {participant}: {asText(warning)}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function Participants() {
  const admin = useAdmin();
  const [participants, setParticipants] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [credentials, setCredentials] = useState(null);
  const [warnings, setWarnings] = useState([]);

  // In admin mode the read carries the token, so it has every address.
  const load = useCallback(async () => {
    try {
      setParticipants(
        admin.active ? await admin.call('GET', '/api/participants') : await request('GET', '/api/participants'),
      );
      return true;
    } catch (failure) {
      // What went wrong first is the one to show, if this is after an action.
      setError((shown) => shown || failure.message);
      return false;
    }
  }, [admin.active, admin.call]);

  const [refreshing, setRefreshing] = useState(false);
  const refresh = async () => {
    setRefreshing(true);
    setError(null);
    await load();
    setRefreshing(false);
  };

  // A secret on the screen goes with the mode that fetched it.
  useEffect(() => {
    if (!admin.active) {
      setCredentials(null);
      setWarnings([]);
    }
  }, [admin.active]);

  useEffect(() => {
    load();
  }, [load]);

  // Run an admin action, showing the API's error, and then read the list again.
  const act = async (action) => {
    setBusy(true);
    setError(null);
    setWarnings([]);
    try {
      await action();
      await load();
      return true;
    } catch (failure) {
      setError(failure.message);
      await load();
      return false;
    } finally {
      setBusy(false);
    }
  };

  const showCompany = (participants || []).some((entry) => entry.company_name);
  const record = (entry, changes) => ({
    participant_id: entry.participant_id,
    participant_type: entry.participant_type,
    hosted: entry.hosted,
    externally_reachable: entry.externally_reachable,
    adapter_url: entry.adapter_url,
    dsp_url: entry.dsp_url,
    peer_notify_url: entry.peer_notify_url,
    ...changes,
  });

  return (
    <section>
      <h2>Participants</h2>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {admin.active && (
        <RegisterForm
          busy={busy}
          run={() =>
            act(async () => {
              const made = await admin.call('POST', '/api/demo');
              setCredentials(made);
              setWarnings(warningsOf(made));
            })
          }
          onDone={(body) =>
            act(async () => {
              const made = await admin.call('POST', '/api/participants', body);
              setCredentials([{ client_id: made.client_id, client_secret: made.client_secret }]);
              setWarnings(warningsOf(made));
            })
          }
        />
      )}
      {warnings.length > 0 && <Warnings warnings={warnings} />}
      {credentials && <Credentials credentials={credentials} onClose={() => setCredentials(null)} />}
      <p>
        <button type="button" onClick={refresh} disabled={refreshing || busy}>
          Refresh
        </button>
      </p>
      {participants && participants.length === 0 && <p>No participants are registered.</p>}
      {participants && participants.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Participant</th>
              <th>Type</th>
              <th>Hosted</th>
              <th>Reachable from outside</th>
              <th>Adapter</th>
              <th>DSP</th>
              {showCompany && (
                <>
                  <th>Company</th>
                  <th>Category</th>
                  <th>City</th>
                  <th>Country</th>
                </>
              )}
              {admin.active && <th>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {participants.map((entry) => (
              <tr key={entry.participant_id}>
                <td>
                  {entry.participant_id}
                  {!entry.hosted && <span className="marker"> (external)</span>}
                </td>
                <td>{shortType(entry.participant_type)}</td>
                <td>{entry.hosted ? 'Yes' : 'No'}</td>
                <td>{entry.externally_reachable ? 'Yes' : 'No'}</td>
                <td>{address(entry.adapter_url)}</td>
                <td>{address(entry.dsp_url)}</td>
                {showCompany && (
                  <>
                    <td>{asText(entry.company_name)}</td>
                    <td>{asText(entry.company_category)}</td>
                    <td>{asText(entry.city)}</td>
                    <td>{asText(entry.country)}</td>
                  </>
                )}
                {admin.active && (
                  <td className="actions">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        act(async () =>
                          setCredentials([
                            await admin.call('GET', `${participantPath(entry.participant_id)}/credentials`),
                          ]),
                        )
                      }
                    >
                      Show credentials
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        act(async () =>
                          setWarnings(
                            warningsOf(
                              await admin.call(
                                'POST',
                                '/api/participants',
                                record(entry, { externally_reachable: !entry.externally_reachable }),
                              ),
                            ),
                          ),
                        )
                      }
                    >
                      {entry.externally_reachable ? 'Make unreachable' : 'Make reachable'}
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        if (window.confirm(`Delete ${entry.participant_id} and everything it holds?`)) {
                          act(() => admin.call('DELETE', participantPath(entry.participant_id)));
                        }
                      }}
                    >
                      Delete
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
