/* =====================================================================
   HalalReady live: the template's Dashboard, driven by the real backend.

   scripts/build_dashboard.py injects this file into index.html's
   script, just before the routing code, so it can use the template's own
   helpers (h, icon, beam, ...) and extend its Dashboard class. The landing
   page and its scripted preview stay as designed; "Live demo" (#demo) opens
   LiveDashboard, which feeds the same graph, log, approval card and pack
   browser from the backend's events instead of buildScript().
   ===================================================================== */
const LIVE_BIZ = 1;
const AG = { coordinator: 'coord', certificate_checker: 'checker', supplier_chaser: 'chaser', document_writer: 'writer',
  onsite_inspector: 'inspector', auditor: 'auditor', renewal_watch: 'renewal', owner: 'owner' };
const AG_BACK = Object.fromEntries(Object.entries(AG).map(([k, v]) => [v, k]));
const LIVE_STATUS = {
  owner: 'Owner', coord: 'Waiting for your files', checker: 'Checks every certificate',
  chaser: 'Contacts your suppliers', writer: 'Drafts your documents', inspector: 'Checks each zone photo',
  auditor: '', pack: '', renewal: 'Watches expiry dates'
};
const LIVE_TOOLS = {
  coord: ['list_files', 'read_document', 'sort_file', 'propose_plan', 'assemble_pack'],
  checker: ['read_document', 'save_ingredients', 'check_certificate', 'ask_owner'],
  chaser: ['draft_message', 'send_after_approval'],
  writer: ['save_document', 'check_requirements'],
  inspector: ['read_photo', 'check_zone', 'ask_owner'],
  renewal: ['schedule_reminder']
};
/* one line per agent, for the plan */
const AGENT_ROLE = {
  certificate_checker: 'Reads every supplier certificate and runs 5 checks on each',
  onsite_inspector: 'Checks each zone photo against the premises requirements',
  document_writer: 'Drafts your halal policy and procedures from your own files',
  supplier_chaser: 'Writes to a supplier when a certificate is missing or expired',
  renewal_watch: 'Watches every expiry date after the pack is built'
};
const CHANNEL = {
  whatsapp: { label: 'WhatsApp', send: 'Send on WhatsApp', done: 'Sent on WhatsApp' },
  telegram: { label: 'Telegram', send: 'Send on Telegram', done: 'Sent on Telegram' },
  email: { label: 'Email', send: 'Send email', done: 'Email sent' }
};
/* the three channels, drawn as small round badges */
const CH_SVG = {
  whatsapp: '<path d="M5.3 18.7l1-3.1a7.4 7.4 0 1 1 2.8 2.5z"/><path d="M9.7 8.9c.3 2.3 2.2 4.2 4.6 4.6l.9-1-1.5-.9-.6.5a3.4 3.4 0 0 1-1.9-1.9l.5-.6-.9-1.5z" fill="currentColor" stroke="none"/>',
  telegram: '<path d="M20.5 4.6 3.6 11.1l5.5 2 2.1 5.9 3.1-4 4.1 3.1z"/><path d="m9.1 13.1 7.3-5.5"/>',
  email: '<rect x="3.6" y="6" width="16.8" height="12" rx="2"/><path d="m4.2 7.4 7.8 5.4 7.8-5.4"/>'
};
const chIcon = key => h('span', { class: 'ch-ico ch-' + key, 'aria-hidden': 'true', html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">' + (CH_SVG[key] || '') + '</svg>' });
/* the graph without the Auditor and the pack node: the pack is the output step, not an agent */
const LIVE_ANCHOR = {
  owner: [.08, .14], coord: [.5, .5], chaser: [.5, .13], checker: [.2, .3], writer: [.8, .3],
  inspector: [.22, .78], renewal: [.78, .78], auditor: [-9, -9], pack: [-9, -9]
};
const HIDDEN_NODES = ['auditor', 'pack'];
const parseJSON = s => { try { return typeof s === 'string' ? JSON.parse(s) : s || null; } catch (_) { return null; } };
const isSheet = name => /\.xlsx?$/i.test(name || '');
const isPdf = name => /\.pdf$/i.test(name || '');

/* an image with boxes drawn on it (positions are shares of the width and height) */
function marked(src, boxes, alt) {
  const wrap = h('div', { class: 'hl-wrap' }, h('img', { class: 'evd-img', src, alt: alt || '' }));
  (boxes || []).forEach(b => { if (b && b.box) wrap.append(h('span', { class: 'hl-box ' + (b.tone || 'bad'), 'data-k': b.key || '', style: { left: b.box[0] * 100 + '%', top: b.box[1] * 100 + '%', width: (b.box[2] - b.box[0]) * 100 + '%', height: (b.box[3] - b.box[1]) * 100 + '%' } })); });
  return wrap;
}
const stateOf = c => c.state || (c.ok ? 'ok' : 'bad');
const isOk = c => stateOf(c) === 'ok';
const STATE_ICON = { ok: 'check', bad: 'x', warn: 'alert', missing: null };
/* the checklist an agent ran: what was checked, what it found, and what to do */
function checkList(checks, img) {
  return h('ul', { class: 'cklist' }, ...(checks || []).map(c => {
    const st = stateOf(c);
    const li = h('li', { class: st }, h('span', { class: 'ck-i', html: STATE_ICON[st] ? icon(STATE_ICON[st]) : '' }),
      h('div', null, h('b', null, c.label), c.detail ? h('span', null, c.detail) : null, c.ask ? h('q', null, c.ask) : null));
    if (img && c.key && c.box) {
      li.addEventListener('mouseenter', () => $$('.hl-box', img).forEach(b => b.classList.toggle('on', b.dataset.k === c.key)));
      li.addEventListener('mouseleave', () => $$('.hl-box', img).forEach(b => b.classList.remove('on')));
    }
    return li;
  }));
}
/* any file the owner gave: photo, PDF or spreadsheet */
function fileView(f) {
  if (isPdf(f.filename)) return h('iframe', { class: 'evd-pdf', src: fileUrl(f.id) + '#toolbar=0&navpanes=0', title: f.filename });
  if (!isSheet(f.filename)) return h('img', { class: 'evd-img', src: fileUrl(f.id), alt: f.filename });
  const box = h('div', { class: 'xs-wrap' }, h('p', { class: 'evd-none' }, 'Opening…'));
  liveApi('/files/' + f.id + '/sheet').then(r => {
    const L = 'ABCDEFGHIJ', n = Math.max(...r.rows.map(x => x.length));
    box.innerHTML = '';
    box.append(h('div', { class: 'xs-scroll' }, h('table', { class: 'xs xs-auto' },
      h('thead', null, h('tr', null, h('th', { class: 'xs-c' }), ...Array.from({ length: n }, (_, k) => h('th', { class: 'xs-c' }, L[k])))),
      h('tbody', null, ...r.rows.map((row, i) => h('tr', { class: i ? '' : 'xs-hd' }, h('td', { class: 'xs-n' }, String(i + 1)), ...Array.from({ length: n }, (_, k) => h('td', null, row[k] || ''))))))),
    h('div', { class: 'xs-tabs' }, ...r.sheets.map((x, k) => h('span', { class: k ? '' : 'on' }, x))));
  }).catch(() => { box.innerHTML = '<p class="evd-none">This file could not be opened.</p>'; });
  return box;
}
/* everything that was dropped: files, and every file inside dropped folders (sub-folders too) */
async function filesFromDrop(dt) {
  const entries = Array.from(dt.items || []).map(i => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);   /* read before any await */
  if (!entries.length) return Array.from(dt.files || []);
  const out = [];
  const walk = async entry => {
    if (entry.isFile) { out.push(await new Promise((res, rej) => entry.file(res, rej))); return; }
    if (!entry.isDirectory) return;
    const reader = entry.createReader();
    for (;;) {
      const batch = await new Promise((res, rej) => reader.readEntries(res, rej));   /* comes in batches of up to 100 */
      if (!batch.length) break;
      for (const e of batch) await walk(e);
    }
  };
  for (const e of entries) await walk(e);
  return out;
}
const fileIcon = name => isSheet(name) ? 'sheet' : /\.(jpe?g|png|heic|webp)$/i.test(name || '') ? 'eye' : 'doc';
const ZONE_LABEL = { store: 'Raw material store', processing: 'Processing area', packing: 'Packing area', cleaning: 'Cleaning area', waste: 'Waste area' };
const zoneChecks = z => ((z.findings || []).filter(f => f.checks).pop() || {}).checks || [];
const ZMARK = { ok: '✓', warn: '⚠', missing: '○', bad: '✗' };
function zoneLine(c) {
  const st = stateOf(c);
  return h('span', { class: 'zc ' + st }, h('i', null, ZMARK[st]), ' ' + c.label.charAt(0).toLowerCase() + c.label.slice(1),
    c.ask ? h('q', null, (st === 'missing' ? ' → ' : ' ') + '“' + c.ask + '”') : null);
}
function zoneSummary(zones, onPick) {
  return h('ul', { class: 'zsum' }, ...zones.filter(z => z.status !== 'unchecked').map(z => {
    const cs = zoneChecks(z), st = cs.some(c => stateOf(c) === 'missing') ? 'missing' : cs.some(c => !isOk(c)) ? 'warn' : 'ok';
    const li = h('li', { class: st }, h('b', null, ZONE_LABEL[z.zone] + ':'), ...cs.map(zoneLine));
    if (onPick) { li.classList.add('pick'); li.addEventListener('click', () => onPick(z)); }
    return li;
  }));
}
const ST_TEXT = { valid: 'Valid', expiring: 'Expiring soon', expired: 'Expired', missing: 'No certificate', unclear: 'Can’t read the scan', unrecognised_issuer: 'Issuer not recognised' };
const ST_RESULT = { valid: 'ok', expiring: 'warn', unclear: 'warn', expired: 'bad', missing: 'bad', unrecognised_issuer: 'bad' };
const LIVE_FILES = [
  { id: 'f1', name: '01_Readiness_Report.pdf', kind: 'pdf', by: 'coord', desc: 'Readiness, open items and what to do before you submit' },
  { id: 'f2', name: '02_Supplier_Certificate_Register.xlsx', kind: 'sheet', by: 'checker', desc: 'Every ingredient with its certificate, issuer and expiry' },
  { id: 'f3', name: '03_Halal_Policy_Draft.docx', kind: 'doc', by: 'writer', desc: 'Your halal policy, drafted from your real details' },
  { id: 'f4', name: '04_SOPs/', kind: 'folder', by: 'writer', desc: 'Ingredient control and traceability procedures' },
  { id: 'f5', name: '05_Premises_Fix_Tracker.xlsx', kind: 'sheet', by: 'inspector', desc: 'What each zone photo shows, and what to fix' },
  { id: 'f6', name: '06_Supplier_Messages/', kind: 'folder', by: 'chaser', desc: 'Messages you approved and the replies' }
];
const TONE_OF = { problem: 'bad', attention: 'attn', ok: 'ok' };
const liveTime = iso => (iso || '').slice(11, 19);
const niceDate = d => d ? new Date(d + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '—';
const fileUrl = id => '/files/' + id + '/content';
const initials = s => (s || '?').split(/\s+/).filter(w => /^[A-Za-z]/.test(w)).slice(0, 2).map(w => w[0].toUpperCase()).join('') || '?';

async function liveApi(path, opts = {}) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || r.statusText);
  return body;
}
const livePost = (path, json) => liveApi(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(json || {}) });

