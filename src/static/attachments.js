/* Mission-local attachments; all previews use textContent or normalized JPEG data. */
let missionAttachments = [];
let attachmentsUploading = false;
const attachmentSection = document.createElement('section');
attachmentSection.className = 'mission-attachments';
attachmentSection.innerHTML = `<label for="mission-files">Files & photos for this mission</label>
<input id="mission-files" type="file" multiple accept=".txt,.md,.pdf,.docx,.pptx,.png,.jpg,.jpeg,.webp">
<p class="help">Up to 5 files, 10 MB each, 12,000 extracted characters combined. Documents: text and tables only, not embedded pictures. Photos: PNG, JPEG or WebP, up to 20 MP, resized to 1600 px; every selected Bulter must use an Ollama vision model. Files stay on this Mac and do not become shared memory.</p>
<div id="attachment-list" aria-live="polite"></div>
<label for="attachment-mode">How should the file be used?</label><select id="attachment-mode"><option value="reference">Analyze / use as reference</option><option value="reuse_design">Create new content using its design</option><option value="edit">Edit existing document or slides</option><option value="placeholders">Fill explicit template placeholders</option></select><p class="help">Design reuse and edits use one Bulter and exact text replacements. Images, charts, masters, and page structure are preserved, not edited. Proposed changes are shown as JSON for review; ambiguous edits cannot export.</p><label for="mission-template">Office source / template (optional for reference)</label><select id="mission-template"><option value="">Standard Word / PowerPoint output</option></select>
<p class="help">To preserve an Office template, place {{RESPONSE}} in a paragraph or slide text box. Optional: {{REQUEST}}. Original slides, styles and layout remain; replacement uses the first run's formatting. Review long text for overflow. Ordinary sample files can instead guide the model through your brief.</p>
<label class="check"><input id="attachment-cloud-consent" type="checkbox"><span>I approve sending these documents, filenames and derived results to the cloud providers selected for this mission. Photos currently remain local.</span></label>`;
document.querySelector('#run-mission').before(attachmentSection);

async function photoPreview(item, target) {
  const response = await fetch(`/api/attachments/${item.id}/preview`, {headers: {'X-Bulter-Token': token}});
  if (!response.ok) throw new Error('Photo preview unavailable.');
  const reader = new FileReader();
  reader.onload = () => { const img = document.createElement('img'); img.src = reader.result; img.alt = item.filename; img.className = 'attachment-photo'; target.append(img); };
  reader.readAsDataURL(await response.blob());
}
function drawAttachments() {
  const list = document.querySelector('#attachment-list'); list.replaceChildren();
  const select = document.querySelector('#mission-template'); const previous = select.value;
  select.replaceChildren(new Option('Standard Word / PowerPoint output', ''));
  for (const item of missionAttachments) {
    const card = document.createElement('div'); card.className = 'attachment-card';
    const name = document.createElement('strong'); name.textContent = item.filename;
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'secondary'; remove.textContent = 'Detach';
    remove.onclick = () => { missionAttachments = missionAttachments.filter(a => a.id !== item.id); drawAttachments(); };
    card.append(name, remove);
    if (item.kind === 'image') photoPreview(item, card).catch(e => notify(e.message));
    else { const details = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = `Review extracted text (${item.text.length} characters)`; const pre = document.createElement('pre'); pre.className = 'attachment-text'; pre.textContent = item.text; details.append(summary, pre); card.append(details); }
    list.append(card);
    if (/\.(docx|pptx)$/i.test(item.filename)) select.add(new Option(item.filename, item.id));
  }
  if ([...select.options].some(o => o.value === previous)) select.value = previous;
  document.querySelector('#attachment-cloud-consent').checked = false;
}
document.querySelector('#mission-files').addEventListener('change', async event => {
  if (attachmentsUploading) return;
  attachmentsUploading = true;
  try {
    const files = [...event.target.files];
    if (files.length + missionAttachments.length > 5) throw new Error('Attach at most five files per mission.');
    for (const file of files) {
      if (!file.size || file.size > 10 * 1024 * 1024) throw new Error('Each file must be nonempty and at most 10 MB.');
      const response = await fetch(`/api/attachments?filename=${encodeURIComponent(file.name)}`, {method: 'POST', headers: {'X-Bulter-Token': token, 'Content-Type': 'application/octet-stream'}, body: file});
      const result = await response.json(); if (!response.ok) throw new Error(result.detail || 'Upload failed.');
      missionAttachments.push(result); drawAttachments();
    }
  } catch (error) { notify(error.message); }
  finally { attachmentsUploading = false; event.target.value = ''; }
});
function attachmentMissionOptions() {
  if (attachmentsUploading) throw new Error('Wait for uploads to finish before starting the mission.');
  return {attachment_mode: document.querySelector('#attachment-mode').value, attachment_ids: missionAttachments.map(a => a.id), template_id: document.querySelector('#mission-template').value || null, attachment_cloud_consent: document.querySelector('#attachment-cloud-consent').checked};
}
function clearMissionAttachments() { missionAttachments = []; document.querySelector('#attachment-mode').value = 'reference'; drawAttachments(); }
function renderMissionAttachments(mission, panel) {
  for (const item of mission.attachments || []) {
    const card = document.createElement('details'); card.className = 'attachment-card';
    const heading = document.createElement('summary'); heading.textContent = `Attachment: ${item.filename}`; card.append(heading);
    if (item.kind === 'image') photoPreview(item, card).catch(e => notify(e.message));
    else { const pre = document.createElement('pre'); pre.className = 'attachment-text'; pre.textContent = item.text; card.append(pre); }
    panel.append(card);
  }
  const template = (mission.attachments || []).find(a => a.id === mission.template_id);
  if (template && mission.status === 'completed') {
    const format = template.filename.split('.').pop().toLowerCase();
    panel.append(button(`Download using ${template.filename}`, 'secondary', async () => {
      try {
        const response = await fetch(`/api/missions/${mission.id}/export/${format}?use_template=true`, {headers: {'X-Bulter-Token': token}});
        if (!response.ok) throw new Error((await response.json()).detail);
        const url = URL.createObjectURL(await response.blob()); const a = document.createElement('a'); a.href = url; a.download = `bulter-template-output.${format}`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (error) { notify(error.message); }
    }));
  }
}
