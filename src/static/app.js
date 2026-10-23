/* My Bulter Enterprise UI. Inputs: local API data. Outputs: safe DOM updates.
   Assumptions: one local user; no HTML rendering of model output. Author: Carter Tan. */
'use strict';
const $ = (selector) => document.querySelector(selector);
const token = $('meta[name="bulter-token"]').content;
let state = {bulters: [], memories: [], missions: []};
let providers = [];
let team = [];
let filter = 'all';
let selectedMission = null;
let polling = false;
let timer;
const labels = {ollama: 'Ollama', lmstudio: 'LM Studio', openai: 'OpenAI', anthropic: 'Claude', openrouter: 'OpenRouter'};
const cloud = (p) => !['ollama', 'lmstudio'].includes(p);

function el(tag, className = '', text = '') {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}
function button(text, className, action) {
  const node = el('button', className, text);
  node.type = 'button';
  node.addEventListener('click', action);
  return node;
}
function notify(message) {
  $('#notice').textContent = message;
  $('#notice').hidden = false;
  clearTimeout(timer);
  timer = setTimeout(() => { $('#notice').hidden = true; }, 6500);
}
async function api(path, method = 'GET', body) {
  const response = await fetch(`/api/${path}`, {method, headers: {'Content-Type': 'application/json', 'X-Bulter-Token': token}, body: body ? JSON.stringify(body) : undefined});
  const result = await response.json();
  if (!response.ok) {
    const detail = typeof result.detail === 'string' ? result.detail : 'Please check the form fields and try again.';
    throw new Error(detail);
  }
  return result;
}
function showView(name) {
  document.querySelectorAll('.view').forEach(v => {v.hidden = v.id !== `view-${name}`;});
  document.querySelectorAll('.nav').forEach(n => {
    n.classList.toggle('active', n.dataset.view === name);
    if (n.dataset.view === name) n.setAttribute('aria-current', 'page');
    else n.removeAttribute('aria-current');
  });
  $('#breadcrumb').textContent = {bulters: 'Bulters', missions: 'Missions', memory: 'Memory', models: 'Models & connections'}[name];
  if (name === 'missions') renderTeam();
}
function providerModels() {
  const id = $('#bulter-provider').value;
  const provider = providers.find(p => p.id === id);
  $('#model-options').replaceChildren(...(provider?.models || []).map(m => {const o = document.createElement('option'); o.value = m; return o;}));
  $('#provider-help').textContent = cloud(id) ? 'Use the exact provider model ID. Saving this Bulter makes no paid request. An API key is required on the server to run it.' : `${provider?.status || 'Not checked'}. Choose an installed chat model, or enter its exact ID. No model downloads happen automatically.`;
}
function openBulter(bot = null, starter = null) {
  $('#bulter-form').reset();
  $('#bulter-form .form-error').textContent = '';
  $('#bulter-id').value = bot?.id || '';
  $('#bulter-name').value = bot?.name || starter?.name || '';
  $('#bulter-role').value = bot?.role || starter?.role || '';
  $('#bulter-instructions').value = bot?.instructions || starter?.instructions || 'Be helpful, precise and explicit about uncertainty. Ask when essential context is missing.';
  $('#bulter-provider').value = bot?.provider || 'ollama';
  $('#bulter-model').value = bot?.model || '';
  $('#bulter-shared').checked = bot?.shared_memory || false;
  $('#bulter-dialog-title').textContent = bot ? 'Edit your Bulter' : 'Create a Bulter';
  providerModels();
  $('#bulter-dialog').showModal();
}
function renderBulters() {
  $('#stat-bulters').textContent = state.bulters.length;
  $('#nav-count').textContent = state.bulters.length;
  $('#bulter-total').textContent = state.bulters.length;
  $('#stat-memory').textContent = state.memories.filter(m => m.active && !m.owner_id).length;
  $('#stat-missions').textContent = state.missions.filter(m => m.status === 'completed').length;
  const grid = $('#bulter-grid');
  grid.replaceChildren();
  const bots = state.bulters.filter(b => filter === 'all' || cloud(b.provider) === (filter === 'cloud'));
  for (const bot of bots) {
    const card = el('article', 'card');
    const top = el('div', 'card-top');
    const provider = providers.find(p => p.id === bot.provider);
    top.append(el('div', 'avatar', bot.name[0].toUpperCase()), el('span', `badge ${cloud(bot.provider) ? 'cloud' : provider?.status === 'Connected' ? '' : 'offline'}`, cloud(bot.provider) ? '↗ Cloud API' : '● Local model'));
    card.append(top, el('h3', '', bot.name), el('p', 'role', bot.role), el('span', 'model-chip', `${labels[bot.provider]} / ${bot.model}`), el('div', 'memory-line', bot.shared_memory ? '▤ Shared memory enabled' : '▤ Private memory only'));
    const actions = el('div', 'card-actions');
    actions.append(button('Start a mission ↗', 'secondary', () => {team = [bot.id]; showView('missions'); $('#mission-prompt').focus();}), button('Edit', 'secondary', () => openBulter(bot)));
    card.append(actions); grid.append(card);
  }
  if (!state.bulters.length) {
    for (const preset of [
      {name: 'Atlas', role: 'Architecture & security', instructions: 'Review architecture with clear assumptions, trust boundaries and practical tradeoffs. Distinguish verified facts from recommendations.'},
      {name: 'Scribe', role: 'Proposals & clear communication', instructions: 'Draft concise professional content. Preserve evidence and qualify unsupported claims. Never invent customer requirements.'},
    ]) {
      const card = el('article', 'card starter');
      card.append(el('span', 'plus', '＋'), el('h3', '', `Meet ${preset.name}`), el('p', '', `${preset.role}. A starting point you can make your own.`), button(`Set up ${preset.name}`, 'secondary', () => openBulter(null, preset)));
      grid.append(card);
    }
  }
  const add = el('article', 'card starter');
  add.append(el('span', 'plus', '＋'), el('h3', '', 'Make room for a specialist'), el('p', '', 'Give a Bulter a purpose, a model, and a way of working.'), button('Create a Bulter', 'secondary', () => openBulter()));
  grid.append(add);
}
function renderTeam() {
  team = team.filter(id => state.bulters.some(b => b.id === id));
  $('#team-picker').replaceChildren(...state.bulters.map(bot => {
    const index = team.indexOf(bot.id);
    const option = button(`${index >= 0 ? `${index + 1}. ` : '＋ '}${bot.name}`, `team-option ${index >= 0 ? 'selected' : ''}`, () => {
      if (team.includes(bot.id)) team = team.filter(id => id !== bot.id);
      else if (team.length < 4) team.push(bot.id);
      else return notify('Choose at most four Bulters for one mission.');
      $('#cloud-consent').checked = false;
      renderTeam();
    });
    option.append(el('small', '', `${labels[bot.provider]} · ${bot.model}`)); return option;
  }));
  if (!state.bulters.length) $('#team-picker').append(el('p', 'empty', 'Create your first Bulter before starting a mission.'));
  $('#team-route').textContent = team.length ? team.map(id => state.bulters.find(b => b.id === id).name).join(' → ') : 'No Bulters selected';
  const useCloud = team.some(id => cloud(state.bulters.find(b => b.id === id).provider));
  $('#cloud-consent-row').hidden = !useCloud;
  $('#cloud-consent').required = useCloud;
  $('#egress-note').textContent = useCloud ? 'Local-only notes will be excluded from ALL steps of this mission, including local steps. Provider keys and model access must be configured.' : 'This mission uses local providers only. No automatic cloud fallback.';
  $('#run-mission').disabled = !team.length || state.missions.some(m => ['queued', 'running'].includes(m.status));
}
function renderMissions() {
  $('#mission-list').replaceChildren();
  for (const mission of state.missions) {
    const item = button('', 'mission-item', () => {selectedMission = mission.id; renderDetail();});
    item.append(el('span', `badge ${mission.status === 'failed' ? 'cloud' : ''}`, mission.status), el('p', '', mission.prompt), el('small', '', `${mission.team.map(b => b.name).join(' → ')} · ${new Date(mission.created).toLocaleString()}`));
    $('#mission-list').append(item);
  }
  if (!state.missions.length) $('#mission-list').append(el('p', 'empty', 'Your first mission starts here. Completed work and interrupted responses will stay in this activity log.'));
  renderDetail();
}
function renderDetail() {
  const target = $('#mission-detail');
  const mission = state.missions.find(m => m.id === selectedMission);
  target.replaceChildren();
  if (!mission) return;
  const panel = el('div', 'panel');
  const head = el('div', 'mission-detail-head');
  head.append(el('h2', '', 'Mission workspace'), el('span', 'badge', mission.status));
  if (['running', 'queued'].includes(mission.status)) head.append(button('Stop mission', 'secondary', async () => {
    try { await api(`missions/${mission.id}/stop`, 'POST'); await refresh(); }
    catch (error) { notify(error.message); }
  }));
  head.append(button('Export JSON', 'secondary', () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(mission, null, 2)], {type: 'application/json'}));
    const a = document.createElement('a'); a.href = url; a.download = `bulter-mission-${mission.id}.json`; a.click(); URL.revokeObjectURL(url);
  }));
  panel.append(head, el('p', 'brief', mission.prompt));
  if (mission.error) panel.append(el('p', 'error', mission.error));
  for (const [index, step] of mission.steps.entries()) {
    const block = el('div', 'step');
    const title = el('div', 'step-head');
    title.append(el('strong', '', `${index + 1}. ${step.name}`), el('small', '', `${labels[step.provider]} / ${step.model}`), el('span', 'badge', step.status));
    block.append(title, el('p', 'help', `${step.memory_ids.length} notes selected from ${step.eligible_memory_count ?? step.memory_ids.length} permitted notes · output handed to subsequent Bulters`), el('pre', 'step-output', step.output || 'Waiting for the model’s first words…'));
    panel.append(block);
  }
  target.append(panel);
}
function openMemory(memory = null) {
  $('#memory-form').reset(); $('#memory-form .form-error').textContent = '';
  $('#memory-id').value = memory?.id || '';
  $('#memory-title').value = memory?.title || '';
  $('#memory-content').value = memory?.content || '';
  $('#memory-cloud').checked = memory?.cloud_allowed || false;
  $('#memory-active').checked = memory?.active ?? true;
  $('#memory-owner').replaceChildren(...[{id: '', name: 'Shared workspace · opted-in Bulters'}, ...state.bulters].map(b => {const o = el('option', '', b.name); o.value = b.id; return o;}));
  $('#memory-owner').value = memory?.owner_id || '';
  $('#memory-dialog-title').textContent = memory ? 'Edit a memory' : 'Add a memory';
  $('#memory-dialog').showModal();
}
function renderMemory() {
  $('#vault-path').textContent = state.obsidian?.exists ? state.obsidian.path : 'Vault not created yet. See the Obsidian setup guide.';
  $('#memory-list').replaceChildren(...state.memories.map(memory => {
    const card = el('article', 'card');
    card.append(el('span', `badge ${memory.cloud_allowed ? 'cloud' : ''}`, memory.active ? (memory.cloud_allowed ? 'Cloud-approved' : 'Local only') : 'Inactive'), el('p', 'help', memory.owner_id ? `Private · ${state.bulters.find(b => b.id === memory.owner_id)?.name || 'Unknown'}` : 'Shared workspace'), el('h3', '', memory.title), el('p', 'memory-content', memory.content));
    if (memory.source_type === 'obsidian') card.append(el('p', 'help', `Edit in Obsidian: ${memory.source_path} · Source: ${memory.source}`));
    else card.append(button('Edit memory', 'secondary', () => openMemory(memory)));
    return card;
  }));
  if (!state.memories.length) $('#memory-list').append(el('p', 'empty', 'No memories yet. Add preferences, useful context, or working principles for your team.'));
}
function renderProviders() {
  const localModels = providers.filter(p => !p.cloud).flatMap(p => p.models);
  $('#stat-models').textContent = localModels.length;
  $('#model-note').textContent = providers.some(p => !p.cloud && p.status.startsWith('Connected')) ? 'Available on your Mac' : 'Start Ollama or LM Studio';
  $('#provider-grid').replaceChildren(...providers.map(p => {
    const card = el('article', 'card provider-card');
    const top = el('div', 'card-top'); top.append(el('h3', '', p.label), el('span', `badge ${p.cloud ? 'cloud' : ''}`, p.cloud ? 'Cloud' : 'Local'));
    card.append(top, el('p', '', p.status));
    if (p.models.length) {
      const list = el('ul'); for (const model of p.models) list.append(el('li', '', model)); card.append(list);
    } else card.append(el('p', '', p.cloud ? 'Assign an exact model ID to a Bulter. API availability and billing depend on your provider account.' : 'Start the local server, then check connections again.'));
    $('#provider-grid').append(card); return card;
  }));
}
async function refresh() {
  state = await api('state');
  renderBulters(); renderMemory(); renderMissions(); renderTeam();
}
async function connections() {
  $('#refresh-models').disabled = true;
  try { providers = await api('providers'); renderProviders(); renderBulters(); }
  catch (error) { notify(error.message); }
  finally { $('#refresh-models').disabled = false; }
}
document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => showView(b.dataset.view)));
document.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => document.getElementById(b.dataset.close).close()));
document.querySelectorAll('[data-filter]').forEach(b => b.addEventListener('click', () => { filter = b.dataset.filter; document.querySelectorAll('[data-filter]').forEach(n => {n.classList.toggle('selected', n === b); n.setAttribute('aria-pressed', String(n === b));}); renderBulters(); }));
$('#new-bulter').addEventListener('click', () => openBulter());
$('#new-memory').addEventListener('click', () => openMemory());
$('#sync-obsidian').addEventListener('click', async () => {
  $('#sync-obsidian').disabled = true;
  try { const result = await api('obsidian/sync', 'POST'); await refresh(); notify(`${result.approved} approved notes synced; ${result.deactivated} deactivated.`); }
  catch (error) { notify(error.message); }
  finally { $('#sync-obsidian').disabled = false; }
});
$('#team-mission').addEventListener('click', () => showView('missions'));
$('#refresh-models').addEventListener('click', connections);
$('#bulter-provider').addEventListener('change', () => { $('#bulter-model').value = ''; providerModels(); });
$('#bulter-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = {name: $('#bulter-name').value, role: $('#bulter-role').value, instructions: $('#bulter-instructions').value, provider: $('#bulter-provider').value, model: $('#bulter-model').value, shared_memory: $('#bulter-shared').checked};
  const id = $('#bulter-id').value;
  try { await api(id ? `bulters/${id}` : 'bulters', id ? 'PUT' : 'POST', data); $('#bulter-dialog').close(); await refresh(); notify('Bulter saved. Its model runs only when you start a mission.'); }
  catch (error) { $('#bulter-form .form-error').textContent = error.message; }
});
$('#memory-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = {title: $('#memory-title').value, content: $('#memory-content').value, owner_id: $('#memory-owner').value || null, cloud_allowed: $('#memory-cloud').checked, active: $('#memory-active').checked};
  const id = $('#memory-id').value;
  try { await api(id ? `memories/${id}` : 'memories', id ? 'PUT' : 'POST', data); $('#memory-dialog').close(); await refresh(); notify('Memory saved with your chosen boundaries.'); }
  catch (error) { $('#memory-form .form-error').textContent = error.message; }
});
$('#mission-form').addEventListener('submit', async (event) => {
  event.preventDefault(); $('#run-mission').disabled = true;
  try {
    const mission = await api('missions', 'POST', {prompt: $('#mission-prompt').value, bulter_ids: team, cloud_consent: $('#cloud-consent').checked});
    selectedMission = mission.id; $('#cloud-consent').checked = false; await refresh(); $('#mission-detail').scrollIntoView({behavior: 'smooth'});
  } catch (error) { notify(error.message); renderTeam(); }
});
async function init() {
  try { await refresh(); await connections(); }
  catch (error) { notify(error.message); }
}
setInterval(async () => {
  if (polling || !state.missions.some(m => ['queued', 'running'].includes(m.status))) return;
  polling = true;
  try { await refresh(); } catch (error) { notify(error.message); } finally { polling = false; }
}, 1200);
init();