/* the handful of Markdown the Document Writer uses: headings, lists, tables, bold */
function mdNodes(src) {
  const out = [];
  let list = null, table = null;
  const inline = s => { const span = h('span'); span.innerHTML = esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\[TO CONFIRM\]/g, '<mark>TO CONFIRM</mark>'); return span; };
  const flush = () => {
    if (list) { out.push(h(list.t, null, ...list.items.map(i => h('li', null, inline(i))))); list = null; }
    if (table) { out.push(h('table', { class: 'pg-t' }, h('tbody', null, ...table.map((r, i) => h('tr', null, ...r.map(c => h(i ? 'td' : 'th', null, inline(c)))))))); table = null; }
  };
  for (const raw of (src || '').split('\n')) {
    const line = raw.trimEnd(); let m;
    if (/^\s*\|/.test(line)) { if (/^\s*\|[\s:|-]+\|\s*$/.test(line)) continue; if (list) flush(); table = table || []; table.push(line.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim())); continue; }
    if ((m = line.match(/^(#{1,4})\s+(.*)/))) { flush(); out.push(h(m[1].length === 1 ? 'h1' : 'h2', null, inline(m[2]))); continue; }
    if ((m = line.match(/^\s*[-*]\s+(.*)/)) || (m = line.match(/^\s*\d+[.)]\s+(.*)/))) {
      if (table) flush();
      const t = /^\s*\d/.test(line) ? 'ol' : 'ul';
      if (!list || list.t !== t) { flush(); list = { t, items: [] }; }
      list.items.push(m[1]); continue;
    }
    flush();
    if (line.trim()) out.push(h('p', null, inline(line)));
  }
  flush();
  return out;
}

class LiveDashboard extends Dashboard {
  /* ---------- boot: history, snapshot, then the live stream ---------- */
  constructor(host, opts) {
    super(host, opts);
    this.snap = null;
    this.lastId = 0;
    this.queue = [];
    this.replaying = false;
    this.boot();
  }
  async boot() {
    try {
      const events = await liveApi('/business/' + LIVE_BIZ + '/events');
      await this.refresh();
      events.forEach(e => this.applyLive(e, true));
      this.lastId = events.length ? events[events.length - 1].id : 0;
      this.history = events;
      this.layout(); this.settle(220); this.renderDetail();
      if (this.started) this.setTab('agents', true);
    } catch (err) {
      console.error(err);
      document.body.dataset.liveError = String(err && err.stack || err).slice(0, 600);   /* readable in a page dump */
      this.toast(err instanceof TypeError && /fetch/i.test(err.message) ? 'Backend not reachable.' : 'Dashboard error: ' + err.message);
    }
    if (/[?&]still(&|=|$)/.test(location.search)) return;   /* ?still: no live stream (screenshots) */
    this.connect();
    setInterval(() => { if (!document.hidden) this.refreshSoon(); }, 6000);
  }
  connect() {
    const es = new EventSource('/business/' + LIVE_BIZ + '/stream?after_id=' + this.lastId);
    es.onmessage = m => {
      let e; try { e = JSON.parse(m.data); } catch (_) { return; }
      if (e.id <= this.lastId) return;
      this.lastId = e.id;
      (this.history = this.history || []).push(e);
      if (this.replaying) this.queue.push(e); else this.applyLive(e, false);
      this.refreshSoon();
    };
    es.onerror = () => this.setStateChip('paused', 'Reconnecting');
  }
  refreshSoon() { clearTimeout(this.rt); this.rt = setTimeout(() => this.refresh().catch(() => {}), 350); }
  async refresh() {
    const B = '/business/' + LIVE_BIZ;
    liveApi('/demo/agents').then(r => { this.runner = r; this.syncRunner(); }).catch(() => {});
    const [overview, agents, feed, ingredients, site, documents, approvals, tasks, files, pack, suppliers] = await Promise.all([
      liveApi(B + '/overview'), liveApi(B + '/agents'), liveApi(B + '/feed'), liveApi(B + '/ingredients'), liveApi(B + '/site'),
      liveApi(B + '/documents'), liveApi(B + '/approvals'), liveApi(B + '/tasks'), liveApi(B + '/files'), liveApi(B + '/pack'), liveApi(B + '/suppliers')]);
    const hadPack = this.snap ? !!this.snap.overview.latest_pack : null;
    this.snap = { overview, agents, feed, ingredients, site, documents, approvals, tasks, files, pack, suppliers };
    if (hadPack === false && overview.latest_pack) this.toast('Application pack ready', ['Open it', () => { this.pkFile = 'chk'; this.setTab('pack'); }]);
    const first = tasks.filter(t => t.from_agent === 'owner' && t.assignee === 'coordinator').pop();
    this.runTask = first || null;
    this.started = !!first;
    if (first) this.caseText.textContent = first.title;
    this.syncInput();
    this.syncNodes();
    this.syncSats();
    this.syncApprovals();
    this.updateNumbers(false);
    this.syncPackFiles();
    if (this.tab === 'pack') this.renderPack();
    if (!this.selected || !this.selected.startsWith('s:')) this.renderDetail(true);
  }

  /* ---------- events from the backend, in the template's shapes ---------- */
  applyLive(e, instant) {
    const a = AG[e.agent] || (e.agent === 'system' ? (e.handed_to === 'renewal_watch' ? 'pack' : 'coord') : null);
    const to = AG[e.handed_to];
    const ack = /^On it:/.test(e.label);
    const done = /^Done:/.test(e.label);
    const toOwner = /^(Question for you|Needs your OK|Plan ready):/.test(e.label);
    if (!a) return;
    if (ack) { if (a !== 'owner') this.setNode(a, 'working', e.label.replace(/^On it:\s*/, ''), instant); return; }
    let tone = TONE_OF[e.status];
    if (done && e.handed_to) tone = 'ok';
    if (e.agent === 'owner') tone = tone === 'ok' ? 'ok' : undefined;
    let tool = null;
    if (to && to !== a) tool = (done ? '↩ ' : '→ ') + AGENTS[to].name;
    else if (toOwner) tool = '→ Mak Teh';
    else tool = this.toolFor(e.label);
    const text = e.agent === 'system' ? e.label : (e.message && !done ? e.message : done ? (e.message || e.label) : e.label);
    const shown = e.agent === 'system' ? 'renewal' : a === 'pack' ? 'coord' : a;
    const item = { agent: shown, text, tone: toOwner ? 'attn' : tone, tool, time: liveTime(e.created_at), ev: this.evidenceKey(e) };
    if (e.agent === 'owner' && /^Prepare|instruction/i.test(e.label) && e.handed_to === 'coordinator') item.kind = 'prompt';
    if (toOwner) item.action = ['Review', () => this.focusApprovals()];
    this.addFeed(item, instant);
    if (to && to !== a) this.fireEdge({ from: a, to, tone: tone === 'ok' && done ? 'ok' : e.agent === 'owner' ? 'human' : tone === 'bad' ? 'bad' : 'ink', label: e.label }, instant);
    else if (toOwner && a !== 'owner') this.fireEdge({ from: a, to: 'owner', tone: 'human', label: e.label }, instant);
    if (a !== 'owner' && a !== 'pack' && !done) this.setNode(a, null, e.label, instant);
    if (e.agent === 'owner') this.setNode('owner', null, e.label, instant);
  }
  toolFor(label) {
    const rules = [[/^Reading .*Photo/i, 'read_photo'], [/^Reading /, 'read_document'], [/^Opening \d+ files/, 'list_files'],
      [/certificate (valid|expired|expiring)|scan unreadable|issuer not recognised/i, 'check_certificate'], [/^Saved \d+ ingredients/, 'save_ingredients'],
      [/^Drafted /, 'save_document'], [/^Sorted /, 'sort_file'], [/^Checked against|passed review|^Returned|sent with gaps/i, 'check_requirements'],
      [/^(Store|Processing|Packing|Cleaning|Waste):/, 'check_zone'], [/not declared/i, 'check_brand'], [/^Planning/, 'plan'],
      [/^Application pack ready|^Updated your application pack/, 'assemble_pack'], [/^Reminder set|^Watching \d+/, 'schedule_reminder']];
    const r = rules.find(([re]) => re.test(label));
    return r ? r[1] : null;
  }
  evidenceKey(e) {
    if (!this.snap) return null;
    const L = (e.label + ' ' + (e.message || '')).toLowerCase();
    if (/merpati|undeclared|not declared/.test(L)) { const i = this.snap.ingredients.find(x => x.source === 'found_on_site'); return i ? 'ing:' + i.id : 'zone:store'; }
    const zone = (e.label.match(/^(Store|Processing|Packing|Cleaning|Waste):/) || [])[1];
    if (zone) return 'zone:' + zone.toLowerCase();
    if (/: certificate /.test(e.label) || e.status === 'problem' || e.status === 'attention') {
      const i = this.snap.ingredients.find(x => L.startsWith(x.name.toLowerCase()) || L.includes(x.name.toLowerCase() + ':'));
      if (i) return 'ing:' + i.id;
    }
    return null;
  }

  /* ---------- the activity log, with real times ---------- */
  addFeed(e, instant) {
    this.log.push(e);
    const a = AGENTS[e.agent];
    const li = h('li', { class: 'lg' + (e.tone ? ' ' + e.tone : '') + (instant ? '' : ' enter') });
    li.append(a.human ? h('span', { class: 'lg-av human', 'aria-hidden': 'true' }, 'MT') : h('span', { class: 'lg-av', 'aria-hidden': 'true', html: icon(a.icon) }));
    const top = h('div', { class: 'lg-top' }, h('b', null, a.human ? 'Mak Teh' : a.name));
    if (e.tool) top.append(h('span', { class: 'lg-tool' }, e.tool));
    top.append(h('time', null, e.time || ''));
    const body = h('div', { style: { 'min-width': '0' } }, top, h('p', { class: 'lg-text' }, e.text));
    if (e.ev || e.action) {
      const meta = h('div', { class: 'lg-meta' });
      if (e.ev) meta.append(h('button', { class: 'ev-btn', type: 'button', onclick: () => this.openEvidence(e.ev) }, 'See evidence'));
      if (e.action) meta.append(h('button', { class: 'ev-btn', type: 'button', onclick: e.action[1] }, e.action[0]));
      body.append(meta);
    }
    li.append(body);
    this.feed.prepend(li);
    this.logN.textContent = this.log.length + ' events';
    if (!instant && this.logBox.classList.contains('is-min') && this.log.length === 3) this.toggleLog();
  }

  /* ---------- state from the snapshot ---------- */
  reset() {
    this.playing = false; cancelAnimationFrame(this.raf);
    this.t = 0; this.gates = {}; this.events = [];
    this.segs = {}; this.ticks = {};
    LANES.forEach(id => { this.segs[id] = []; this.ticks[id] = []; });
    this.issues = []; this.log = []; this.filesReady = 0; this.complete = false; this.gateAsk = null; this.apCard = null;
    this.prog = {}; this.status = {}; this.state = {}; this.selected = 'coord'; this.userPicked = false;
    NODE_ORDER.forEach(id => { this.prog[id] = { ids: {}, bad: 0 }; this.status[id] = LIVE_STATUS[id]; this.setNodeState(id, 'idle'); });
    this.sats.forEach(s => { s.el.remove(); s.line.remove(); });
    this.sats = [];
    Object.values(this.crossLinks).forEach(l => l.el.remove());
    this.links = this.links.filter(l => !l.cross);
    this.crossLinks = {};
    this.beamLayer.innerHTML = '';
    Object.values(this.baseLinks).forEach(l => l.classList.remove('is-live'));
    this.feed.innerHTML = '';
    this.logN.textContent = '0 events';
    this.apSlot.innerHTML = '';
    this.gBanner.hidden = true;
    this.closeEvidence();
    this.pkFile = 'chk';
    this.layout();
    this.renderDetail();
    this.paintPlay();
  }
  syncNodes() {
    const s = this.snap; if (!s) return;
    const doneBy = {};
    s.tasks.forEach(t => { if (t.status === 'done') doneBy[t.assignee] = (doneBy[t.assignee] || 0) + 1; });
    for (const a of s.agents.agents) {
      const id = AG[a.agent]; if (!id) continue;
      let st = a.in_progress_tasks || a.open_tasks ? 'working' : doneBy[a.agent] ? (this.badCount(id) ? 'flag' : 'done') : 'idle';
      if (id === 'chaser' && s.approvals.some(x => x.kind === 'message' && x.status === 'pending')) st = 'waiting';
      if (id === 'coord' && s.approvals.some(x => (x.kind === 'plan' || (x.kind === 'question' && (parseJSON(x.payload) || {}).options)) && x.status === 'pending')) st = 'waiting';
      if (st !== this.state[id]) { this.segChange(id, this.state[id], st); this.setNodeState(id, st); }
      if (a.state !== 'working' && st !== 'idle') this.status[id] = this.idleLine(id) || this.status[id];
    }
    const needs = s.feed.needs_you.length;
    this.setNodeState('owner', needs ? 'waiting' : this.started ? 'done' : 'idle');
    this.status.owner = needs ? needs + ' thing' + (needs > 1 ? 's' : '') + ' need you' : this.started ? 'Gave one instruction' : LIVE_STATUS.owner;
    const lp = s.overview.latest_pack;
    this.setNodeState('pack', lp ? 'done' : this.started ? 'idle' : 'idle');
    this.status.pack = lp ? lp.items_ready + ' of ' + lp.items_total + ' items ready' : LIVE_STATUS.pack;
    const rw = s.tasks.filter(t => t.assignee === 'renewal_watch');
    if (!rw.length) this.setNodeState('renewal', 'idle');
  }
  idleLine(id) {
    const s = this.snap;
    if (id === 'checker') { const n = s.ingredients.length, ok = s.ingredients.filter(i => ST_RESULT[i.status] === 'ok').length; return n ? n + ' checked, ' + (n - ok) + ' need action' : null; }
    if (id === 'inspector') { const z = s.site.zones.filter(z => z.status !== 'unchecked'); return z.length ? z.length + ' zones checked, ' + z.filter(x => x.status === 'issue').length + ' to fix' : null; }
    if (id === 'writer') return s.documents.length ? s.documents.length + ' documents drafted' : null;
    if (id === 'auditor') { const n = s.documents.filter(d => d.status !== 'draft').length; return n ? n + ' documents reviewed' : null; }
    if (id === 'chaser') { const m = s.approvals.filter(a => a.kind === 'message'); return m.length ? m.filter(a => a.status === 'sent' || a.status === 'replied').length + ' of ' + m.length + ' messages sent' : null; }
    if (id === 'coord') return s.overview.status_by === 'coordinator' ? 'Status sent to Mak Teh' : null;
    return null;
  }
  badCount(id) { return this.sats.filter(x => x.parent === id && x.result === 'bad').length; }
  syncSats() {
    const s = this.snap; if (!s) return;
    const dots = [];
    s.ingredients.filter(i => i.cert_id || i.source === 'found_on_site').forEach(i => dots.push({ agent: 'checker', id: 'i' + i.id, result: ST_RESULT[i.status] || 'ink', label: i.name + ': ' + (ST_TEXT[i.status] || i.status), meta: { kind: 'ing', ing: i, label: i.source === 'found_on_site' ? (i.brand || i.name) : i.name, tag: i.status === 'missing' ? 'NONE' : i.status === 'expired' ? 'EXP' : 'ISS' } }));
    s.site.zones.filter(z => z.status !== 'unchecked').forEach(z => dots.push({ agent: 'inspector', id: 'z' + z.zone, result: z.status === 'issue' ? 'bad' : 'ok', label: ZONE_LABEL[z.zone] + ': ' + (z.findings.filter(f => f.status === 'open' && f.severity !== 'ok').map(f => f.title).join('; ') || 'all checks passed'), meta: { kind: 'zone', zone: z, label: ZONE_LABEL[z.zone].replace(' area', '').toLowerCase(), tag: 'FIX' } }));
    s.documents.forEach(d => {
      const st = d.status === 'approved' ? 'ok' : d.status === 'rejected' ? 'warn' : 'ink';
      dots.push({ agent: 'writer', id: 'd' + d.doc_type, result: st, label: d.title + ': v' + d.version, meta: { kind: 'doc', doc: d, label: d.title.replace(/ (Procedure|for .*)$/i, '') } });
    });
    s.approvals.filter(a => a.kind === 'message').forEach(a => dots.push({ agent: 'chaser', id: 'm' + a.id, result: a.status === 'replied' ? 'ok' : a.status === 'sent' ? 'ok' : a.status === 'failed' ? 'bad' : 'ink', label: a.title + ': ' + a.status, meta: { kind: 'msg', ap: a, label: 'to ' + (this.supplierName(a.supplier_id) || 'supplier').replace(/ Sdn Bhd| Enterprise/, '') } }));
    for (const d of dots) {
      const key = d.agent + ':' + d.id;
      const old = this.sats.find(x => x.key === key);
      if (old && old.result === d.result && old.text === d.label) { old.meta = d.meta; continue; }
      this.liveMeta = d.meta;
      this.addSat(d, !!old || !this.ready);
      this.liveMeta = null;
    }
    this.ready = true;
    NODE_ORDER.forEach(id => {
      const n = this.G[id], bad = this.badCount(id);
      if (this.prog[id]) this.prog[id].bad = bad;
      const bt = n && n.el.querySelector('.badge text');
      if (bt) bt.textContent = bad || '';
      if (n) n.el.classList.toggle('has-bad', bad > 0);
    });
  }
  satMeta(e) { return this.liveMeta || (this.sats.find(x => x.key === e.agent + ':' + e.id) || {}).meta || { kind: 'item', label: e.label || e.id }; }
  supplierName(id) { const s = this.snap && this.snap.suppliers.find(x => x.id === id); return s ? s.name : null; }
  updateNumbers(instant) {
    const s = this.snap;
    const set = (el, v) => { if (instant) el.textContent = String(v); else tickTo(el, v); };
    if (!s) { set(this.k.ready.v, 0); set(this.k.issues.v, 0); set(this.k.files.v, 0); this.k.approvals.v.textContent = '0'; return; }
    const r = s.overview.readiness;
    set(this.k.ready.v, r.done); this.k.ready.v.dataset.of = '/' + r.total;
    const problems = s.ingredients.filter(i => (i.cert_id || i.source === 'found_on_site') && ST_RESULT[i.status] !== 'ok').length + s.site.zones.filter(z => z.status === 'issue').length;
    set(this.k.issues.v, problems); this.k.issues.el.classList.toggle('is-bad', problems > 0);
    this.filesReady = LIVE_FILES.filter(f => this.fileReady(f.id)).length;
    set(this.k.files.v, this.filesReady); this.k.files.v.dataset.of = '/6';
    const asked = s.approvals.filter(a => a.comment !== 'superseded by a new version');
    const decided = asked.filter(a => a.status !== 'pending').length;
    this.k.approvals.v.textContent = String(decided); this.k.approvals.v.dataset.of = asked.length ? '/' + asked.length : '';
    set(this.scoreV, r.score);
    this.scoreRing.setAttribute('stroke-dashoffset', (this.scoreRC * (1 - r.score / 100)).toFixed(1));
    this.scoreBox.classList.toggle('good', r.score >= 80);
    const t = this.scoreBox.querySelector('.score-t');
    if (t) { t.children[1].textContent = r.ingredients_covered + '/' + r.ingredients_total + ' ingredients covered'; t.children[2].textContent = r.zones_clear + '/' + r.zones_total + ' zones clear · ' + r.documents_approved + '/3 documents approved'; }
    this.pkHeadScore.textContent = String(s.pack.items_ready);
    const total = s.tasks.length, doneN = s.tasks.filter(x => x.status === 'done').length;
    this.runBar.style.width = (total ? Math.round(doneN / total * 100) : 0) + '%';
    if (this.runTask) {
      const t0 = new Date(this.runTask.created_at), secs = Math.max(0, Math.round((Date.now() - t0) / 1000));
      const busy = s.agents.agents.some(a => a.in_progress_tasks || a.open_tasks);
      this.ranFor.innerHTML = icon('clock') + (busy ? 'Running for ' : 'Started ') + (busy ? Math.floor(secs / 60) + 'm ' + String(secs % 60).padStart(2, '0') + 's' : liveTime(this.runTask.created_at)) + ', live run';
    } else this.ranFor.innerHTML = icon('clock') + 'Not started';
    this.refreshState();
  }
  refreshState() {
    if (this.tabBtns) { this.tabBtns.input.dataset.done = String(!!this.started); this.tabBtns.agents.dataset.done = String(!!this.snap?.overview.latest_pack); this.tabBtns.pack.dataset.done = String(!!this.snap?.overview.latest_pack); }
    if (this.replaying) return this.setStateChip('running', 'Replaying ' + this.speed + '×');
    if (!this.started) return this.setStateChip('ready', 'Not started');
    const s = this.snap;
    const busy = s && s.agents.agents.filter(a => a.in_progress_tasks || a.open_tasks).length;
    const needs = s ? s.feed.needs_you.length : 0;
    this.pkHeadState.textContent = s && s.overview.latest_pack ? 'Ready for your review' : this.filesReady ? this.filesReady + ' of 6 files ready' : 'Not built yet';
    this.pkHeadState.dataset.state = s && s.overview.latest_pack ? 'complete' : this.filesReady ? 'running' : 'ready';
    const pendingWork = s && s.tasks.some(t => t.status !== 'done');
    if (this.runner && !this.runner.running && pendingWork) return this.setStateChip('waiting', this.runner.starting ? 'Agents starting' : 'Agents offline');
    if (this.runner && this.runner.error && /quota/i.test(this.runner.error)) return this.setStateChip('waiting', 'Out of Gemini quota');
    if (s && s.feed.needs_you.some(n => n.kind === 'question' && (parseJSON(n.payload) || {}).options)) return this.setStateChip('waiting', 'Paused · needs you');
    if (busy) return this.setStateChip('running', busy + ' agent' + (busy > 1 ? 's' : '') + ' working');
    if (needs) return this.setStateChip('waiting', needs + ' need' + (needs > 1 ? '' : 's') + ' you');
    this.setStateChip('complete', s && s.overview.latest_pack ? 'Ready for your review' : 'All quiet');
  }

  /* ---------- the run: start, plan, approvals ---------- */
  start() {
    const q = this.inPrompt.value.trim();
    if (!q) return;
    const s = this.snap;
    if (!s || !s.files.length) { this.toast('Drop your files in first.'); return; }
    this.startBtn.disabled = true;
    livePost('/business/' + LIVE_BIZ + '/runs', { mode: 'prepare', instruction: q })
      .then(() => {
        this.started = true; this.caseText.textContent = q; this.setTab('agents');
        if (!(this.runner && this.runner.running)) this.startAgents(true);
        this.refreshSoon();
      })
      .catch(err => { this.startBtn.disabled = false; this.toast(err.message); });
  }
  focusApprovals() {
    this.setTab('agents');
    const first = this.apSlot.querySelector('.ap:not(.is-done)');
    if (first) first.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'nearest' });
  }
  syncApprovals() {
    const s = this.snap; if (!s) return;
    const order = { plan: 0, question: 1, message: 2 };
    /* documents are approved on the output checklist, not here */
    const needs = s.feed.needs_you.filter(n => (n.type === 'approval' && n.kind !== 'document') || n.type === 'failed_message')
      .sort((a, b) => (order[a.kind] ?? 9) - (order[b.kind] ?? 9) || a.id - b.id);
    this.apCards = this.apCards || {};
    const keep = new Set(needs.map(n => n.type + n.id));
    Object.entries(this.apCards).forEach(([k, el]) => { if (!keep.has(k) && !el.classList.contains('is-done')) el.remove(); if (!keep.has(k)) delete this.apCards[k]; });
    if (this.drafting && needs.some(n => n.kind === 'message')) { this.drafting.remove(); this.drafting = null; }
    needs.forEach(n => {
      const k = n.type + n.id;
      if (this.apCards[k]) return;
      const card = this.liveCard(n);
      this.apCards[k] = card;
      this.apSlot.append(card);
      if (this.ready && !reduced()) card.animate([{ opacity: 0, transform: 'translateY(-8px)', filter: 'blur(6px)' }, { opacity: 1, transform: 'none', filter: 'none' }], { duration: 480, easing: 'cubic-bezier(.2,.8,.2,1)' });
      /* the run stopped on this: show the owner exactly where the problem is */
      if (this.ready && n.kind === 'question' && n.ingredient_id && (parseJSON(n.payload) || {}).options) setTimeout(() => this.openEvidence('ing:' + n.ingredient_id), 500);
    });
    const top = needs[0];
    this.gBanner.hidden = !top;
    if (top) {
      const t = this.gBanner.querySelector('.gb-txt b');
      t.textContent = top.kind === 'plan' ? 'The Coordinator’s plan' : top.kind === 'message' ? 'Message to ' + (top.supplier_name || 'a supplier') : top.title;
      this.gWait.textContent = liveTime(top.created_at).slice(0, 5);
      this.gBanner.querySelector('.gb-ico').innerHTML = icon(top.kind === 'message' ? 'send' : top.kind === 'plan' ? 'hub' : 'hand');
      const go = this.gBanner.querySelector('.gb-go');
      go.hidden = top.kind !== 'plan';
      go.onclick = () => this.approveItem(top);
      this.gBanner.querySelector('.gb-ghost').onclick = () => { this.select(AG[top.requested_by] || 'coord', true); this.focusApprovals(); };
    }
  }
  liveCard(n) {
    const card = h('section', { class: 'ap', 'aria-label': n.title });
    const append = card.append.bind(card);
    card.append = (...xs) => append(...xs.flat().filter(x => x != null && x !== false));   /* skip parts a card doesn't have */
    const who = AGENTS[AG[n.requested_by]] || AGENTS.coord;
    const extra = parseJSON(n.payload) || {};
    const head = (title, ic) => h('div', { class: 'ap-h' }, h('span', { class: 'ap-ico', 'aria-hidden': 'true', html: icon(ic || 'hand') }),
      h('div', { class: 'ap-title' }, h('b', null, title), h('span', null, who.name + ', ' + liveTime(n.created_at).slice(0, 5))));
    const doneHead = text => { card.classList.add('is-done'); card.classList.remove('ap-block'); const ah = card.querySelector('.ap-h'); ah.innerHTML = ''; ah.append(h('span', { class: 'ap-ico ok', 'aria-hidden': 'true', html: icon('done') }), h('div', { class: 'ap-title' }, h('b', null, text), h('span', null, 'at ' + new Date().toTimeString().slice(0, 5)))); card.querySelectorAll('.ap-actions, .ap-opts, .ap-drop, .ap-back, textarea').forEach(x => x.remove());
      /* done cards step aside after a moment, so the next decision stays at the top */
      setTimeout(() => { if (!card.isConnected) return; const go = () => card.remove(); if (reduced()) go(); else card.animate([{ opacity: 1 }, { opacity: 0, transform: 'translateY(-6px)' }], { duration: 350, easing: 'ease-in' }).finished.then(go, go); }, 8000); };
    card.markDone = doneHead;
    const sup = this.snap.suppliers.find(x => x.id === n.supplier_id) || {};
    if (n.type === 'failed_message') {
      card.append(head('Could not send', 'alert'), h('p', { class: 'ap-why' }, n.send_error || 'The message did not go out.'),
        h('div', { class: 'ap-actions' }, h('button', { class: 'btn btn-ink', type: 'button', onclick: () => this.approveItem(n, card) }, 'Try again')));
    } else if (n.kind === 'plan') {
      const steps = parseJSON(n.payload) || [];
      const role = a => h('li', null, h('span', { class: 'lg-av', html: icon(AGENTS[AG[a]].icon) }), h('div', null, h('b', null, AGENTS[AG[a]].name), h('span', null, AGENT_ROLE[a] || '')));
      const ask = h('button', { class: 'btn btn-line', type: 'button' }, 'Ask for a change');
      ask.addEventListener('click', () => {
        if (card.querySelector('.ap-back')) return;
        const box = h('textarea', { class: 'draft ap-back', rows: 2, placeholder: 'What should the Coordinator change?' });
        card.append(box, h('div', { class: 'ap-actions' }, h('button', { class: 'btn btn-ink', type: 'button', onclick: () => {
          if (!box.value.trim()) { box.focus(); return; }
          livePost('/approvals/' + n.id + '/reject', { comment: box.value.trim() }).then(() => { doneHead('You asked for a change'); this.refreshSoon(); }).catch(err => this.toast(err.message));
        } }, 'Send to the Coordinator')));
        box.focus();
      });
      const also = ['supplier_chaser', 'renewal_watch'].filter(a => !steps.some(st => st.assignee === a));
      card.append(head('Approve the plan', 'hub'), h('p', { class: 'ap-why' }, n.body_en || ''),
        h('span', { class: 'mono-l sec' }, 'Working in parallel'),
        h('ol', { class: 'plan-steps' }, ...steps.map(st => role(st.assignee))),
        also.length ? h('span', { class: 'mono-l sec' }, 'Joins when needed') : null,
        also.length ? h('ol', { class: 'plan-steps soft' }, ...also.map(role)) : null,
        h('div', { class: 'ap-actions' }, h('button', { class: 'btn btn-ink mb', type: 'button', onclick: () => this.approveItem(n, card) }, 'Approve the plan'), ask));
    } else if (n.kind === 'message') {
      const ch = CHANNEL[n.channel] || CHANNEL.whatsapp;
      let lang = 'ms';
      const texts = { ms: n.body_ms || n.body_en || '', en: n.body_en || n.body_ms || '' };
      const split = t => { const m = t.match(/^Subject: (.*)\n\n([\s\S]*)$/); return m ? [m[1], m[2]] : [null, t]; };
      const subj = h('b', { class: 'mail-subj' }), bodyText = h('span', { lang: 'ms' });
      const paint = () => { const [sb, b] = split(texts[lang]); subj.textContent = sb || ''; bodyText.textContent = b; bodyText.setAttribute('lang', lang); };
      paint();
      const langBtn = h('button', { class: 'msg-lang', type: 'button' }, 'Show in English');
      langBtn.addEventListener('click', () => { lang = lang === 'ms' ? 'en' : 'ms'; paint(); langBtn.textContent = lang === 'ms' ? 'Show in English' : 'Show in Malay'; });
      const to = sup.contact_name || sup.name || 'Supplier';
      const view = n.channel === 'email'
        ? h('div', { class: 'mail' }, h('div', { class: 'mail-row' }, h('span', null, 'To'), h('b', null, to + ', ' + (sup.name || ''))), h('div', { class: 'mail-row' }, h('span', null, 'Subject'), subj), h('div', { class: 'mail-body' }, bodyText))
        : h('div', { class: 'bubble' + (n.channel === 'telegram' ? ' tg' : '') }, bodyText, h('div', { class: 'bubble-meta' }, h('span', null, 'Draft, not sent')));
      const draft = h('textarea', { class: 'draft', 'aria-label': 'Edit the message', hidden: true, rows: 6 });
      const editBtn = h('button', { class: 'btn btn-line', type: 'button' }, 'Edit');
      editBtn.addEventListener('click', () => {
        if (draft.hidden) { draft.value = texts[lang]; draft.hidden = false; view.hidden = true; editBtn.textContent = 'Save'; draft.focus(); }
        else { texts[lang] = draft.value.trim() || texts[lang]; paint(); draft.hidden = true; view.hidden = false; editBtn.textContent = 'Edit'; }
      });
      card.append(h('div', { class: 'ap-h' }, chIcon(n.channel || 'whatsapp'), h('div', { class: 'ap-title' }, h('b', null, 'Ready to send'), h('span', null, who.name + ', ' + liveTime(n.created_at).slice(0, 5)))),
        h('p', { class: 'ap-why' }, 'Asks ' + (sup.name || 'the supplier') + ' for the renewed cooking oil certificate.'),
        h('div', { class: 'msg ch-' + (n.channel || 'whatsapp') },
          h('div', { class: 'msg-to' }, h('span', { class: 'msg-av', 'aria-hidden': 'true' }, initials(to), chIcon(n.channel || 'whatsapp')), h('div', null, h('b', null, to), h('span', null, (sup.name || '') + ', ' + ch.label))),
          view, draft, langBtn),
        h('div', { class: 'ap-actions' }, h('button', { class: 'btn btn-ink mb', type: 'button', onclick: () => { if (!draft.hidden) editBtn.click(); this.approveItem(n, card, { body_ms: texts.ms, body_en: texts.en }); } }, chIcon(n.channel || 'whatsapp'), ch.send), editBtn));
    } else if (n.kind === 'question' && extra.options) {
      /* a decision the run waits for */
      const ing = this.snap.ingredients.find(i => i.id === n.ingredient_id);
      const failed = ((ing && ing.cert_checks) || []).filter(c => !isOk(c));
      const thumb = n.file_id ? marked(fileUrl(n.file_id), failed.map(c => ({ box: c.box, key: c.key })), n.title) : null;
      if (thumb) { thumb.classList.add('ap-shot'); thumb.addEventListener('click', () => this.openEvidence('ing:' + n.ingredient_id)); }
      card.classList.add('ap-block');
      card.append(head('The run is paused', 'alert'),
        h('div', { class: 'ap-q' }, thumb, h('div', null, h('p', { class: 'ap-why' }, h('b', null, n.title)), failed.map(c => h('p', { class: 'ap-fail', html: icon('x') + '<span>' + esc(c.label) + '</span>' }))[0] || null)),
        h('p', { class: 'ap-why' }, n.body_en || ''),
        h('button', { class: 'ev-btn', type: 'button', onclick: () => this.openEvidence('ing:' + n.ingredient_id) }, 'See where'),
        this.channelButtons(o => this.answerChoice(n, o), true));
    } else if (n.kind === 'question') {
      const zone = extra.zone && this.snap.site.zones.find(z => z.zone === extra.zone);
      const finding = zone && zone.findings.find(f => f.status === 'open' && f.severity !== 'ok');
      const failed = ((finding && finding.checks) || []).filter(c => !isOk(c));
      const fileIn = h('input', { type: 'file', accept: zone ? 'image/*' : 'image/*,application/pdf,.xlsx,.docx', class: 'sr-only' });
      const ask = zone && !n.file_id ? 'Upload a photo' : 'Upload the new photo';
      const picked = h('span', { class: 'fn' }, zone ? ask : 'Attach a file');
      fileIn.addEventListener('change', () => { picked.textContent = fileIn.files[0] ? fileIn.files[0].name : ask; });
      const shot = n.file_id ? (zone ? marked(fileUrl(n.file_id), failed.map(c => ({ box: c.box, tone: stateOf(c) === 'warn' ? 'warn' : 'bad' }))) : h('img', { class: 'ap-thumb', src: fileUrl(n.file_id), alt: '' })) : null;
      if (shot) { shot.classList.add(zone ? 'ap-shot' : 'ap-thumb'); shot.addEventListener('click', () => zone ? this.openEvidence('zone:' + zone.zone) : this.openFileView(n.file_id, n.title)); }
      card.append(head(zone ? (n.file_id ? 'Fix suggested' : 'Photo missing') : 'Needs your answer', zone ? 'eye' : 'hand'),
        h('p', { class: 'ap-why' }, h('b', null, n.title)),
        zone ? shot : h('div', { class: 'ap-q' }, shot, h('p', { class: 'ap-why' }, n.body_en || '')),
        zone && failed.length ? checkList(failed) : null,
        zone ? h('p', { class: 'ap-why ap-tip', html: icon('sparkle') + '<span>' + esc(n.body_en || '') + '</span>' }) : null,
        zone ? h('details', { class: 'zsum-more' }, h('summary', null, 'All zones'), zoneSummary(this.snap.site.zones)) : null,
        h('label', { class: 'dropbar ap-drop' }, h('span', { class: 'dropbar-ico', html: icon('upload') }), picked, fileIn),
        h('div', { class: 'ap-actions' }, h('button', { class: 'btn btn-ink mb', type: 'button', onclick: () => {
          if (!fileIn.files[0]) { this.toast(zone ? 'Choose the new photo first.' : 'Attach a file first.'); return; }
          const fd = new FormData(); fd.append('files', fileIn.files[0]); fd.append('text', n.file_id ? 'New photo after the fix' : 'Here is the photo');
          liveApi('/approvals/' + n.id + '/answer', { method: 'POST', body: fd }).then(() => { doneHead('Photo sent'); this.toast('Sent to the ' + who.name + '.'); this.refreshSoon(); }).catch(err => this.toast(err.message));
        } }, 'Send to the ' + who.name)));
    }
    return card;
  }
  /* how to reach the supplier: three channels, and "Not now" while the run waits */
  channelButtons(onPick, withLater) {
    const box = h('div', { class: 'ap-opts' });
    const opts = Object.entries(CHANNEL).map(([key, c]) => ({ key, label: c.label })).concat(withLater ? [{ key: 'later', label: 'Not now' }] : []);
    opts.forEach(o => box.append(h('button', { class: 'btn ' + (o.key === 'later' ? 'btn-line' : 'btn-ink') + ' ap-opt', type: 'button', onclick: () => {
      box.querySelectorAll('button').forEach(b => { b.disabled = true; });
      onPick(o).catch(err => { this.toast(err.message); box.querySelectorAll('button').forEach(b => { b.disabled = false; }); });
    } }, o.key === 'later' ? null : chIcon(o.key), o.label)));
    return box;
  }
  /* the paused run's question, answered from its card or from the agent's details */
  answerChoice(n, o) {
    const fd = new FormData(); fd.append('text', o.key === 'later' ? 'Not now' : 'Use ' + o.label);
    return liveApi('/approvals/' + n.id + '/answer', { method: 'POST', body: fd }).then(() => {
      const card = this.apCards && this.apCards['approval' + n.id];
      if (card && card.markDone) card.markDone(o.key === 'later' ? 'You chose to wait' : 'You chose ' + o.label);
      if (o.key !== 'later') this.showDrafting(o.key, n.ingredient_id);
      this.refreshSoon();
    });
  }
  /* after the run: ask the supplier now */
  askSupplier(ing, key) {
    return livePost('/business/' + LIVE_BIZ + '/ask-supplier', { ingredient_id: ing.id, channel: key }).then(() => {
      this.setTab('agents');
      this.showDrafting(key, ing.id);
      this.refreshSoon();
    });
  }
  /* upload the fix for one open item; it goes to the agent that owns it */
  uploadBtn(key, label, who) {
    this.followUps = this.followUps || {};
    if (this.followUps[key]) return h('span', { class: 'rc-busy' }, h('i'), this.followUps[key]);
    const input = h('input', { type: 'file', accept: key.startsWith('zone:') ? 'image/*' : 'image/*,application/pdf', class: 'sr-only' });
    input.addEventListener('change', () => {
      if (!input.files[0]) return;
      const fd = new FormData(); fd.append('key', key); fd.append('files', input.files[0]);
      this.followUps[key] = 'Sent to the ' + who + '…';
      this.rerender();
      liveApi('/business/' + LIVE_BIZ + '/follow-up', { method: 'POST', body: fd })
        .then(() => { this.toast('Sent to the ' + who + '.'); this.refreshSoon(); })
        .catch(err => { delete this.followUps[key]; this.rerender(); this.toast(err.message); });
    });
    return h('label', { class: 'btn btn-ink btn-sm rc-up' }, icon('upload'), label, input);
  }
  rerender() { if (this.tab === 'pack') this.renderPack(); this.renderDetail(true); }
  /* what each flagged item needs next, for the agent's details */
  ingStep(i) {
    const s = this.snap;
    const sup = s.suppliers.find(x => x.id === i.supplier_id) || {};
    const who = sup.contact_name || i.supplier_name || 'the supplier';
    const failed = (i.cert_checks || []).filter(c => !isOk(c)).map(c => c.label);
    const q = s.feed.needs_you.find(n => n.kind === 'question' && n.ingredient_id === i.id && (parseJSON(n.payload) || {}).options);
    const m = s.approvals.find(a => a.kind === 'message' && a.ingredient_id === i.id);
    const upload = this.uploadBtn('cert:' + i.id, i.status === 'expired' ? 'Upload renewed certificate' : 'Upload certificate', 'Certificate Checker');
    let text, actions = [];
    if (q) {
      text = 'The run is paused. Choose how I should ask ' + who + ' for the renewed certificate.';
      actions = [this.channelButtons(o => this.answerChoice(q, o), true)];
    } else if (m && m.status === 'pending') {
      text = 'The ' + (CHANNEL[m.channel] || CHANNEL.whatsapp).label + ' to ' + who + ' is drafted and waiting for you.';
      actions = [h('button', { class: 'btn btn-ink btn-sm', type: 'button', onclick: () => this.focusApprovals() }, chIcon(m.channel || 'whatsapp'), 'Review the draft')];
    } else if (m && (m.status === 'sent' || m.status === 'replied')) {
      text = 'Asked ' + who + (m.channel === 'email' ? ' by email' : ' on ' + (CHANNEL[m.channel] || CHANNEL.whatsapp).label) + ' at ' + liveTime(m.sent_at).slice(0, 5) + '. When the renewed certificate comes, upload it and I’ll run the 5 checks again.';
      actions = [upload];
    } else if (s.tasks.some(t => t.assignee === 'supplier_chaser' && t.status !== 'done')) {
      text = 'The Supplier Chaser is writing to ' + who + '.';
    } else {
      text = 'Ask ' + who + ' at ' + (i.supplier_name || 'the supplier') + ' for the renewed certificate, or upload it if you already have it.';
      actions = [this.channelButtons(o => this.askSupplier(i, o.key), false), upload];
    }
    actions.push(h('button', { class: 'ev-btn', type: 'button', onclick: () => this.openEvidence('ing:' + i.id) }, 'See where'));
    return { title: i.name + ': ' + (failed[0] || ST_TEXT[i.status] || i.status), text, actions };
  }
  zoneStep(z) {
    const f = z.findings.find(x => x.status === 'open' && x.severity !== 'ok') || {};
    return { title: ZONE_LABEL[z.zone] + ': ' + (f.title || 'fix needed').toLowerCase(), text: f.suggestion || 'Fix it, then upload a new photo of the zone.',
      actions: [this.uploadBtn('zone:' + z.zone, zoneChecks(z).some(c => stateOf(c) === 'missing') ? 'Upload a photo' : 'Upload new photo', 'On-site Inspector'), h('button', { class: 'ev-btn', type: 'button', onclick: () => this.openEvidence('zone:' + z.zone) }, 'See where')] };
  }
  nextSteps(id) {
    const s = this.snap; if (!s) return [];
    const out = [];
    if (id === 'checker' || id === 'chaser') s.ingredients.filter(i => i.cert_id && ST_RESULT[i.status] !== 'ok').forEach(i => out.push(this.ingStep(i)));
    if (id === 'inspector') s.site.zones.filter(z => z.status === 'issue').forEach(z => out.push(this.zoneStep(z)));
    if (id === 'writer') {
      const waiting = s.documents.filter(d => d.status === 'pending_approval');
      if (waiting.length) out.push({ title: waiting.length + ' document' + (waiting.length > 1 ? 's' : '') + ' waiting for your approval', text: waiting.map(d => d.title).join(', ') + '. Read and approve them on the readiness checklist.',
        actions: [h('button', { class: 'btn btn-ink btn-sm', type: 'button', onclick: () => { this.pkFile = 'chk'; this.setTab('pack'); } }, icon('list'), 'Open the checklist')] });
    }
    if (id === 'coord' || id === 'owner') {
      const n = s.feed.needs_you.length;
      if (n) out.push({ title: n + (n > 1 ? ' things need' : ' thing needs') + ' you', text: 'Each one is on the right, and on the readiness checklist once the pack is built.',
        actions: [h('button', { class: 'btn btn-ink btn-sm', type: 'button', onclick: () => this.focusApprovals() }, 'Show me')] });
    }
    return out;
  }
  stepBox(st) { return h('div', { class: 'nstep' }, h('b', null, st.title), h('p', null, st.text), st.actions.length ? h('div', { class: 'nstep-a' }, ...st.actions) : null); }

  /* while the Supplier Chaser writes the message */
  showDrafting(channel, ingredientId) {
    if (this.drafting) this.drafting.remove();
    const sup = this.snap.suppliers.find(x => x.id === (this.snap.ingredients.find(i => i.id === ingredientId) || {}).supplier_id) || {};
    const ch = CHANNEL[channel];
    this.drafting = h('section', { class: 'ap ap-drafting', 'aria-live': 'polite' },
      h('div', { class: 'ap-h' }, chIcon(channel), h('div', { class: 'ap-title' }, h('b', null, 'Supplier Chaser is writing'), h('span', null, ch.label + ' to ' + (sup.contact_name || sup.name || 'the supplier')))),
      h('div', { class: 'msg ch-' + channel }, h('div', { class: 'pg-skel' }, ...[92, 84, 96, 58].map(w => h('i', { style: { width: w + '%' } })))));
    this.apSlot.append(this.drafting);
  }
  approveItem(n, card, edits) {
    card = card || this.apCards[n.type + n.id];
    const btn = card && card.querySelector('.btn-ink');
    if (btn) { btn.disabled = true; if (!reduced()) btn.classList.add('press'); }
    livePost('/approvals/' + n.id + '/approve', edits || {}).then(r => {
      const ch = CHANNEL[r.channel] || null;
      const msg = n.kind === 'plan' ? 'You approved the plan' : n.kind === 'message' ? (r.status === 'sent' ? (ch ? ch.done : 'Sent') : 'Could not send') : 'You approved the document';
      if (card && card.markDone) card.markDone(msg);
      this.toast(n.kind === 'plan' ? 'Plan approved. The agents are starting.' : n.kind === 'message' ? (r.status === 'sent' ? msg + ' to ' + (n.supplier_name || 'the supplier') + '.' : 'Could not send: ' + (r.send_error || r.status)) : 'Approved.');
      this.refreshSoon();
    }).catch(err => { if (btn) btn.disabled = false; this.toast(err.message); });
  }

  /* ---------- replay: re-animate this run's conversation ---------- */
  play() {
    if (!this.started || !(this.history || []).length) { this.setTab('input'); return; }
    if (this.replaying) { this.paused = false; this.paintPlay(); this.replayStep(); return; }
    const runStart = this.history.findIndex(e => e.agent === 'owner' && e.handed_to === 'coordinator');
    this.replayList = this.history.slice(Math.max(0, runStart - 1)).filter(e => e.agent !== 'system' || e.handed_to);
    this.replayAt = 0; this.replaying = true; this.paused = false; this.playing = true;
    this.feed.innerHTML = ''; this.log = []; this.beamLayer.innerHTML = '';
    this.paintPlay(); this.refreshState(); this.replayStep();
  }
  replayStep() {
    clearTimeout(this.replayTimer);
    if (!this.replaying || this.paused) return;
    const L = this.replayList;
    if (this.replayAt >= L.length) return this.endReplay();
    const e = L[this.replayAt++];
    this.applyLive(e, false);
    const k = this.replayAt / L.length;
    this.scrub.value = String(Math.round(k * 1000)); this.scrub.style.setProperty('--p', (k * 100) + '%');
    const next = L[this.replayAt];
    const gap = next ? Math.min(1400, Math.max(120, new Date(next.created_at) - new Date(e.created_at))) : 0;
    this.replayTimer = setTimeout(() => this.replayStep(), gap / this.speed);
  }
  endReplay() {
    this.replaying = false; this.playing = false; this.paintPlay();
    this.queue.splice(0).forEach(e => this.applyLive(e, false));
    this.refreshState();
  }
  pause(byUser) { if (this.replaying && byUser) { this.paused = true; clearTimeout(this.replayTimer); } this.playing = false; this.paintPlay(); }
  paintPlay() {
    if (!this.playBtn) return;
    const on = this.replaying && !this.paused;
    this.playBtn.innerHTML = icon(on ? 'pause' : 'restart') + (on ? 'Pause' : this.replaying ? 'Resume' : 'Replay');
  }
  seek() { /* the scrub shows replay progress; a live run is not seekable */ }
  fastForward() {}
  advance() {}

  /* ---------- tab 1: input, with the real pile ---------- */
  buildInput() {
    super.buildInput();
    const p = this.panes.input;
    /* tiles and lists are rebuilt from the backend in syncInput() */
    this.inTiles = $('.tiles', p);
    /* everything the owner dropped in, as a pile of small documents */
    this.pileEl = h('div', { class: 'pile', hidden: true });
    this.inTiles.before(this.pileEl);
    this.inFilesHead = $$('.in-sec .mono-l.ok', p)[0];
    this.inFilesChip = $('.cmp-chip.ok', p);
    const drop = $('.dropbar', p), fileIn = $('input[type=file]', drop);
    const upload = files => {
      /* a whole folder comes in at once; system files (.DS_Store, Thumbs.db, ~$ lock files) stay out */
      const keep = Array.from(files || []).filter(f => f.size && !/^(\.|~\$)|^(thumbs\.db|desktop\.ini)$/i.test(f.name))
        .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
      const fd = new FormData(); keep.forEach(f => fd.append('files', f));
      if (!fd.has('files')) { this.toast('No files found in what you dropped.'); return; }
      liveApi('/business/' + LIVE_BIZ + '/files', { method: 'POST', body: fd }).then(r => { this.toast(r.files.length + (r.files.length === 1 ? ' file' : ' files') + ' added.'); this.refreshSoon(); }).catch(err => this.toast(err.message));
    };
    void fileIn;
    const d2 = drop.cloneNode(true); drop.replaceWith(d2);   /* the clone drops the template's 'list only' handlers */
    const fi2 = $('input[type=file]', d2); fi2.addEventListener('change', () => { upload(fi2.files); fi2.value = ''; });
    d2.addEventListener('dragover', e => { e.preventDefault(); d2.classList.add('over'); });
    d2.addEventListener('dragleave', () => d2.classList.remove('over'));
    d2.addEventListener('drop', e => { e.preventDefault(); d2.classList.remove('over'); filesFromDrop(e.dataTransfer).then(upload).catch(err => this.toast(err.message)); });
    const head = d2.querySelector('b'); if (head) { head.textContent = 'Drop your files or a whole folder here'; head.nextSibling && (head.nextSibling.textContent = ' or browse'); }
    /* or pick a folder in the file dialog */
    const folderIn = h('input', { type: 'file', multiple: true, webkitdirectory: true, class: 'sr-only' });
    folderIn.addEventListener('change', () => { upload(folderIn.files); folderIn.value = ''; });
    d2.after(h('label', { class: 'folder-pick' }, icon('folder'), 'or choose a folder', folderIn));
    $('.in-note', p)?.remove();
    $('.own-list', p)?.remove();
    this.inProducts = $$('.cmp-in', p)[1];
    if (this.inProducts) this.inProducts.value = '2 sambal products';
    $$('.sugg-b', p).forEach((b, i) => { const t = ['Prepare Mak Teh Sambal’s halal certification application.', 'Check every supplier certificate before I renew.', 'Check my premises photos for halal risks.'][i]; if (t) { b.textContent = t; b.onclick = () => { this.inPrompt.value = t; this.inPrompt.focus(); }; } });
    [['Plan', 'The Coordinator reads your files'], ['Approve', 'You approve the plan'], ['Work', 'Three agents in parallel'], ['Decide', 'You choose what to do about problems'], ['Output', 'Readiness score and checklist']]
      .forEach(([b, t], i) => { const li = $$('.hsteps li', p)[i]; if (li) { li.querySelector(':scope > b').textContent = b; li.querySelector(':scope > span:last-child').textContent = t; } });
    this.startBtn.querySelector('span').textContent = 'Analyze';
  }
  trayOf(f) {
    if (f.category) return f.category;
    const n = f.filename.toLowerCase();
    if (/photo|zone|site|\.(jpe?g|heic)$/.test(n) && !/cert/.test(n)) return 'site';
    if (/recipe|resipi|label|product|ingredient/.test(n)) return 'products';
    if (/cert|sijil|invoice|invois|supplier|pembekal/.test(n)) return 'suppliers';
    return 'company';
  }
  renderPile(files) {
    const el = this.pileEl;
    el.innerHTML = '';
    el.hidden = !files.length;
    if (!files.length) return;
    const ext = f => (f.filename.split('.').pop() || '').toLowerCase();
    const certs = files.filter(f => /cert|sijil/i.test(f.filename)).length;
    const photos = files.filter(f => /^(jpe?g|png|heic|webp)$/.test(ext(f)) && !/cert|sijil/i.test(f.filename)).length;
    const sheets = files.filter(f => /^xlsx?$/.test(ext(f))).length, pdfs = files.filter(f => ext(f) === 'pdf').length;
    const parts = [[certs, 'certificate'], [sheets, 'spreadsheet'], [pdfs, 'PDF'], [photos, 'photo']].filter(([n]) => n).map(([n, w]) => n + ' ' + w + (n > 1 ? 's' : ''));
    const desk = h('div', { class: 'pile-desk' });
    files.forEach((f, i) => {
      const card = h('button', { class: 'pile-doc', type: 'button', title: f.filename, 'aria-label': 'Open ' + f.filename,
        style: { '--r': (((f.id * 37) % 9) - 4) + 'deg', '--d': (i * 40) + 'ms' }, onclick: () => this.openFileView(f.id) });
      const img = h('img', { src: '/files/' + f.id + '/thumb', alt: '', loading: 'lazy' });
      img.addEventListener('error', () => img.replaceWith(h('span', { class: 'pile-ico', html: icon(fileIcon(f.filename)) })));
      card.append(img, h('span', { class: 'pile-ext ext-' + ext(f) }, ext(f).toUpperCase()),
        h('span', { class: 'pile-n' }, f.filename.replace(/^\d+_/, '').replace(/\.\w+$/, '').replace(/_/g, ' ')));
      desk.append(card);
    });
    el.append(h('div', { class: 'pile-h' }, h('b', null, files.length + ' documents to read, check and file'), h('span', null, parts.join(' · '))), desk);
  }
  syncInput() {
    const s = this.snap; if (!s || !this.inTiles) return;
    const ids = s.files.map(f => f.id + f.filename).join('|');
    if (ids !== this.pileIds) { this.pileIds = ids; this.renderPile(s.files.filter(f => f.source !== 'supplier_reply')); }
    const groups = { suppliers: [], products: [], site: [], company: [] };
    s.files.forEach(f => groups[this.trayOf(f)].push(f));
    const TILES = [['suppliers', 'cert', 'Supplier files', 'Certificates, supplier list, invoices', 'ink'], ['products', 'list', 'Products', 'Recipes and labels', 'ok'], ['site', 'eye', 'Site photos', 'One photo per zone', 'human'], ['company', 'doc', 'Company documents', 'SSM, profile, organisation chart', 'attn']];
    this.inTiles.innerHTML = '';
    let open = this.openTile || null;
    const list = this.fileList;
    TILES.forEach(([key, ic, title, sub, tone]) => {
      const fs = groups[key], n = fs.length;
      const thumbs = h('span', { class: 'tile-thumbs', 'aria-hidden': 'true' }, ...Array.from({ length: Math.min(3, n) }, () => h('i')));
      const t = h('button', { class: 'tile t-' + tone, type: 'button', 'aria-expanded': open === key ? 'true' : 'false' },
        h('span', { class: 'tile-ico', html: icon(ic) }), thumbs, h('b', null, title), h('span', { class: 'tile-sub' }, sub),
        h('span', { class: 'tile-foot' }, h('span', { class: 'tile-types' }, ...[...new Set(fs.map(f => (f.filename.split('.').pop() || '').toLowerCase()))].map(e => h('span', { class: 'tile-ext ext-' + e }, e.toUpperCase()))),
          h('span', { class: 'tile-ok', html: n ? icon('done') + (fs.every(f => f.category) ? 'Sorted' : 'In the pile') : '' })));
      t.addEventListener('click', () => {
        if (this.openTile === key) { this.openTile = null; list.hidden = true; this.syncInput(); return; }
        this.openTile = key; this.syncInput();
      });
      this.inTiles.append(t);
      if (open === key) {
        list.innerHTML = '';
        list.append(h('div', { class: 'tile-list-h' }, h('span', { class: 'mono-l' }, title), h('span', { class: 'mono-l ok' }, n + (n === 1 ? ' file' : ' files'))),
          h('ul', null, ...fs.map(f => h('li', null, h('button', { class: 'fv-btn', type: 'button', title: 'Open ' + f.filename, 'aria-label': 'Open ' + f.filename, html: icon(fileIcon(f.filename)), onclick: () => this.openFileView(f.id) }),
            h('button', { class: 'fn fn-btn', type: 'button', onclick: () => this.openFileView(f.id) }, f.filename)))));
        list.hidden = false;
      }
    });
    if (!open) list.hidden = true;
    const total = s.files.length;
    if (this.inFilesHead) this.inFilesHead.textContent = total ? total + ' files loaded' : 'No files yet';
    if (this.inFilesChip) this.inFilesChip.innerHTML = icon('done') + (total ? total + ' files attached' : 'No files yet');
    this.inFilesChip?.classList.toggle('ok', total > 0);
    this.startBtn.disabled = !!this.started;
    this.startBtn.querySelector('span').textContent = this.started ? 'Analyzing' : 'Analyze';
  }

  /* ---------- the detail panel ---------- */
  renderDetail(soft) {
    if (!this.snap) { if (this.detail) this.detail.innerHTML = ''; return; }
    const id = this.selected;
    NODE_ORDER.forEach(n => this.G[n] && this.G[n].el.classList.toggle('is-sel', n === id));
    const d = this.detail, s = this.snap;
    const grid = rows => h('div', { class: 'dgrid' }, ...rows.map(([k, v, wide]) => h('div', { class: 'dcell' + (wide ? ' wide' : '') }, h('span', { class: 'mono-l' }, k), h('span', { class: 'dv' }, v))));
    const boxes = (a, b) => h('div', { class: 'dboxes' }, ...[a, b].map(([k, v, cls]) => h('div', { class: 'dbox ' + (cls || '') }, h('span', { class: 'mono-l' }, k), h('b', null, v))));
    const head = (ic, title, sub) => h('div', { class: 'dhead' }, h('span', { class: 'dico', html: icon(ic) }), h('div', null, h('b', null, title), h('span', { class: 'dsub' }, sub)));
    let html;
    if (id && id.startsWith('s:')) {
      const sat = this.sats.find(x => 's:' + x.key === id);
      if (!sat) { this.selected = 'coord'; return this.renderDetail(); }
      const m = sat.meta || {}, bad = sat.result === 'bad';
      html = [];
      if (m.kind === 'ing') {
        const i = s.ingredients.find(x => x.id === m.ing.id) || m.ing;
        const certFile = i.cert_file_id && s.files.find(f => f.id === i.cert_file_id);
        html.push(head('cert', i.name, (i.supplier_name || 'No supplier on file') + (i.source === 'found_on_site' ? ', found on site' : '')),
          boxes(['Result', ST_TEXT[i.status] || i.status, ST_RESULT[i.status] === 'ok' ? 'ok' : ST_RESULT[i.status] === 'warn' ? 'warn' : 'bad'], ['Valid until', i.expiry_date ? niceDate(i.expiry_date) : '—']),
          i.cert_checks ? h('span', { class: 'mono-l sec' }, (i.cert_checks.filter(isOk).length) + ' of ' + i.cert_checks.length + ' checks passed') : null,
          i.cert_checks ? checkList(i.cert_checks) : null,
          h('span', { class: 'mono-l sec' }, 'Certificate'),
          grid([['Brand', i.brand || '—'], ['Certificate no.', i.cert_number || '—'], ['Issued by', i.status === 'unclear' ? 'Unreadable' : (i.issuer || '—'), true], ['Used in', (i.products || []).join(', ') || '—', true], ['Tool', 'check_certificate'], ['File', certFile ? certFile.filename : 'None on file', true]]));
        if (ST_RESULT[i.status] !== 'ok' && i.cert_id) html.push(h('span', { class: 'mono-l sec' }, 'Proposed next step'), this.stepBox(this.ingStep(i)));
        if (ST_RESULT[i.status] !== 'ok' || i.cert_file_id) html.push(h('button', { class: 'btn btn-ink btn-sm dbtn', type: 'button', onclick: () => this.openEvidence('ing:' + i.id) }, icon('eye'), 'See the evidence'));
      } else if (m.kind === 'zone') {
        const z = s.site.zones.find(x => x.zone === m.zone.zone) || m.zone;
        const last = z.findings.filter(f => f.checks).pop();
        const zc = (last && last.checks) || [];
        html.push(head('eye', ZONE_LABEL[z.zone], 'Zone photo, checked by the On-site Inspector'), boxes(['Result', bad ? 'Fix needed' : 'Clear', bad ? 'bad' : 'ok'], ['Checks', zc.filter(isOk).length + ' / ' + zc.length]),
          checkList(zc), bad ? h('span', { class: 'mono-l sec' }, 'Proposed next step') : null, bad ? this.stepBox(this.zoneStep(z)) : null,
          h('button', { class: 'btn btn-ink btn-sm dbtn', type: 'button', onclick: () => this.openEvidence('zone:' + z.zone) }, icon('eye'), 'See the photo'));
      } else if (m.kind === 'doc' || m.kind === 'review') {
        const doc = s.documents.find(x => x.id === m.doc.id) || m.doc;
        const st = { draft: 'Draft', pending_approval: 'Passed review, waiting for you', approved: 'Approved', rejected: 'You asked for changes' }[doc.status];
        html.push(head('doc', doc.title, m.kind === 'review' ? 'Reviewed by the Auditor' : 'Drafted by the Document Writer'), boxes(['Status', st, doc.status === 'approved' ? 'ok' : doc.status === 'pending_approval' ? 'ink' : doc.status === 'rejected' ? 'warn' : ''], ['Version', 'v' + doc.version]),
          grid([['Checked against', 'rules/document_requirements.json', true], ['Tool', m.kind === 'review' ? 'check_requirements' : 'save_document']]),
          h('button', { class: 'btn btn-ink btn-sm dbtn', type: 'button', onclick: () => { this.pkFile = doc.doc_type === 'halal_policy' ? 'f3' : 'f4'; this.pkSub = doc.doc_type === 'traceability' ? 1 : 0; this.setTab('pack'); } }, icon('folder'), 'Open in the pack'));
      } else if (m.kind === 'msg') {
        const a = s.approvals.find(x => x.id === m.ap.id) || m.ap;
        html.push(head('send', a.title, 'Drafted by the Supplier Chaser'), boxes(['Status', { pending: 'Waiting for you', sent: 'Sent', replied: 'Replied', failed: 'Not sent', approved: 'Approved' }[a.status] || a.status, a.status === 'replied' || a.status === 'sent' ? 'ok' : a.status === 'failed' ? 'bad' : 'warn'], ['Channel', a.channel || '—']),
          grid([['Message', a.body_ms || a.body_en || '', true]].concat(a.reply_text ? [['Reply', a.reply_text, true]] : [])),
          h('button', { class: 'btn btn-ink btn-sm dbtn', type: 'button', onclick: () => { this.pkFile = 'f6'; this.setTab('pack'); } }, icon('folder'), 'Open in the pack'));
      } else if (m.kind === 'file') {
        html.push(head(m.file.kind === 'sheet' ? 'sheet' : m.file.kind === 'folder' ? 'folder' : 'doc', m.file.name, 'Application Pack file'), boxes(['Status', 'Ready', 'ok'], ['Made by', AGENTS[m.file.by].name]),
          grid([['Contains', m.file.desc, true]]), h('button', { class: 'btn btn-ink btn-sm dbtn', type: 'button', onclick: () => { this.pkFile = m.file.id; this.setTab('pack'); } }, icon('folder'), 'Open in the pack'));
      } else html.push(head('list', m.label || sat.key, AGENTS[sat.parent].name), grid([['Note', sat.text || '', true]]));
    } else {
      const a = AGENTS[id] || AGENTS.coord;
      const st = this.state[id] || 'idle';
      const backend = AG_BACK[id];
      const mine = backend ? s.tasks.filter(t => t.assignee === backend) : [];
      const checked = s.tasks.some(t => t.assignee === 'certificate_checker' && t.status === 'done') ? s.ingredients.length : s.ingredients.filter(i => i.cert_id).length;
      const prog = { checker: [checked, s.ingredients.length], inspector: [s.site.zones.filter(z => z.status !== 'unchecked').length, s.site.zones.length], writer: [s.documents.length, 3], auditor: [s.documents.filter(d => d.status !== 'draft').length, 3], pack: [this.filesReady, 6] }[id] || (mine.length ? [mine.filter(t => t.status === 'done').length, mine.length] : null);
      const firstEv = this.log.find(e => e.agent === id);
      const recent = this.log.filter(e => e.agent === id).slice(-3).reverse();
      html = [
        h('div', { class: 'dhead' }, h('span', { class: 'dico' + (a.human ? ' human' : ''), html: a.human ? '<b>MT</b>' : icon(a.icon) }),
          h('div', null, h('b', null, a.human ? 'Mak Teh (you)' : a.name), h('span', { class: 'dsub mono' }, a.human ? 'Owner, approves the plan and messages' : 'workbuddy/sub-agent/' + (AGENT_SLUG[id] || id)))),
        boxes(['Status', STATE_LABEL[st], st === 'waiting' ? 'warn' : st === 'flag' ? 'bad' : st === 'done' ? 'ok' : st === 'working' ? 'ink' : ''], ['Progress', prog ? prog[0] + ' / ' + prog[1] : '—']),
        h('p', { class: 'dnow' }, this.status[id] || ''),
        ...(id === 'inspector' && s.site.zones.some(z => z.status !== 'unchecked') ? [h('span', { class: 'mono-l sec' }, 'Zone by zone'), zoneSummary(s.site.zones, z => this.openEvidence('zone:' + z.zone))] : []),
        ...(steps => steps.length ? [h('span', { class: 'mono-l sec' }, 'Proposed next step'), ...steps.map(st => this.stepBox(st))] : [])(this.nextSteps(id)),
        h('span', { class: 'mono-l sec' }, 'Run details'),
        grid([['Tools', (LIVE_TOOLS[id] || (id === 'owner' ? ['approvals in the dashboard'] : id === 'pack' ? ['assemble_pack'] : [])).join(', '), true],
          ['Flagged', String(this.badCount(id))], ['Tasks', mine.length ? mine.filter(t => t.status === 'done').length + ' done of ' + mine.length : '—'],
          ['Started', firstEv ? firstEv.time : '—'], ['State', st === 'working' ? 'Running' : STATE_LABEL[st]]])
      ];
      if (recent.length) html.push(h('span', { class: 'mono-l sec' }, 'Recent actions'), h('ul', { class: 'drecent' }, ...recent.map(e => h('li', { class: e.tone || '' }, h('time', null, e.time), h('span', null, e.text)))));
    }
    d.innerHTML = '';
    d.append(...html);
    if (!soft && !reduced()) d.animate([{ opacity: .3, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }], { duration: 260, easing: 'ease-out' });
  }

  /* ---------- evidence: the real file, what was checked, what was found ---------- */
  openDrawer(kicker, title, body) {
    const k = this.drawer.querySelector('.drawer-h .mono-l');
    if (k) { k.textContent = kicker; k.className = 'mono-l ' + (kicker === 'Problem' ? 'bad' : kicker === 'Checked' ? 'ok' : ''); }
    this.drawerTitle.textContent = title;
    this.drawerBody.innerHTML = '';
    this.drawerBody.append(body);
    this.drawer.classList.add('open');
    this.lastFocus = document.activeElement;
    setTimeout(() => this.drawerClose.focus({ preventScroll: true }), 60);
  }
  openFileView(fid, title) {
    const f = (this.snap && this.snap.files.find(x => x.id === fid)) || { id: fid, filename: title || '' };
    this.openDrawer('File', f.filename || title || 'File',
      h('div', { class: 'evd' }, h('div', { class: 'evd-src' }, fileView(f)),
        h('p', { class: 'evd-cap', html: icon(fileIcon(f.filename)) + '<span>' + esc(f.filename) + '</span>' }),
        h('a', { class: 'btn btn-line btn-sm fb-dl', href: fileUrl(fid), download: f.filename }, icon('folder'), 'Download')));
  }
  openEvidence(key) {
    const s = this.snap; if (!s || !key) return;
    const [kind, ref] = key.split(':');
    const wrap = h('div', { class: 'evd' });
    const rows = h('dl', { class: 'evd-rows' });
    const row = (k, v) => rows.append(h('div', { class: 'evd-row' }, h('dt', null, k), h('dd', { html: v })));
    let title = 'Evidence', kicker = 'Checked', src = null, caption = '', checks = [];
    if (kind === 'ing') {
      const i = s.ingredients.find(x => String(x.id) === ref); if (!i) return;
      const f = i.cert_file_id && s.files.find(x => x.id === i.cert_file_id);
      checks = i.cert_checks || [];
      const failed = checks.filter(c => !isOk(c));
      kicker = ST_RESULT[i.status] === 'ok' ? 'Checked' : 'Problem';
      title = i.name + ': ' + (ST_TEXT[i.status] || i.status).toLowerCase();
      if (f) {
        src = marked(fileUrl(f.id), checks.map(c => ({ box: c.box, key: c.key, tone: isOk(c) ? 'ok' : 'bad' })), f.filename);
        src.classList.add(failed.length ? 'show-bad' : 'show-none');
        caption = f.filename + (failed.length ? ', the field in red' : '');
      }
      row('Checked by', 'Certificate Checker <span class="tool">check_certificate</span>');
      row('Supplier', esc(i.supplier_name || '—') + (i.brand ? ', brand ' + esc(i.brand) : ''));
      if (failed.length) row('What’s wrong', '<strong>' + failed.map(c => esc(c.label)).join('<br>') + '</strong>');
      row('Next step', esc({ missing: 'Upload the certificate from the checklist.', expired: 'Ask ' + (i.supplier_name || 'the supplier') + ' for the renewed certificate, then upload it from the checklist.', unclear: 'Upload a clearer copy.', unrecognised_issuer: 'Ask for a certificate from a recognised body, or switch supplier.', valid: 'Nothing to do.', expiring: 'Renewal Watch will ask the supplier before it expires.' }[i.status] || ''));
    } else if (kind === 'zone') {
      const z = s.site.zones.find(x => x.zone === ref); if (!z) return;
      const last = z.findings.filter(f => f.checks).pop() || {};
      checks = last.checks || [];
      const photo = (last.photo_file_id && s.files.find(f => f.id === last.photo_file_id)) || s.files.find(f => f.zone === ref);
      kicker = z.status === 'issue' ? 'Problem' : 'Checked';
      const missing = checks.some(c => stateOf(c) === 'missing');
      title = ZONE_LABEL[ref] + (missing ? ': no photo yet' : z.status === 'issue' ? ': fix needed' : ': all checks passed');
      if (missing) src = h('p', { class: 'evd-none' }, '○  No photo of the ' + ZONE_LABEL[ref].toLowerCase() + ' yet.');
      else if (photo) {
        src = marked(fileUrl(photo.id), checks.filter(c => !isOk(c)).map(c => ({ box: c.box, tone: stateOf(c) === 'warn' ? 'warn' : 'bad' })), photo.filename);
        caption = photo.filename;
      }
      row('Checked by', 'On-site Inspector <span class="tool">check_zone</span>');
      if (z.status === 'issue' && last.suggestion) row('Suggested fix', esc(last.suggestion));
      else row('Next step', 'Nothing to do.');
    } else return;
    wrap.append(h('div', { class: 'evd-src' }, src || h('p', { class: 'evd-none' }, 'No file on record')),
      caption ? h('p', { class: 'evd-cap', html: icon('eye') + '<span>' + esc(caption) + '</span>' }) : null,
      checks.length ? h('span', { class: 'mono-l sec' }, checks.filter(isOk).length + ' of ' + checks.length + ' checks passed') : null,
      checks.length ? checkList(checks, src) : null, rows);
    this.openDrawer(kicker, title, wrap);
  }

  /* ---------- tab 3: the pack, from what the agents produced ---------- */
  buildPackTab() {
    const p = this.panes.pack;
    this.pkList = h('div', { class: 'fb-list', role: 'tablist', 'aria-label': 'Files in the pack' });
    this.pkView = h('div', { class: 'pk-view' });
    this.pkHeadState = h('span', { class: 'fb-state' }, 'Not built yet');
    this.pkHeadScore = h('b', { class: 'tnum' }, '0');
    this.pkHeadTotal = h('span', null, ' of 0 items ready');
    this.pkTodo = h('ul', { class: 'fb-todo' });
    this.pkTodoBox = h('div', { class: 'fb-todo-box', hidden: true }, h('h4', null, 'Before you submit'), this.pkTodo);
    this.pkDownload = h('a', { class: 'btn btn-line btn-sm fb-dl', href: '/business/' + LIVE_BIZ + '/pack/download', hidden: true }, icon('folder'), 'Download the pack');
    const side = h('aside', { class: 'fb-side' },
      h('div', { class: 'fb-root' }, h('span', { class: 'fb-chev', html: icon('back') }), h('span', { class: 'fb-fold', html: icon('folder') }), h('span', null, 'MakTehSambal_ApplicationPack')),
      this.pkScore = h('button', { class: 'pk-score', type: 'button', hidden: true, onclick: () => this.showFile('chk') }),
      this.pkScore, this.pkList, this.pkTodoBox, this.pkDownload,
      h('p', { class: 'fb-note' }, 'WorkBuddy writes these files to your shared folder. You submit on MYeHALAL yourself.'));
    this.pkCrumb = h('span', { class: 'fb-crumb-f' }, '');
    const head = h('div', { class: 'fb-bar' },
      h('div', { class: 'fb-crumb' }, h('span', null, 'Application Pack'), h('span', { class: 'fb-sep' }, '/'), this.pkCrumb),
      h('div', { class: 'fb-meta' }, this.pkHeadState, h('span', { class: 'fb-dot' }), h('span', null, this.pkHeadScore, this.pkHeadTotal)));
    this.pkLock = h('div', { class: 'pk-lock', hidden: true }, h('b', null, 'Nothing here yet'), h('p', null, 'Start the run on the Input tab. Files appear here as the agents finish them.'), h('button', { class: 'btn btn-ink btn-sm', type: 'button', onclick: () => this.setTab('input') }, 'Go to Input'));
    p.append(side, h('div', { class: 'pk-main' }, head, this.pkLock, this.pkView));
    this.fileBtns = {};
    const EXT = { pdf: 'PDF', sheet: 'XLSX', doc: 'DOCX', folder: '' };
    LIVE_FILES.forEach(f => {
      const kindIcon = f.kind === 'sheet' ? 'sheet' : f.kind === 'folder' ? 'folder' : 'doc';
      const nice = f.name.replace(/^\d\d_/, '').replace(/\.\w+$|\/$/, '').replace(/_/g, ' ');
      const b = h('button', { class: 'fb-row', type: 'button', role: 'tab', 'aria-selected': 'false', 'data-state': 'pending', onclick: () => this.showFile(f.id) },
        h('span', { class: 'file-ico ft-' + f.kind, html: icon(kindIcon) }),
        h('span', { class: 'fb-name' }, h('span', null, nice), h('small', null, (EXT[f.kind] ? EXT[f.kind] + ' · ' : 'Folder · ') + AGENTS[f.by].name)),
        h('span', { class: 'pk-st', 'aria-label': 'Status' }, 'Waiting'));
      this.fileBtns[f.id] = b;
      this.pkList.append(b);
    });
    /* first: the readiness checklist, with a follow-up on every open row */
    const chk = h('button', { class: 'fb-row', type: 'button', role: 'tab', 'aria-selected': 'false', 'data-state': 'pending', onclick: () => this.showFile('chk') },
      h('span', { class: 'file-ico ft-sheet', html: icon('list') }),
      h('span', { class: 'fb-name' }, h('span', null, 'Readiness checklist'), h('small', null, 'Score and what is still open')),
      h('span', { class: 'pk-st', 'aria-label': 'Status' }, 'Waiting'));
    this.fileBtns.chk = chk;
    this.pkList.prepend(chk);
    this.pkFile = 'chk';
  }
  fileReady(id) {
    const s = this.snap; if (!s) return false;
    const doc = t => s.documents.find(d => d.doc_type === t);
    return {
      f1: !!s.overview.latest_pack,
      f2: s.ingredients.length > 0 && s.tasks.some(t => t.assignee === 'certificate_checker' && t.status === 'done'),
      f3: !!doc('halal_policy'),
      f4: !!(doc('ingredient_control') || doc('traceability')),
      f5: s.site.zones.every(z => z.status !== 'unchecked'),
      f6: s.approvals.some(a => a.kind === 'message' && (a.status === 'sent' || a.status === 'replied'))
    }[id];
  }
  syncPackFiles() {
    if (!this.snap) return;
    LIVE_FILES.forEach(f => { const b = this.fileBtns[f.id], ok = this.fileReady(f.id), st = ok ? this.fileStatus(f.id) : ['Waiting', 'wait']; b.dataset.state = ok ? 'ready' : 'pending'; const el = b.querySelector('.pk-st'); el.textContent = st[0]; el.dataset.tone = st[1]; });
    const pk = this.snap.pack, cb = this.fileBtns.chk;
    Object.keys(this.followUps || {}).forEach(k => { const it = pk.sections.flatMap(x => x.items).find(x => x.key === k); if (it && it.status === 'ready') delete this.followUps[k]; });
    cb.dataset.state = pk.latest_pack ? 'ready' : 'pending';
    const r = this.snap.overview.readiness, open = pk.items_total - pk.items_ready;
    cb.querySelector('.pk-st').textContent = pk.latest_pack ? (open ? open + ' open' : 'All ready') : 'Waiting';
    cb.querySelector('.pk-st').dataset.tone = pk.latest_pack ? (open ? 'attn' : 'ok') : 'wait';
    this.pkScore.hidden = !pk.latest_pack;
    if (pk.latest_pack) {
      const RC = 2 * Math.PI * 20;
      this.pkScore.innerHTML = '<span class="rc-ring sm"><svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r="20" class="sr-bg"/><circle cx="24" cy="24" r="20" class="sr-fg" stroke="url(#hr-ring)" stroke-dasharray="' + RC.toFixed(1) + '" stroke-dashoffset="' + (RC * (1 - r.score / 100)).toFixed(1) + '" transform="rotate(-90 24 24)"/></svg><b class="tnum">' + r.score + '</b></span>'
        + '<span class="pk-score-t"><b>' + r.score + '% ready</b><span>' + pk.items_ready + ' of ' + pk.items_total + ' items · ' + (open ? open + ' open' : 'nothing open') + '</span></span>';
    }
    this.pkHeadTotal.textContent = ' of ' + pk.items_total + ' items ready';
    this.pkTodo.innerHTML = '';
    pk.missing.forEach(m => {
      const ev = m.key.startsWith('cert:') ? 'ing:' + m.key.split(':')[1] : m.key.startsWith('zone:') ? m.key : null;
      this.pkTodo.append(h('li', null, h('label', null, h('input', { type: 'checkbox' }), h('span', null, m.label + ': ' + (m.reason || 'missing'))),
        ev ? h('button', { class: 'fb-ev', type: 'button', onclick: () => this.openEvidence(ev) }, 'Evidence') : null));
    });
    this.pkTodoBox.hidden = true;
    this.pkDownload.hidden = !this.snap.overview.latest_pack;
  }
  showFile(id) { this.pkFile = id; this.pkSub = 0; this.renderPack(); }
  /* what is in each file, in two words: [text, tone] */
  fileStatus(id) {
    const s = this.snap, pk = s.pack;
    const docSt = d => ({ draft: ['Draft', 'wait'], pending_approval: ['To approve', 'attn'], approved: ['Approved', 'ok'], rejected: ['Changes asked', 'attn'] }[d.status] || ['Draft', 'wait']);
    if (id === 'f1') return pk.missing.length ? [pk.missing.length + ' open', 'attn'] : ['Complete', 'ok'];
    if (id === 'f2') { const n = s.ingredients.length, ok = s.ingredients.filter(i => ST_RESULT[i.status] === 'ok').length; return [ok + ' of ' + n + ' valid', ok === n ? 'ok' : 'attn']; }
    if (id === 'f3') return docSt(s.documents.find(d => d.doc_type === 'halal_policy') || {});
    if (id === 'f4') { const ds = s.documents.filter(d => d.doc_type !== 'halal_policy'), ok = ds.filter(d => d.status === 'approved').length; return ok === ds.length ? ['Approved', 'ok'] : [(ds.length - ok) + ' to approve', 'attn']; }
    if (id === 'f5') { const n = s.site.zones.filter(z => z.status === 'issue').length; return n ? [n + ' to fix', 'attn'] : ['All clear', 'ok']; }
    if (id === 'f6') { const m = s.approvals.filter(a => a.kind === 'message'), sent = m.filter(a => a.status === 'sent' || a.status === 'replied').length; return sent ? [sent + ' sent', 'ok'] : m.length ? ['Draft', 'attn'] : ['None', 'wait']; }
    return ['Ready', 'ok'];
  }
  /* the output: readiness score and a checklist per section; every open row has its follow-up */
  renderChecklist() {
    const s = this.snap, v = this.pkView;
    this.pkCrumb.textContent = 'Readiness checklist';
    v.innerHTML = '';
    if (!this.started || !s) return;
    const pk = s.pack, r = s.overview.readiness;
    if (!pk.latest_pack) {
      v.append(h('div', { class: 'pg pg-wait' }, h('div', { class: 'pg-skel' }, ...[70, 92, 84, 60, 88, 76].map(w => h('i', { style: { width: w + '%' } }))),
        h('p', null, 'The Coordinator builds the checklist when the agents finish.')));
      return;
    }
    const ingOf = key => s.ingredients.find(i => 'cert:' + i.id === key);
    const action = it => {
      const out = [];
      const ev = it.key.startsWith('cert:') ? 'ing:' + it.key.slice(5) : it.key.startsWith('zone:') ? it.key : null;
      if (it.status !== 'ready' && (it.key.startsWith('cert:') || (it.key.startsWith('zone:') && /^open/.test(it.reason || '')))) {
        const zone = it.key.startsWith('zone:'), ing = ingOf(it.key);
        const noPhoto = zone && zoneChecks(s.site.zones.find(z => 'zone:' + z.zone === it.key) || {}).some(c => stateOf(c) === 'missing');
        out.push(this.uploadBtn(it.key, zone ? (noPhoto ? 'Upload a photo' : 'Upload new photo') : ing && ing.status === 'expired' ? 'Upload renewed certificate' : 'Upload certificate', zone ? 'On-site Inspector' : 'Certificate Checker'));
      }
      if (it.key.startsWith('doc:') && it.status !== 'ready' && it.document_id) {
        const ap = s.approvals.find(a => a.kind === 'document' && a.document_id === it.document_id && a.status === 'pending');
        out.push(h('button', { class: 'btn btn-line btn-sm', type: 'button', onclick: () => { const d = s.documents.find(x => x.id === it.document_id); this.pkFile = d && d.doc_type === 'halal_policy' ? 'f3' : 'f4'; this.pkSub = d && d.doc_type === 'traceability' ? 1 : 0; this.renderPack(); } }, 'Read'));
        if (ap) out.push(h('button', { class: 'btn btn-ink btn-sm', type: 'button', onclick: e => { e.currentTarget.disabled = true; livePost('/approvals/' + ap.id + '/approve').then(() => { this.toast('Approved: ' + it.label + '.'); this.refreshSoon(); }).catch(err => this.toast(err.message)); } }, 'Approve'));
      }
      if (ev) out.push(h('button', { class: 'ev-btn', type: 'button', onclick: () => this.openEvidence(ev) }, it.status === 'ready' ? 'View' : 'See where'));
      else if (it.file_id) out.push(h('button', { class: 'ev-btn', type: 'button', onclick: () => this.openFileView(it.file_id) }, 'View'));
      return out;
    };
    const RC = 2 * Math.PI * 30;
    const ring = h('div', { class: 'rc-ring', html: '<svg viewBox="0 0 72 72" aria-hidden="true"><circle cx="36" cy="36" r="30" class="sr-bg"/><circle cx="36" cy="36" r="30" class="sr-fg" stroke="url(#hr-ring)" stroke-dasharray="' + RC.toFixed(1) + '" stroke-dashoffset="' + (RC * (1 - r.score / 100)).toFixed(1) + '" transform="rotate(-90 36 36)"/></svg><b class="tnum">' + r.score + '<small>%</small></b>' });
    const open = pk.items_total - pk.items_ready;
    v.append(h('div', { class: 'rc' },
      h('header', { class: 'rc-head' }, ring,
        h('div', { class: 'rc-sum' }, h('span', { class: 'mono-l' }, 'Readiness score'), h('b', null, pk.items_ready + ' of ' + pk.items_total + ' items ready'),
          h('span', null, open ? open + ' open item' + (open > 1 ? 's' : '') + ', highlighted below with what to do next.' : 'Everything is ready. You can submit on MYeHALAL.')),
        h('a', { class: 'btn btn-line btn-sm', href: '/business/' + LIVE_BIZ + '/pack/download' }, icon('folder'), 'Download the pack')),
      ...pk.sections.map(sec => h('section', { class: 'rc-sec' },
        h('h3', null, h('span', null, sec.title.replace(/^\d+\.\s*/, '')), h('span', { class: 'rc-n tnum' }, sec.items.filter(i => i.status === 'ready').length + ' / ' + sec.items.length)),
        h('ul', null, ...sec.items.map(it => h('li', { class: 'rc-row ' + (it.status === 'ready' ? 'ok' : 'open') },
          h('span', { class: 'ck-i', html: icon(it.status === 'ready' ? 'check' : 'alert') }),
          it.key.startsWith('zone:') ? (z => h('div', { class: 'rc-t' }, h('b', null, ZONE_LABEL[z.zone]), z.status === 'unchecked' ? h('span', null, 'Not checked yet') : h('span', { class: 'rc-z' }, ...zoneChecks(z).map(zoneLine))))(s.site.zones.find(z => 'zone:' + z.zone === it.key) || { zone: it.key.slice(5), status: 'unchecked' })
            : h('div', { class: 'rc-t' }, h('b', null, it.label), h('span', null, (it.status === 'ready' ? (it.note || 'Ready') : (it.reason || 'Missing')).replace(/\d{4}-\d{2}-\d{2}/g, d => niceDate(d)).replace(/^expires/, 'Valid until'))),
          h('div', { class: 'rc-a' }, ...action(it)))))))));
  }
  renderPack() {
    if (!this.pkView) return;
    const s = this.snap;
    this.pkLock.hidden = !!this.started;
    Object.entries(this.fileBtns).forEach(([fid, b]) => b.setAttribute('aria-selected', fid === this.pkFile ? 'true' : 'false'));
    if (this.pkFile === 'chk') return this.renderChecklist();
    const f = LIVE_FILES.find(x => x.id === this.pkFile) || LIVE_FILES[0];
    this.pkCrumb.textContent = f.name;
    const v = this.pkView;
    v.innerHTML = '';
    if (!this.started || !s) return;
    if (!this.fileReady(f.id)) {
      v.append(h('div', { class: 'pg pg-wait' }, h('div', { class: 'pg-skel' }, ...[70, 92, 84, 60, 88, 76].map(w => h('i', { style: { width: w + '%' } }))),
        h('p', null, AGENTS[f.by].name + ' is preparing this file.')));
      return;
    }
    const DATE = niceDate(s.overview.today);
    const tool = (left, right) => h('div', { class: 'vw-tool' }, h('span', { class: 'vw-l' }, ...left), h('span', { class: 'vw-r' }, ...right));
    const pill = t => h('span', { class: 'vw-pill' }, t);
    const sheet = (cols, widths, rows, tabs) => {
      const L = 'ABCDEFGH';
      const t = h('table', { class: 'xs' },
        h('colgroup', null, h('col', { style: { width: '38px' } }), ...widths.map(w => h('col', { style: { width: w } }))),
        h('thead', null, h('tr', null, h('th', { class: 'xs-c' }), ...cols.map((_, k) => h('th', { class: 'xs-c' }, L[k])))),
        h('tbody', null, h('tr', { class: 'xs-hd' }, h('td', { class: 'xs-n' }, '1'), ...cols.map(c => h('td', null, c))),
          ...rows.map((r, k) => h('tr', { class: r.cls || '' }, h('td', { class: 'xs-n' }, String(k + 2)), ...r.cells.map(c => h('td', null, c))))));
      return h('div', { class: 'xs-wrap' }, h('div', { class: 'xs-scroll' }, t), h('div', { class: 'xs-tabs' }, ...tabs.map((x, k) => h('span', { class: k ? '' : 'on' }, x))));
    };
    const res = (txt, tone) => h('span', { class: 'xs-res ' + tone }, txt);
    const letter = ref => h('header', { class: 'pg-lh' }, h('div', null, h('b', null, 'Mak Teh Sambal Sdn Bhd'), h('span', null, 'Lot 7, Jalan Perusahaan 3/2, Seksyen 15, 40200 Shah Alam, Selangor')), h('span', { class: 'pg-ref' }, ref));
    let body;
    if (f.id === 'f2') {
      const rows = s.ingredients.map(i => ({ cls: ST_RESULT[i.status] === 'ok' ? '' : 'bad', cells: [i.supplier_name || '—', i.name + (i.brand ? ' (' + i.brand + ')' : ''), i.cert_number || '—', i.status === 'unclear' ? 'Unreadable' : (i.issuer || '—'), i.expiry_date ? niceDate(i.expiry_date) : '—', ST_RESULT[i.status] === 'ok' ? res(ST_TEXT[i.status], 'ok') : res(ST_TEXT[i.status], 'bad')] }));
      body = [tool([h('b', null, 'Register')], [pill(rows.length + ' rows'), pill('Filter: none')]),
        sheet(['Supplier', 'Item', 'Certificate no.', 'Issued by', 'Valid until', 'Result'], ['22%', '22%', '18%', '16%', '10%', '12%'], rows, ['Register', 'Recognised bodies', 'Notes'])];
    } else if (f.id === 'f5') {
      const rows = s.site.zones.map(z => { const open = z.findings.filter(x => x.severity !== 'ok'); return { cls: z.status === 'issue' ? 'bad' : '', cells: [ZONE_LABEL[z.zone], (open.length ? open : z.findings).map(x => x.title).join('; ') || 'Not checked', z.status === 'clear' ? res('OK', 'ok') : z.status === 'issue' ? res('Fix', 'bad') : res('Open', 'bad'), open.length ? 'Remove it, or declare it with a certificate' : '', open.length ? 'Mak Teh' : ''] }; });
      const photo = s.files.find(x => x.zone === 'store');
      body = [tool([h('b', null, 'Tracker')], [pill(s.site.zones.length + ' zones'), pill(s.site.zones.filter(z => z.status === 'issue').length + ' open')]),
        sheet(['Zone', 'What the photo shows', 'Result', 'Fix', 'Owner'], ['18%', '40%', '10%', '22%', '10%'], rows, ['Tracker', 'Photos']),
        photo ? h('figure', { class: 'vw-fig' }, h('img', { class: 'evd-img', src: fileUrl(photo.id), alt: 'Store photo' }), h('figcaption', null, 'Photo attached to the store row: ' + photo.filename)) : null];
    } else if (f.id === 'f1') {
      const pk = s.pack, r = s.overview.readiness;
      const page = h('article', { class: 'pg' }, letter('Ref. MTS/HR/2026/01'),
        h('h1', null, 'Halal certification readiness report'),
        h('dl', { class: 'pg-meta' }, ...[['Prepared', DATE + (s.overview.latest_pack ? ', ' + liveTime(s.overview.latest_pack.created_at).slice(0, 5) : '')], ['Prepared by', 'Halalah, Coordinator agent'], ['For', 'Mak Teh, Managing Director']].map(([k, x]) => h('div', null, h('dt', null, k), h('dd', null, x)))),
        h('h2', null, '1. Summary'),
        h('p', null, s.overview.status_sentence + ' Readiness: ' + r.score + '% (' + r.done + ' of ' + r.total + ' items).'),
        h('h2', null, '2. Requirements by area'),
        h('table', { class: 'pg-t' }, h('thead', null, h('tr', null, h('th', null, 'Area'), h('th', null, 'Ready'), h('th', null, 'Open items'))),
          h('tbody', null, ...pk.sections.map(g => h('tr', null, h('td', null, g.title.replace(/^\d+\.\s*/, '')), h('td', null, g.items.filter(i => i.status === 'ready').length + ' / ' + g.items.length),
            h('td', null, g.items.filter(i => i.status !== 'ready').map(i => i.label).join('; ') || '—'))))),
        h('h2', null, '3. Actions before submission'),
        h('ol', null, ...(pk.missing.length ? pk.missing.map(m => h('li', null, m.label + ': ' + (m.reason || 'missing'))) : [h('li', null, 'Nothing open.')])),
        h('footer', { class: 'pg-foot' }, h('span', null, 'Prepared with Halalah. Certification decisions rest with JAKIM.'), h('span', null, 'Page 1 of 1')));
      body = [tool([h('b', null, 'Readiness Report')], [pill('100%'), pill('1 page')]), h('div', { class: 'pg-desk' }, page)];
    } else if (f.id === 'f3') {
      const doc = s.documents.find(d => d.doc_type === 'halal_policy');
      const page = h('article', { class: 'pg' }, letter('Doc. MTS/HP/01 · ' + (doc.status === 'approved' ? 'Approved' : 'Draft ' + doc.version)),
        h('table', { class: 'pg-t pg-ver' }, h('tbody', null, ...[['Version', 'v' + doc.version], ['Written by', 'Document Writer agent'], ['Reviewed by', doc.status === 'draft' ? 'Auditor, in review' : 'Auditor agent, passed'], ['Status', { draft: 'Draft', pending_approval: 'Waiting for your approval', approved: 'Approved by Mak Teh', rejected: 'You asked for changes' }[doc.status]]].map(([k, x]) => h('tr', null, h('th', null, k), h('td', null, x))))),
        ...mdNodes(doc.body), h('footer', { class: 'pg-foot' }, h('span', null, 'Draft for review by Mak Teh'), h('span', null, DATE)));
      body = [tool([h('b', null, doc.title)], [pill('100%'), pill('v' + doc.version)]), h('div', { class: 'pg-desk' }, page)];
    } else {
      const items = f.id === 'f4'
        ? s.documents.filter(d => d.doc_type !== 'halal_policy').map(d => ({ name: 'SOP_' + d.doc_type + '_v' + d.version + '.docx', title: d.title, doc: d }))
        : s.approvals.filter(a => a.kind === 'message').map(a => ({ name: (a.sent_at || a.created_at).slice(0, 10) + '_' + (this.supplierName(a.supplier_id) || 'supplier').replace(/\s+/g, '_') + '.txt', title: a.title, ap: a }));
      const k = Math.min(this.pkSub || 0, Math.max(0, items.length - 1));
      const list = h('div', { class: 'flst' }, h('div', { class: 'fl-h' }, h('span', null, 'Name'), h('span', null, 'Kind')),
        ...items.map((it, n) => h('button', { class: 'fl-row', type: 'button', 'aria-selected': n === k ? 'true' : 'false', onclick: () => { this.pkSub = n; this.renderPack(); } },
          h('span', { class: 'file-ico ' + (f.id === 'f4' ? 'ft-doc' : 'ft-msg'), html: icon(f.id === 'f4' ? 'doc' : 'send') }), h('span', { class: 'fl-n' }, it.name), h('span', { class: 'fl-k' }, f.id === 'f4' ? 'Word document' : 'Message'))));
      const it = items[k];
      let prev = h('p', { class: 'wa-sys' }, 'Nothing here yet.');
      if (it && f.id === 'f4') {
        prev = h('article', { class: 'pg' }, letter('SOP ' + (k + 1) + ' · v' + it.doc.version), ...mdNodes(it.doc.body));
      } else if (it) {
        const a = it.ap, sup = this.snap.suppliers.find(x => x.id === a.supplier_id) || {};
        prev = h('div', { class: 'wa' }, h('div', { class: 'wa-h' }, h('span', { class: 'msg-av' }, initials(sup.contact_name || sup.name)), h('div', null, h('b', null, sup.contact_name || sup.name || ''), h('span', null, sup.name || ''))),
          h('div', { class: 'wa-b' }, h('span', { class: 'wa-day' }, niceDate((a.sent_at || a.created_at).slice(0, 10))),
            h('div', { class: 'bubble' }, h('span', { lang: 'ms' }, a.body_ms || a.body_en || ''), h('div', { class: 'bubble-meta', html: '<span>' + liveTime(a.sent_at).slice(0, 5) + '</span>' + (a.status === 'sent' || a.status === 'replied' ? icon('ticks') : '') })),
            a.reply_text || a.reply_file_id ? h('div', { class: 'bubble wa-in' }, a.reply_file_id ? h('img', { class: 'wa-img', src: fileUrl(a.reply_file_id), alt: 'Attachment' }) : null, a.reply_text ? h('span', null, a.reply_text) : null, h('div', { class: 'bubble-meta' }, h('span', null, liveTime(a.replied_at).slice(0, 5)))) : null,
            h('p', { class: 'wa-sys' }, a.status === 'pending' ? 'Draft, waiting for Mak Teh’s approval' : a.status === 'replied' ? 'Supplier replied; the Certificate Checker read the file' : 'Sent after Mak Teh approved it' + (a.channel ? ', via ' + a.channel : ''))));
      }
      body = [tool([h('b', null, f.name.replace(/^\d\d_/, '').replace(/\/$/, '').replace(/_/g, ' '))], [pill(items.length + ' items')]), list, h('div', { class: 'pg-desk' }, prev)];
    }
    v.append(...body.filter(Boolean));
  }

  /* ---------- the agents themselves: running, offline, out of quota ---------- */
  startAgents(quiet) {
    this.agentBtn.disabled = true;
    livePost('/demo/agents/start').then(() => {
      if (!quiet) this.toast('Starting the agents…');
      this.runner = Object.assign({}, this.runner, { starting: true }); this.syncRunner();
      [2500, 5000, 9000].forEach(ms => setTimeout(() => this.refreshSoon(), ms));
    }).catch(err => { this.agentBtn.disabled = false; this.toast(err.message); });
  }
  stopAgents() {
    livePost('/demo/agents/stop').then(() => { this.toast('Agents stopped.'); this.refreshSoon(); }).catch(err => this.toast(err.message));
  }
  syncRunner() {
    const r = this.runner || {};
    const quota = r.error && /quota/i.test(r.error);
    this.agentBox.dataset.state = r.running ? (quota ? 'error' : 'on') : r.starting ? 'starting' : 'off';
    this.agentText.textContent = r.running ? (quota ? 'Out of Gemini quota' : 'Agents running') : r.starting ? 'Agents starting…' : 'Agents offline';
    this.agentSub.textContent = r.running ? (quota ? 'Add a key from another project, or wait for the daily reset' : (r.model || 'Gemini') + ' · ' + (r.keys || 1) + ' key' + ((r.keys || 1) > 1 ? 's' : '')) : r.starting ? 'Loading the agents' : 'Start them to process the run';
    this.agentBtn.hidden = !!(r.running || r.starting);
    this.agentBtn.disabled = false;
    this.agentStop.hidden = !r.running;
    /* a run with work left and no agents (a restart, a reload): bring them back */
    if (!r.running && !r.starting && this.started && !this.autoStarted) { this.autoStarted = true; this.startAgents(true); }
    this.refreshState();
  }

  /* ---------- the shell: agents kept running quietly, a small start-over button ---------- */
  build() {
    super.build();
    /* the agents are started with Analyze; their box stays out of sight */
    this.agentText = h('b', null, '');
    this.agentSub = h('span', null, '');
    this.agentBtn = h('button', { class: 'btn btn-ink btn-sm', type: 'button', onclick: () => this.startAgents() }, icon('play'), 'Start');
    this.agentStop = h('button', { class: 'agent-stop', type: 'button', hidden: true, onclick: () => this.stopAgents() }, 'Stop');
    this.agentBox = h('div', { class: 'agent-box', 'data-state': 'off', hidden: true }, this.agentText, this.agentSub, this.agentBtn, this.agentStop);
    this.ranFor.after(this.agentBox);
    const replay = $('.replay', this.root); if (replay) replay.hidden = true;
    /* start over: two taps, so it is never hit by accident */
    let armed = null;
    const reset = h('button', { class: 'icon-btn reset-btn', type: 'button', title: 'Start over', 'aria-label': 'Start over', html: icon('restart') });
    reset.addEventListener('click', () => {
      if (!armed) { reset.classList.add('armed'); reset.title = 'Tap again to start over'; armed = setTimeout(() => { armed = null; reset.classList.remove('armed'); reset.title = 'Start over'; }, 3000); return; }
      clearTimeout(armed);
      livePost('/demo/reset').then(() => { location.hash = '#demo'; location.reload(); }).catch(err => this.toast(err.message));
    });
    const end = $('.dt-end', this.root);
    end.insertBefore(reset, end.children[1] || null);
    /* presenter: the right arrow moves the run on to its next step (nothing on screen) */
    document.addEventListener('keydown', e => {
      if (e.key !== 'ArrowRight' || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || e.repeat) return;
      if (!this.root.isConnected || this.host.hidden || (e.target.closest && e.target.closest('input, textarea, select, [contenteditable]'))) return;
      livePost('/demo/next').catch(() => {});
    });
  }

  /* ---------- the graph: no Auditor, and the pack is the output step, not a node ---------- */
  buildGraph() {
    super.buildGraph();
    HIDDEN_NODES.forEach(id => this.G[id].el.remove());
    this.links = this.links.filter(l => { const gone = HIDDEN_NODES.includes(l.a) || HIDDEN_NODES.includes(l.b); if (gone) l.el.remove(); return !gone; });
    HIDDEN_NODES.forEach(id => delete this.baseLinks[id]);
    const l = svgEl('line', { class: 'gk dashed' });
    this.gLinks.append(l);
    this.links.push({ a: 'coord', b: 'renewal', el: l });
    this.baseLinks.renewal = l;
  }
  anchor(id) { return LIVE_ANCHOR[id]; }
  /* placeholders need a count up front: certificates to check and zones to inspect come from the snapshot */
  expectedDots(id) {
    const s = this.snap; if (!s) return 0;
    if (id === 'checker') return s.ingredients.filter(i => i.cert_id || i.proof_type === 'halal_certificate').length;
    if (id === 'inspector') return s.site.zones.length;
    return 0;
  }
  layout() {
    const W = this.gWrap.clientWidth, H = this.gWrap.clientHeight;
    if (!W || !H) return;
    this.W = W; this.H = H;
    this.svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    NODE_ORDER.forEach(id => {
      const n = this.G[id];
      const nx = LIVE_ANCHOR[id][0] * W, ny = LIVE_ANCHOR[id][1] * H;
      const dx = nx - n.x, dy = ny - n.y;
      n.x = nx; n.y = ny;
      this.sats.filter(s => s.parent === id).forEach(s => { s.x += dx; s.y += dy; });
      n.el.setAttribute('transform', 'translate(' + nx.toFixed(1) + ' ' + ny.toFixed(1) + ')');
    });
    this.drawLinks();
    this.kick();
  }
}
