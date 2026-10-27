/* My Bulter Enterprise UI. Inputs: local API data. Outputs: safe DOM updates.
   Assumptions: one local user; no HTML rendering of model output. Author: Carter Tan. */
'use strict';
const $ = (selector) => document.querySelector(selector);
const token = $('meta[name="bulter-token"]').content;
let state = {bulters: [], memories: [], missions: []};
let providers = [];
let imageEngine = null;
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
  $('#breadcrumb').textContent = {bulters: 'Bulters', missions: 'Missions', memory: 'Memory', models: 'Models & connections', connectors: 'Connectors'}[name];
  if (name === 'missions') renderTeam();
  if (name === 'connectors') refreshConnectors().catch(error => notify(error.message));
}
function selectedModel() {
  return $('#bulter-model').value === '__custom__' ? $('#bulter-custom-model').value.trim() : $('#bulter-model').value;
}
function modelEntryMode() {
  const custom = $('#bulter-model').value === '__custom__';
  $('#custom-model-row').hidden = !custom;
  $('#bulter-custom-model').required = custom;
  $('#bulter-custom-model').disabled = !custom;
}
function providerModels(model = selectedModel()) {
  const keepCustomEntry = arguments.length === 0 && $('#bulter-model').value === '__custom__';
  const id = $('#bulter-provider').value;
  const provider = providers.find(p => p.id === id);
  const models = [...new Set(provider?.models || [])];
  const choices = [{id: '', name: 'Choose a model'}, ...models.map(m => ({id: m, name: m}))];
  // Keep saved IDs available even when discovery is offline or the provider has no catalog.
  if (model && !models.includes(model)) choices.push({id: model, name: `${model} (saved or entered ID)`});
  choices.push({id: '__custom__', name: 'Enter a custom model ID…'});
  $('#bulter-model').replaceChildren(...choices.map(m => {const o = el('option', '', m.name); o.value = m.id; return o;}));
  $('#bulter-model').value = keepCustomEntry ? '__custom__' : model || (cloud(id) ? '__custom__' : '');
  modelEntryMode();
  $('#provider-help').textContent = cloud(id) ? 'Select a saved model or enter the exact provider model ID. Saving makes no paid request.' : `${provider?.status || 'Checking connections'}. All discovered chat models are listed. Saving changes future missions; no model downloads happen automatically.`;
}
function openBulter(bot = null, starter = null) {
  $('#bulter-form').reset();
  $('#bulter-form .form-error').textContent = '';
  $('#bulter-id').value = bot?.id || '';
  $('#bulter-name').value = bot?.name || starter?.name || '';
  $('#bulter-role').value = bot?.role || starter?.role || '';
  $('#bulter-instructions').value = bot?.instructions || starter?.instructions || 'Be helpful, precise and explicit about uncertainty. Ask when essential context is missing.';
  $('#bulter-provider').value = bot?.provider || 'ollama';
  $('#bulter-custom-model').value = '';
  $('#bulter-output').value = bot?.output_tokens || 4096;
  $('#bulter-context').value = bot?.context_tokens || 16384;
  $('#bulter-thinking').value = bot?.thinking || 'auto';
  $('#bulter-shared').checked = bot?.shared_memory || false;
  $('#bulter-dialog-title').textContent = bot ? 'Edit your Bulter' : 'Create a Bulter';
  providerModels(bot?.model || starter?.model || '');
  $('#bulter-dialog').showModal();
  connections();
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
    actions.append(button('Start a mission ↗', 'secondary', () => {team = [bot.id]; showView('missions'); $('#mission-prompt').focus();}), button('Edit', 'secondary', () => openBulter(bot)), button('Remove', 'secondary', () => openRemoveBulter(bot)));
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
  const removed = state.removed_bulters || [];
  if (removed.length) {
    const panel = el('details', 'panel'); panel.append(el('summary', '', `Removed Bulters (${removed.length})`));
    for (const bot of removed) {
      const row = el('div', 'card-actions'); row.append(el('span', '', bot.name), button('Restore', 'secondary', async () => {
        try { await api(`bulters/${bot.id}/restore`, 'POST'); await refresh(); notify(`${bot.name} restored.`); }
        catch (error) { notify(error.message); }
      })); panel.append(row);
    }
    grid.append(panel);
  }
}
function openRemoveBulter(bot) {
  $('#remove-bulter-id').value = bot.id;
  $('#remove-bulter-title').textContent = `Remove ${bot.name}?`;
  $('#remove-bulter-message').textContent = `Remove ${bot.name} from your active service team?`;
  $('#remove-bulter-form .form-error').textContent = '';
  $('#remove-bulter-dialog').showModal();
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
  if (mission.status === 'completed') for (const [format, label] of [['docx', 'Download Word'], ['pptx', 'Download PowerPoint']]) {
    head.append(button(label, 'secondary', async () => {
      try {
        const response = await fetch(`/api/missions/${mission.id}/export/${format}`, {headers: {'X-Bulter-Token': token}});
        if (!response.ok) throw new Error((await response.json()).detail);
        const url = URL.createObjectURL(await response.blob());
        const a = document.createElement('a'); a.href = url; a.download = `bulter-response.${format}`; a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (error) { notify(error.message); }
    }));
  }
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
  // Retain a removed owner when editing its note; never silently convert it to shared.
  const removedOwner = (state.removed_bulters || []).filter(b => b.id === memory?.owner_id).map(b => ({...b, name: `${b.name} (removed)`}));
  $('#memory-owner').replaceChildren(...[{id: '', name: 'Shared workspace · opted-in Bulters'}, ...state.bulters, ...removedOwner].map(b => {const o = el('option', '', b.name); o.value = b.id; return o;}));
  $('#memory-owner').value = memory?.owner_id || '';
  $('#memory-dialog-title').textContent = memory ? 'Edit a memory' : 'Add a memory';
  $('#memory-dialog').showModal();
}
function renderMemory() {
  $('#vault-path').textContent = state.obsidian?.exists ? state.obsidian.path : 'Vault not created yet. See the Obsidian setup guide.';
  $('#memory-list').replaceChildren(...state.memories.map(memory => {
    const card = el('article', 'card');
    card.append(el('span', `badge ${memory.cloud_allowed ? 'cloud' : ''}`, memory.active ? (memory.cloud_allowed ? 'Cloud-approved' : 'Local only') : 'Inactive'), el('p', 'help', memory.owner_id ? `Private · ${[...state.bulters, ...(state.removed_bulters || [])].find(b => b.id === memory.owner_id)?.name || 'Unknown'}` : 'Shared workspace'), el('h3', '', memory.title), el('p', 'memory-content', memory.content));
    if (memory.source_type === 'obsidian') card.append(el('p', 'help', `Edit in Obsidian: ${memory.source_path} · Source: ${memory.source}`));
    else card.append(button('Edit memory', 'secondary', () => openMemory(memory)));
    return card;
  }));
  if (!state.memories.length) $('#memory-list').append(el('p', 'empty', 'No memories yet. Add preferences, useful context, or working principles for your team.'));
}
function renderRecommendations() {
  const local = providers.find(p => p.id === 'ollama');
  const installed = new Set(local?.installed_models || local?.models || []);
  const rows = [
    ['Architecture, PKI and editable diagrams', 'qwen3.8:27b', 'Diagram Bulter for Mermaid text; diagram command for safe SVG'],
    ['Proposals and general technical drafting', 'qwen3.8:27b', 'Assign to a Bulter; provide source notes and verify claims'],
    ['Quick summaries and everyday drafting', 'gemma4:e4b', 'Lightweight first draft; use a reviewer for important work'],
    ['Python, shell and code review', 'devstral-small-2:latest', 'Draft code as text; review and test before execution'],
    ['Document review and second opinion', 'granite4.1:30b', 'Use as a separate review step with the original evidence'],
    ['Alternative reasoning and analysis', 'qwen3.6:35b-a3b', 'Keep as an existing alternative; compare on your own tasks'],
    ['Illustrations and visual concepts', 'FLUX.2 Klein 4B · MFLUX', 'Local illustrations: run the flux command'],
    ['Photorealism and bilingual lettering', 'Z-Image Turbo · MFLUX', 'Local photos: run the photo command; check lettering'],
    ['Future semantic memory retrieval', 'qwen3-embedding:4b', 'Embedding only; current memory search does not use it']
  ];
  $('#model-recommendations').replaceChildren(...rows.map(([work, model, usage]) => {
    const row = el('tr');
    const availability = local?.status.startsWith('Connected') ? (installed.has(model) ? 'Installed' : 'Not installed') : 'Connection unavailable';
    const imageTask = model.startsWith('FLUX.') ? 'flux' : model.startsWith('Z-Image') ? 'photo' : null;
    const status = imageTask ? (imageEngine?.models?.[imageTask]?.status || 'Image engine status unavailable') : availability;
    for (const value of [work, model, usage, status]) row.append(el('td', '', value));
    return row;
  }));
}
$('#diagram-bulter').addEventListener('click', () => openBulter(null, {name: 'Draftsman', role: 'Architecture and diagram specialist', model: 'qwen3.8:27b', instructions: 'Draft concise Mermaid flowcharts with explicit assumptions. Use only components and relationships supported by the brief and permitted notes. Return diagram source as text, followed by a short explanation. Do not include scripts, links or external resources. Never invent product capabilities.'}));
function renderProviders() {
  renderRecommendations();
  const localModels = providers.filter(p => !p.cloud).flatMap(p => p.models);
  $('#stat-models').textContent = localModels.length;
  $('#model-note').textContent = providers.some(p => !p.cloud && p.status.startsWith('Connected')) ? 'Available on your Mac' : 'Start Ollama or LM Studio';
  $('#provider-grid').replaceChildren(...providers.map(p => {
    const card = el('article', 'card provider-card');
    const top = el('div', 'card-top'); top.append(el('h3', '', p.label), el('span', `badge ${p.cloud ? 'cloud' : ''}`, p.cloud ? 'Cloud' : 'Local'));
    card.append(top, el('p', '', p.status));
    if (p.cloud) {
      card.append(button(p.credential?.configured ? 'Replace API key' : 'Add API key', 'secondary', () => {
        $('#credential-form').reset(); $('#credential-form .form-error').textContent = '';
        $('#credential-provider').value = p.id; $('#credential-title').textContent = `${p.label} API key`;
        $('#credential-dialog').showModal();
      }));
      if (p.credential?.configured) card.append(button('Remove saved key', 'secondary', () => {
        $('#disconnect-provider').value = p.id; $('#disconnect-form .form-error').textContent = '';
        $('#disconnect-title').textContent = `Remove saved ${p.label} key?`; $('#disconnect-dialog').showModal();
      }));
    }
    if (p.image_models?.length) card.append(el('p', 'help', `Image weights: ${p.image_models.join(', ')}. ${p.image_generation_status || 'Inference unverified'}.`));
    if (p.models.length) {
      const list = el('ul'); for (const model of p.models) list.append(el('li', '', model)); card.append(list);
    } else card.append(el('p', '', p.cloud ? 'Assign an exact model ID to a Bulter. API availability and billing depend on your provider account.' : 'Start the local server, then check connections again.'));
    $('#provider-grid').append(card); return card;
  }));
  const images = el('article', 'card provider-card');
  images.append(el('h3', '', 'MFLUX · local pictures'), el('p', 'help', 'Separate Apple Silicon engine. No API key; terminal workflow.'));
  for (const task of ['flux', 'photo']) {
    const model = imageEngine?.models?.[task];
    images.append(el('p', '', `${model?.label || task}: ${model?.status || 'Status unavailable'}`));
  }
  $('#provider-grid').append(images);
}
async function refresh() {
  state = await api('state');
  renderBulters(); renderMemory(); renderMissions(); renderTeam();
}
async function connections() {
  $('#refresh-models').disabled = true;
  try { [providers, imageEngine] = await Promise.all([api('providers'), api('image-engine')]); renderProviders(); renderBulters(); if ($('#bulter-dialog').open) providerModels(); }
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
$('#bulter-provider').addEventListener('change', () => { $('#bulter-custom-model').value = ''; providerModels(''); });
$('#bulter-model').addEventListener('change', modelEntryMode);
$('#bulter-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = {name: $('#bulter-name').value, role: $('#bulter-role').value, instructions: $('#bulter-instructions').value, provider: $('#bulter-provider').value, model: selectedModel(), shared_memory: $('#bulter-shared').checked, output_tokens: Number($('#bulter-output').value), context_tokens: Number($('#bulter-context').value), thinking: $('#bulter-thinking').value};
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
    const mission = await api('missions', 'POST', {prompt: $('#mission-prompt').value, bulter_ids: team, cloud_consent: $('#cloud-consent').checked, ...connectorMissionOptions()});
    clearConnectorSelection();
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

async function renderUploads() {
  const documents = await api('documents');
  $('#upload-list').replaceChildren();
  for (const doc of documents.reverse()) {
    const card = el('article', 'card');
    card.append(el('h3', '', doc.filename), el('p', 'help', `${doc.status} · ${doc.chunks.length} memory parts · local only`));
    for (const [i, content] of doc.chunks.entries()) {
      const detail = el('details'); detail.append(el('summary', '', `Part ${i + 1}`), el('pre', 'step-output', content)); card.append(detail);
    }
    if (doc.status === 'draft') card.append(button('Approve all parts as local shared memory', 'primary', async () => {
      try { await api(`documents/${doc.id}/approve`, 'POST'); await renderUploads(); await refresh(); notify('Approved notes imported into Obsidian memory.'); }
      catch (error) { $('#upload-status').textContent = error.message; }
    }));
    $('#upload-list').append(card);
  }
}
$('#upload-document').addEventListener('click', async () => {
  $('#upload-dialog').showModal();
  try { await renderUploads(); } catch (error) { $('#upload-status').textContent = error.message; }
});
$('#extract-document').addEventListener('click', async () => {
  const file = $('#upload-file').files[0];
  if (!file || file.size > 10 * 1024 * 1024) { $('#upload-status').textContent = 'Choose a file up to 10 MB.'; return; }
  $('#extract-document').disabled = true; $('#upload-status').textContent = 'Extracting locally…';
  try {
    const response = await fetch(`/api/documents?filename=${encodeURIComponent(file.name)}`, {method: 'POST', headers: {'X-Bulter-Token': token, 'Content-Type': 'application/octet-stream'}, body: file});
    const data = await response.json(); if (!response.ok) throw new Error(data.detail);
    $('#upload-status').textContent = 'Review the extracted text below. Nothing is used as memory until approved.';
    await renderUploads();
  } catch (error) { $('#upload-status').textContent = error.message; }
  finally { $('#extract-document').disabled = false; }
});

$('#remove-bulter-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const submit = $('#remove-bulter-form button[type="submit"]'); submit.disabled = true;
  try {
    await api(`bulters/${$('#remove-bulter-id').value}`, 'DELETE');
    $('#remove-bulter-dialog').close(); await refresh();
    notify('Bulter removed. You can create a replacement or restore it from Removed Bulters.');
  } catch (error) { $('#remove-bulter-form .form-error').textContent = error.message; }
  finally { submit.disabled = false; }
});

$('#credential-dialog').addEventListener('close', () => $('#credential-form').reset());
$('#credential-dialog').addEventListener('cancel', () => $('#credential-form').reset());
window.addEventListener('pagehide', () => $('#credential-form').reset());
$('#credential-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const field = $('#credential-key');
  const submit = $('#credential-form button[type="submit"]'); submit.disabled = true;
  let secret = field.value; field.value = '';
  try {
    await api(`credentials/${$('#credential-provider').value}`, 'PUT', {api_key: secret});
    $('#credential-dialog').close(); await connections(); notify('Key saved in macOS Keychain. Provider access remains unverified until a mission runs.');
  } catch (error) { $('#credential-form .form-error').textContent = error.message; }
  finally { secret = ''; submit.disabled = false; }
});
$('#disconnect-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const submit = $('#disconnect-form button[type="submit"]'); submit.disabled = true;
  try {
    await api(`credentials/${$('#disconnect-provider').value}`, 'DELETE');
    $('#disconnect-dialog').close(); await connections(); notify('Saved key removed from this instance. Remote key was not revoked.');
  } catch (error) { $('#disconnect-form .form-error').textContent = error.message; }
  finally { submit.disabled = false; }
});
