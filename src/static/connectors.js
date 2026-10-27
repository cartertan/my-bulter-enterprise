/* Explicit connector controls. Inputs: user forms and local API. Outputs: safe DOM.
   No automatic external writes, HTML rendering or model-directed actions. Author: Carter Tan. */
'use strict';
let connectorData = {connections: {}, evidence: [], actions: []};
let connectorSelection = [];
const contextNotice = el('p', 'help', 'No connector reference selected.');
contextNotice.id = 'connector-context-notice';
$('#mission-form').insertBefore(contextNotice, $('#run-mission'));
const clearContext = button('Clear connector references', 'secondary', clearConnectorSelection);
$('#mission-form').insertBefore(clearContext, $('#run-mission'));
const telegramNotice = el('label', 'check');
const telegramNotify = document.createElement('input');
telegramNotify.type = 'checkbox'; telegramNotify.id = 'telegram-notify';
telegramNotice.append(telegramNotify, el('span', '', 'Send a Telegram notice with this mission’s ID and status only. Requires a paired bot; no results are sent.'));
$('#mission-form').insertBefore(telegramNotice, $('#run-mission'));

function connectorMissionOptions() {
  return {evidence_ids: [...connectorSelection], telegram_notify: telegramNotify.checked};
}
function clearConnectorSelection() {
  connectorSelection = [];
  contextNotice.textContent = 'No connector reference selected.';
  telegramNotify.checked = false;
}
async function connectorOperation(path, body = {}) {
  $('#connector-status').textContent = 'Working…';
  try {
    const result = await api(`connectors/${path}`, 'POST', body);
    $('#connector-status').textContent = 'Finished. Review the result below.';
    await refreshConnectors();
    return result;
  } catch (error) {
    $('#connector-status').textContent = error.message;
    throw error;
  }
}
function bindConnectorButton(id, action) {
  $(id).addEventListener('click', async () => {
    $(id).disabled = true;
    try { await action(); } catch (error) { notify(error.message); }
    finally { $(id).disabled = false; }
  });
}
async function refreshConnectors() {
  connectorData = await api('connectors');
  const google = connectorData.connections.google;
  const telegram = connectorData.connections.telegram;
  if ($('#connector-status').textContent === 'Account connections have not been checked.') $('#connector-status').textContent = 'Connection metadata loaded. See each connector’s status below.';
  const browserCapture = connectorData.evidence.find(item => item.source === 'browser');
  $('#browser-connector-status').textContent = browserCapture ? `Last successful browser capture: ${new Date(browserCapture.created).toLocaleString()}. This records a past capture, not a live health check.` : 'No browser capture recorded yet.';
  $('#google-status').textContent = google.configured ? 'Authorized · credentials in Keychain. Live reads verify access.' : 'Not connected';
  $('#telegram-status').textContent = telegram.configured ? 'Paired · private chat authorized · token in Keychain' : 'Not paired';
  $('#connector-evidence-list').replaceChildren();
  for (const item of connectorData.evidence) {
    const card = el('article', 'panel');
    card.append(el('h3', '', item.title), el('p', 'help', `${item.source} · ${item.created} · local-only${item.truncated ? ' · truncated' : ''}`));
    const details = document.createElement('details');
    details.append(el('summary', '', 'Review captured text'), el('pre', 'connector-text', item.content));
    card.append(details, button('Use in a local mission', 'secondary', () => {
      if (!connectorSelection.includes(item.id)) {
        if (connectorSelection.length >= 3) return notify('Choose at most three reference snapshots. Clear the selection in Missions to start again.');
        connectorSelection.push(item.id);
      }
      contextNotice.textContent = `${connectorSelection.length} connector snapshot(s) selected. Local models only; no automatic memory import.`;
      showView('missions');
    }));
    $('#connector-evidence-list').append(card);
  }
  $('#connector-action-list').replaceChildren();
  for (const action of connectorData.actions) {
    const row = el('div', 'panel');
    row.append(el('strong', '', `${action.kind} · ${action.status}`), el('p', 'help', action.created));
    if (action.error) row.append(el('p', 'error', action.error));
    row.append(button('Review stored action', 'secondary', () => renderActionPreview(action)));
    $('#connector-action-list').append(row);
  }
}
function renderActionPreview(action) {
  const panel = $('#connector-action-preview'); panel.replaceChildren();
  panel.append(el('h3', '', `${action.kind} · ${action.status}`), el('pre', 'connector-text', JSON.stringify(action.payload, null, 2)));
  if (action.current_event) panel.append(el('h3', '', 'Existing calendar event — check before changing'), el('pre', 'connector-text', JSON.stringify(action.current_event, null, 2)));
  panel.append(el('p', 'help', 'This exact content will leave your Mac. Check recipients, event IDs and timezone offsets. Preview expires after 15 minutes. Failed/unknown actions are not retried automatically.'));
  if (action.status === 'pending') {
    const confirm = button('Confirm this exact action', 'primary', async () => {
      confirm.disabled = true;
      try { renderActionPreview(await connectorOperation(`actions/${action.id}/confirm`, {confirm: true})); }
      catch (error) { notify(error.message); }
    });
    panel.append(confirm, button('Cancel preview', 'secondary', async () => {
      try { renderActionPreview(await connectorOperation(`actions/${action.id}/cancel`)); }
      catch (error) { notify(error.message); }
    }));
  }
  if (action.error) panel.append(el('p', 'error', action.error));
  panel.scrollIntoView({behavior: 'smooth', block: 'center'});
}
$('#google-connect-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget; const submit = form.querySelector('button'); submit.disabled = true;
  const payload = {client_id: $('#google-client-id').value.trim(), client_secret: $('#google-client-secret').value.trim()};
  $('#google-client-secret').value = ''; $('#google-authorize-link').hidden = true;
  try {
    const result = await connectorOperation('google/connect', payload);
    $('#google-authorize-link').href = result.authorization_url; $('#google-authorize-link').hidden = false;
    $('#connector-status').textContent = 'Click Continue to Google, review the permissions, then return and refresh status.';
  } catch (error) { notify(error.message); }
  finally { payload.client_secret = ''; submit.disabled = false; }
});
$('#telegram-connect-form').addEventListener('submit', async event => {
  event.preventDefault(); const submit = event.currentTarget.querySelector('button'); submit.disabled = true;
  const payload = {token: $('#telegram-token').value.trim()}; $('#telegram-token').value = '';
  try {
    const result = await connectorOperation('telegram/connect', payload);
    $('#telegram-pair-command').textContent = `In your private chat with @${result.username}, send: ${result.command} (expires in 10 minutes)`;
  } catch (error) { notify(error.message); }
  finally { payload.token = ''; submit.disabled = false; }
});
bindConnectorButton('#refresh-connectors', refreshConnectors);
bindConnectorButton('#read-gmail', () => connectorOperation('google/read', {kind: 'gmail', query: $('#gmail-query').value}));
bindConnectorButton('#read-calendar', () => connectorOperation('google/read', {kind: 'calendar'}));
bindConnectorButton('#read-telegram', () => connectorOperation('telegram/inbox'));
bindConnectorButton('#capture-browser', () => connectorOperation('browser/capture'));
bindConnectorButton('#pair-telegram', async () => {
  const result = await connectorOperation('telegram/pair');
  $('#telegram-pair-command').textContent = result.paired ? 'Your private chat is paired.' : result.message;
});
for (const name of ['google', 'telegram']) bindConnectorButton(`#disconnect-${name}`, async () => {
  if (!window.confirm('Disconnect this local connector? Existing evidence and action history remain. Revoke remote access separately in Google or BotFather.')) return;
  await connectorOperation(`${name}/disconnect`);
});
bindConnectorButton('#save-manual-context', async () => {
  await connectorOperation('manual', {text: $('#manual-connector-text').value});
  $('#manual-connector-text').value = '';
});
$('#connector-action-kind').addEventListener('change', () => {
  const type = $('#connector-action-kind').value.split('.')[0];
  document.querySelectorAll('[data-action-fields]').forEach(node => { node.hidden = node.dataset.actionFields !== type; });
});
$('#connector-action-form').addEventListener('submit', async event => {
  event.preventDefault(); const submit = event.currentTarget.querySelector('button[type="submit"]'); submit.disabled = true;
  const kind = $('#connector-action-kind').value;
  let payload = {kind};
  if (kind === 'gmail.send') Object.assign(payload, {to: $('#connector-to').value, subject: $('#connector-subject').value, body: $('#connector-body').value});
  else if (kind === 'telegram.send') payload.text = $('#connector-telegram-text').value;
  else Object.assign(payload, {event_id: $('#connector-event-id').value, summary: $('#connector-summary').value, description: $('#connector-description').value, start: $('#connector-start').value, end: $('#connector-end').value});
  try { renderActionPreview(await connectorOperation('actions/prepare', payload)); }
  catch (error) { notify(error.message); }
  finally { submit.disabled = false; }
});
