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

import React, { useEffect, useState } from 'react';

import { useAdmin } from '../admin.jsx';
import { participantPath, request } from '../api.js';

const isType = (entry, type) => (entry.participant_type || '').endsWith(type);
const companyOf = (entry) => (entry.company_name ? `${entry.participant_id} (${entry.company_name})` : entry.participant_id);

export default function Policies() {
  const admin = useAdmin();
  const [participants, setParticipants] = useState([]);
  const [owner, setOwner] = useState('');
  const [builder, setBuilder] = useState('');
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    request('GET', '/api/participants')
      .then(setParticipants)
      .catch((failure) => setError(failure.message));
  }, []);

  const read = async (fo, mb) => {
    const query = new URLSearchParams({ fo, mb }).toString();
    // An external side needs a token, so send one when there is one.
    return admin.active ? admin.call('GET', `/api/policy?${query}`) : request('GET', `/api/policy?${query}`);
  };

  const show = async (event) => {
    event.preventDefault();
    setError(null);
    setView(null);
    try {
      setView(await read(owner, builder));
    } catch (failure) {
      setError(failure.message);
    }
  };

  const act = async (action) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      setView(await read(owner, builder));
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  };

  const decide = (entry, action) =>
    act(() =>
      admin.call('POST', `${participantPath(entry.provider)}/approvals`, {
        consumer_id: entry.consumer,
        capability: entry.capability,
        action,
      }),
    );

  const reset = (entry) =>
    act(() =>
      admin.call('PATCH', `${participantPath(entry.provider)}/approvals/${encodeURIComponent(entry.approval_id)}`, {
        action: 'reset',
      }),
    );

  return (
    <section>
      <h2>Policies</h2>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <form onSubmit={show} className="panel" aria-label="Choose a pair">
        <label>
          Factory owner
          <select value={owner} onChange={(event) => setOwner(event.target.value)} required>
            <option value="">Choose</option>
            {participants
              .filter((entry) => isType(entry, 'factory_owner'))
              .map((entry) => (
                <option key={entry.participant_id} value={entry.participant_id}>
                  {companyOf(entry)}
                </option>
              ))}
          </select>
        </label>
        <label>
          Machine builder
          <select value={builder} onChange={(event) => setBuilder(event.target.value)} required>
            <option value="">Choose</option>
            {participants
              .filter((entry) => isType(entry, 'machine_builder'))
              .map((entry) => (
                <option key={entry.participant_id} value={entry.participant_id}>
                  {companyOf(entry)}
                </option>
              ))}
          </select>
        </label>
        <button type="submit">Show</button>
      </form>
      {view && view.unavailable.length > 0 && (
        <p role="note">Held by its own adapter, so not shown here: {view.unavailable.join(', ')}</p>
      )}
      {view && (
        <table>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Consumer</th>
              <th>Capability</th>
              <th>Default</th>
              <th>Status</th>
              <th>Source</th>
              <th>Note</th>
              {admin.active && <th>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {view.capabilities.map((entry) => (
              <tr key={`${entry.provider}/${entry.capability}`}>
                <td>{entry.provider}</td>
                <td>{entry.consumer}</td>
                <td title={entry.description}>{entry.label || entry.capability}</td>
                <td>{entry.default_policy}</td>
                <td>{entry.status}</td>
                <td>{entry.source}</td>
                <td>{entry.decision_note}</td>
                {admin.active && (
                  <td className="actions">
                    <button type="button" disabled={busy} onClick={() => decide(entry, 'approve')}>
                      Approve
                    </button>
                    <button type="button" disabled={busy} onClick={() => decide(entry, 'deny')}>
                      Deny
                    </button>
                    <button type="button" disabled={busy || !entry.approval_id} onClick={() => reset(entry)}>
                      Reset
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
