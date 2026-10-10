/* =====================================================================
   HalalReady live: the template's Dashboard, driven by the real backend.

   scripts/build_dashboard.py injects this file into GreenHalalReady.html's
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
  owner: 'Owner, sample case', coord: 'Waiting for your instruction', checker: 'Checks every certificate',
  chaser: 'Waiting for work', writer: '3 documents to draft', inspector: '5 zone photos',
  auditor: 'Reviews every document', pack: 'Built at the end', renewal: 'Wakes on expiry dates'
};
const LIVE_TOOLS = {
  coord: ['read_document', 'sort_file', 'propose_plan', 'set_status', 'assemble_pack'],
  checker: ['read_document', 'record_certificate', 'check_brand', 'ask_owner'],
  chaser: ['request_supplier_message'],
  writer: ['save_document', 'get_document'],
  inspector: ['read_document', 'compare_store_brands', 'save_site_finding'],
  auditor: ['check_requirements', 'request_document_approval'],
  renewal: ['get_case', 'create_task']
};
const ZONE_LABEL = { store: 'Raw material store', processing: 'Processing area', packing: 'Packing area', cleaning: 'Cleaning area', waste: 'Waste area' };
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
    if (/[?&]still/.test(location.search)) return;   /* ?still: no live stream (screenshots) */
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
    const [overview, agents, feed, ingredients, site, documents, approvals, tasks, files, pack, suppliers] = await Promise.all([
      liveApi(B + '/overview'), liveApi(B + '/agents'), liveApi(B + '/feed'), liveApi(B + '/ingredients'), liveApi(B + '/site'),
      liveApi(B + '/documents'), liveApi(B + '/approvals'), liveApi(B + '/tasks'), liveApi(B + '/files'), liveApi(B + '/pack'), liveApi(B + '/suppliers')]);
    this.snap = { overview, agents, feed, ingredients, site, documents, approvals, tasks, files, pack, suppliers };
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
    const rules = [[/^Reading /, 'read_document'], [/certificate (valid|expired|expiring)|scan unreadable|issuer not recognised/i, 'record_certificate'],
      [/^Drafted /, 'save_document'], [/^Sorted /, 'sort_file'], [/passed review|^Returned|sent with gaps/i, 'check_requirements'],
      [/^(Store|Processing|Packing|Cleaning|Waste):/, 'save_site_finding'], [/not declared/i, 'check_brand'], [/^Planning/, 'plan']];
    const r = rules.find(([re]) => re.test(label));
    return r ? r[1] : null;
  }
  evidenceKey(e) {
    if (!this.snap) return null;
    const L = (e.label + ' ' + (e.message || '')).toLowerCase();
    if (/merpati|undeclared|not declared/.test(L)) { const i = this.snap.ingredients.find(x => x.source === 'found_on_site'); return i ? 'ing:' + i.id : 'zone:store'; }
    const zone = (e.label.match(/^(Store|Processing|Packing|Cleaning|Waste):/) || [])[1];
    if (zone && e.status !== 'ok') return 'zone:' + zone.toLowerCase();
    if (e.status === 'problem' || e.status === 'attention') {
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
    this.pkFile = 'f1';
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
      let st = a.state === 'working' ? 'working' : a.state === 'waiting' ? 'working' : doneBy[a.agent] ? (this.badCount(id) ? 'flag' : 'done') : 'idle';
      if (id === 'chaser' && s.approvals.some(x => x.kind === 'message' && x.status === 'pending')) st = 'waiting';
      if (id === 'coord' && s.approvals.some(x => x.kind === 'plan' && x.status === 'pending')) st = 'waiting';
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
    s.ingredients.forEach(i => dots.push({ agent: 'checker', id: 'i' + i.id, result: ST_RESULT[i.status] || 'ink', label: i.name + ': ' + (ST_TEXT[i.status] || i.status), meta: { kind: 'ing', ing: i, label: i.source === 'found_on_site' ? (i.brand || i.name) : i.name, tag: i.status === 'missing' ? 'NONE' : i.status === 'expired' ? 'EXP' : 'ISS' } }));
    s.site.zones.filter(z => z.status !== 'unchecked').forEach(z => dots.push({ agent: 'inspector', id: 'z' + z.zone, result: z.status === 'issue' ? 'bad' : 'ok', label: ZONE_LABEL[z.zone] + ': ' + (z.findings.filter(f => f.severity !== 'ok').map(f => f.title).join('; ') || 'nothing to flag'), meta: { kind: 'zone', zone: z, label: ZONE_LABEL[z.zone].replace(' area', '').toLowerCase(), tag: 'FIX' } }));
    const returned = new Set((this.history || []).filter(e => e.agent === 'auditor' && /Returned/i.test(e.label)).map(e => (e.label.match(/(halal_policy|ingredient_control|traceability)/) || [])[1]));
    s.documents.forEach(d => {
      const st = d.status === 'approved' || d.status === 'pending_approval' ? 'ok' : d.status === 'rejected' ? 'warn' : 'ink';
      dots.push({ agent: 'writer', id: 'd' + d.doc_type, result: st, label: d.title + ': v' + d.version, meta: { kind: 'doc', doc: d, label: d.title.replace(/ (Procedure|for .*)$/i, '') } });
      if (d.status !== 'draft' || returned.has(d.doc_type)) dots.push({ agent: 'auditor', id: 'a' + d.doc_type, result: d.status === 'draft' ? 'warn' : 'ok', label: d.title + (d.status === 'draft' ? ': returned to the Writer' : ': passed review'), meta: { kind: 'review', doc: d, label: 'review: ' + d.title.replace(/ (Procedure|for .*)$/i, '').toLowerCase() } });
    });
    s.approvals.filter(a => a.kind === 'message').forEach(a => dots.push({ agent: 'chaser', id: 'm' + a.id, result: a.status === 'replied' ? 'ok' : a.status === 'sent' ? 'ok' : a.status === 'failed' ? 'bad' : 'ink', label: a.title + ': ' + a.status, meta: { kind: 'msg', ap: a, label: 'to ' + (this.supplierName(a.supplier_id) || 'supplier').replace(/ Sdn Bhd| Enterprise/, '') } }));
    LIVE_FILES.forEach(f => { if (this.fileReady(f.id)) dots.push({ agent: 'pack', id: f.id, result: 'ok', label: f.name + ': ready', meta: { kind: 'file', file: f, label: f.name.split('_')[0] + ' ' + f.name.split('_')[1].replace(/\.\w+$|\/$/g, '').toLowerCase() } }); });
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
    const problems = s.overview.problems.length + s.site.zones.filter(z => z.status === 'issue').length;
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
    if (t) { t.children[1].textContent = r.ingredients_covered + '/' + r.ingredients_total + ' ingredients covered'; t.children[2].textContent = r.zones_clear + '/5 zones clear · ' + r.documents_approved + '/3 documents approved'; }
    this.pkHeadScore.textContent = String(s.pack.items_ready);
    const total = s.tasks.length, doneN = s.tasks.filter(x => x.status === 'done').length;
    this.runBar.style.width = (total ? Math.round(doneN / total * 100) : 0) + '%';
    if (this.runTask) {
      const t0 = new Date(this.runTask.created_at), secs = Math.max(0, Math.round((Date.now() - t0) / 1000));
      const busy = s.agents.agents.some(a => a.state === 'working');
      this.ranFor.innerHTML = icon('clock') + (busy ? 'Running for ' : 'Started ') + (busy ? Math.floor(secs / 60) + 'm ' + String(secs % 60).padStart(2, '0') + 's' : liveTime(this.runTask.created_at)) + ', live run';
    } else this.ranFor.innerHTML = icon('clock') + 'Not started';
    this.refreshState();
  }
  refreshState() {
    if (this.tabBtns) { this.tabBtns.input.dataset.done = String(!!this.started); this.tabBtns.agents.dataset.done = String(!!this.snap?.overview.latest_pack); this.tabBtns.pack.dataset.done = String(!!this.snap?.overview.latest_pack); }
    if (this.replaying) return this.setStateChip('running', 'Replaying ' + this.speed + '×');
    if (!this.started) return this.setStateChip('ready', 'Not started');
    const s = this.snap;
    const busy = s && s.agents.agents.filter(a => a.state === 'working').length;
    const needs = s ? s.feed.needs_you.length : 0;
    this.pkHeadState.textContent = s && s.overview.latest_pack ? 'Ready for your review' : this.filesReady ? this.filesReady + ' of 6 files ready' : 'Not built yet';
    this.pkHeadState.dataset.state = s && s.overview.latest_pack ? 'complete' : this.filesReady ? 'running' : 'ready';
    if (busy) return this.setStateChip('running', busy + ' agent' + (busy > 1 ? 's' : '') + ' working');
    if (needs) return this.setStateChip('waiting', needs + ' need' + (needs > 1 ? '' : 's') + ' you');
    this.setStateChip('complete', 'Live · all quiet');
  }

  /* ---------- the run: start, plan, approvals ---------- */
  start() {
    const q = this.inPrompt.value.trim();
    if (!q) return;
    const s = this.snap;
    if (!s || !s.files.length) { this.toast('Add your files first, or load the sample case.'); return; }
    this.startBtn.disabled = true;
    livePost('/business/' + LIVE_BIZ + '/runs', { mode: 'prepare', instruction: q })
      .then(() => { this.started = true; this.caseText.textContent = q; this.setTab('agents'); this.toast('The Coordinator has your instruction.'); this.refreshSoon(); })
      .catch(err => { this.startBtn.disabled = false; this.toast(err.message); });
  }
  focusApprovals() {
    this.setTab('agents');
    const first = this.apSlot.querySelector('.ap:not(.is-done)');
    if (first) first.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'nearest' });
  }
  syncApprovals() {
    const s = this.snap; if (!s) return;
    const order = { plan: 0, message: 1, question: 2, document: 3 };
    const needs = s.feed.needs_you.filter(n => n.type === 'approval' || n.type === 'failed_message')
      .sort((a, b) => (order[a.kind] ?? 9) - (order[b.kind] ?? 9) || a.id - b.id);
    this.apCards = this.apCards || {};
    const keep = new Set(needs.map(n => n.type + n.id));
    Object.entries(this.apCards).forEach(([k, el]) => { if (!keep.has(k) && !el.classList.contains('is-done')) el.remove(); if (!keep.has(k)) delete this.apCards[k]; });
    needs.forEach(n => {
      const k = n.type + n.id;
      if (!this.apCards[k]) {
        const card = this.liveCard(n);
        this.apCards[k] = card;
        this.apSlot.append(card);
        if (this.ready && !reduced()) card.animate([{ opacity: 0, transform: 'translateY(-8px)', filter: 'blur(6px)' }, { opacity: 1, transform: 'none', filter: 'none' }], { duration: 480, easing: 'cubic-bezier(.2,.8,.2,1)' });
      }
    });
    const top = needs[0];
    this.gBanner.hidden = !top;
    if (top) {
      const t = this.gBanner.querySelector('.gb-txt b');
      t.textContent = top.kind === 'plan' ? 'The Coordinator’s plan' : top.kind === 'message' ? 'Message to ' + (top.supplier_name || 'a supplier') : top.kind === 'question' ? top.title : top.title;
      this.gWait.textContent = liveTime(top.created_at).slice(0, 5);
      this.gBanner.querySelector('.gb-ico').innerHTML = icon(top.kind === 'message' ? 'send' : top.kind === 'plan' ? 'hub' : top.kind === 'question' ? 'hand' : 'doc');
      const go = this.gBanner.querySelector('.gb-go');
      go.hidden = top.kind === 'question';
      go.onclick = () => this.approveItem(top);
      this.gBanner.querySelector('.gb-ghost').onclick = () => { this.select(AG[top.requested_by] || 'coord', true); this.focusApprovals(); };
    }
  }
  liveCard(n) {
    const card = h('section', { class: 'ap', 'aria-label': n.title });
    const who = AGENTS[AG[n.requested_by]] || AGENTS.coord;
    const head = (title, ic) => h('div', { class: 'ap-h' }, h('span', { class: 'ap-ico', 'aria-hidden': 'true', html: icon(ic || 'hand') }),
      h('div', { class: 'ap-title' }, h('b', null, title), h('span', null, who.name + ', ' + liveTime(n.created_at))));
    const doneHead = text => { card.classList.add('is-done'); const ah = card.querySelector('.ap-h'); ah.innerHTML = ''; ah.append(h('span', { class: 'ap-ico ok', 'aria-hidden': 'true', html: icon('done') }), h('div', { class: 'ap-title' }, h('b', null, text), h('span', null, 'at ' + new Date().toTimeString().slice(0, 5)))); };
    card.markDone = doneHead;
    if (n.type === 'failed_message') {
      card.append(head('Could not send', 'alert'), h('p', { class: 'ap-why' }, n.send_error || 'The message did not go out.'),
        h('div', { class: 'ap-actions' }, h('button', { class: 'btn btn-ink', type: 'button', onclick: () => this.approveItem(n, card) }, 'Try again')));
    } else if (n.kind === 'plan') {
      let steps = []; try { steps = JSON.parse(n.payload || '[]'); } catch (_) { /* keep empty */ }
      card.append(head('Approve the plan', 'hub'), h('p', { class: 'ap-why' }, n.body_en || ''),
        h('ol', { class: 'plan-steps' }, ...steps.map(st => { const a = AGENTS[AG[st.assignee]]; return h('li', null, h('span', { class: 'lg-av', html: icon(a.icon) }), h('div', null, h('b', null, a.name), h('span', null, st.title))); })),
        h('div', { class: 'ap-actions' }, h('button', { class: 'btn btn-ink mb', type: 'button', onclick: () => this.approveItem(n, card) }, 'Approve the plan')));
    } else if (n.kind === 'message') {
      let lang = 'ms';
      const texts = { ms: n.body_ms || n.body_en || '', en: n.body_en || n.body_ms || '' };
      const bubbleText = h('span', { lang: 'ms' }, texts.ms);
      const langBtn = h('button', { class: 'msg-lang', type: 'button' }, 'Show in English');
      langBtn.addEventListener('click', () => { lang = lang === 'ms' ? 'en' : 'ms'; bubbleText.textContent = texts[lang]; bubbleText.setAttribute('lang', lang); langBtn.textContent = lang === 'ms' ? 'Show in English' : 'Show in Malay'; });
      const bubble = h('div', { class: 'bubble' }, bubbleText, h('div', { class: 'bubble-meta' }, h('span', null, 'Draft, not sent')));
      const draft = h('textarea', { class: 'draft', 'aria-label': 'Edit the message', hidden: true });
      const editBtn = h('button', { class: 'btn btn-line', type: 'button' }, 'Edit draft');
      editBtn.addEventListener('click', () => {
        if (draft.hidden) { draft.value = texts[lang]; draft.hidden = false; bubble.hidden = true; editBtn.textContent = 'Save draft'; draft.focus(); }
        else { texts[lang] = draft.value.trim() || texts[lang]; bubbleText.textContent = texts[lang]; draft.hidden = true; bubble.hidden = false; editBtn.textContent = 'Edit draft'; }
      });
      const sup = this.snap.suppliers.find(x => x.id === n.supplier_id) || {};
      const ing = this.snap.ingredients.find(i => i.id === n.ingredient_id);
      card.append(head('Needs your approval'),
        h('p', { class: 'ap-why' }, ing ? (ing.name + ': ' + (ST_TEXT[ing.status] || ing.status).toLowerCase() + '. This asks ' + (sup.name || 'the supplier') + ' for the certificate.') : n.title),
        h('div', { class: 'msg' },
          h('div', { class: 'msg-to' }, h('span', { class: 'msg-av', 'aria-hidden': 'true' }, initials(sup.contact_name || sup.name)), h('div', null, h('b', null, sup.contact_name || sup.name || 'Supplier'), h('span', null, (sup.name || '') + (sup.telegram_chat_id ? ', on Telegram' : ', on WhatsApp')))),
          bubble, draft, langBtn),
        h('div', { class: 'ap-actions' }, h('button', { class: 'btn btn-ink mb', type: 'button', onclick: () => { if (!draft.hidden) editBtn.click(); this.approveItem(n, card, { body_ms: texts.ms, body_en: texts.en }); } }, 'Approve and send'), editBtn));
    } else if (n.kind === 'question') {
      const fileIn = h('input', { type: 'file', accept: 'image/*,application/pdf,.xlsx,.docx', class: 'sr-only' });
      const picked = h('span', { class: 'fn' }, 'Attach a file');
      fileIn.addEventListener('change', () => { picked.textContent = fileIn.files[0] ? fileIn.files[0].name : 'Attach a file'; });
      const note = h('textarea', { class: 'draft', rows: 2, placeholder: 'Optional note', 'aria-label': 'Your answer' });
      card.append(head('Needs your answer', 'hand'),
        h('div', { class: 'ap-q' }, n.file_id ? h('img', { class: 'ap-thumb', src: fileUrl(n.file_id), alt: 'The file in question', onclick: () => this.openFileView(n.file_id, n.title) }) : null, h('p', { class: 'ap-why' }, h('b', null, n.title), h('br'), n.body_en || '')),
        h('label', { class: 'dropbar ap-drop' }, h('span', { class: 'dropbar-ico', html: icon('upload') }), picked, fileIn), note,
        h('div', { class: 'ap-actions' }, h('button', { class: 'btn btn-ink mb', type: 'button', onclick: () => {
          const fd = new FormData(); if (fileIn.files[0]) fd.append('files', fileIn.files[0]); if (note.value.trim()) fd.append('text', note.value.trim());
          if (!fileIn.files[0] && !note.value.trim()) { this.toast('Attach a file or write an answer.'); return; }
          liveApi('/approvals/' + n.id + '/answer', { method: 'POST', body: fd }).then(() => { doneHead('You answered'); this.toast('Sent back to the ' + who.name + '.'); this.refreshSoon(); }).catch(err => this.toast(err.message));
        } }, 'Send to the ' + who.name)));
    } else {
      const doc = this.snap.documents.find(d => d.id === n.document_id);
      card.append(head('Ready for your review', 'doc'), h('p', { class: 'ap-why' }, (doc ? doc.title + ', version ' + doc.version : n.title) + '. Passed the Auditor’s checklist.'),
        h('div', { class: 'ap-actions' },
          h('button', { class: 'btn btn-ink', type: 'button', onclick: () => this.approveItem(n, card) }, 'Approve'),
          h('button', { class: 'btn btn-line', type: 'button', onclick: () => { this.pkFile = doc && doc.doc_type === 'halal_policy' ? 'f3' : 'f4'; this.pkSub = doc && doc.doc_type === 'traceability' ? 1 : 0; this.setTab('pack'); } }, 'Read'),
          h('button', { class: 'btn btn-line', type: 'button', onclick: () => {
            if (card.querySelector('.ap-back')) return;   /* an inline box, never a browser dialog */
            const box = h('textarea', { class: 'draft ap-back', rows: 2, placeholder: 'What should change?' });
            const send = h('button', { class: 'btn btn-line', type: 'button', onclick: () => livePost('/approvals/' + n.id + '/reject', { comment: box.value }).then(() => { doneHead('Sent back with your comment'); this.refreshSoon(); }).catch(err => this.toast(err.message)) }, 'Send back');
            card.append(box, h('div', { class: 'ap-actions' }, send));
          } }, 'Ask for changes')));
    }
    return card;
  }
  approveItem(n, card, edits) {
    card = card || this.apCards[n.type + n.id];
    const btn = card && card.querySelector('.btn-ink');
    if (btn) { btn.disabled = true; if (!reduced()) btn.classList.add('press'); }
    livePost('/approvals/' + n.id + '/approve', edits || {}).then(r => {
      const msg = n.kind === 'plan' ? 'You approved the plan' : n.kind === 'message' ? (r.status === 'sent' ? 'You approved the message' : 'Could not send') : 'You approved the document';
      if (card && card.markDone) card.markDone(msg);
      this.toast(n.kind === 'plan' ? 'Plan approved. The agents are starting.' : n.kind === 'message' ? (r.channel === 'manual' ? 'Approved. Messaging is in manual mode, so send it yourself.' : r.status === 'sent' ? 'Approved. Sent via ' + r.channel + '.' : 'Could not send: ' + (r.send_error || r.status)) : 'Approved.');
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
    this.inFilesHead = $$('.in-sec .mono-l.ok', p)[0];
    this.inFilesChip = $('.cmp-chip.ok', p);
    const drop = $('.dropbar', p), fileIn = $('input[type=file]', drop);
    const upload = files => {
      const fd = new FormData(); Array.from(files || []).forEach(f => fd.append('files', f));
      if (!fd.has('files')) return;
      liveApi('/business/' + LIVE_BIZ + '/files', { method: 'POST', body: fd }).then(r => { this.toast(r.files.length + ' file(s) added. The Coordinator will sort them.'); this.refreshSoon(); }).catch(err => this.toast(err.message));
    };
    void fileIn;
    const d2 = drop.cloneNode(true); drop.replaceWith(d2);   /* the clone drops the template's 'list only' handlers */
    const fi2 = $('input[type=file]', d2); fi2.addEventListener('change', () => { upload(fi2.files); fi2.value = ''; });
    d2.addEventListener('dragover', e => { e.preventDefault(); d2.classList.add('over'); });
    d2.addEventListener('dragleave', () => d2.classList.remove('over'));
    d2.addEventListener('drop', e => { e.preventDefault(); d2.classList.remove('over'); upload(e.dataTransfer.files); });
    this.sampleBtn = h('button', { class: 'btn btn-line btn-sm in-sample', type: 'button', onclick: () => livePost('/demo/load-sample').then(r => { this.toast(r.files + ' sample files loaded.'); this.refreshSoon(); }).catch(err => this.toast(err.message)) }, icon('plus'), 'Load the sample case');
    d2.after(this.sampleBtn);
    $('.in-note', p)?.remove();
    $('.own-list', p)?.remove();
    this.inProducts = $$('.cmp-in', p)[1];
    if (this.inProducts) this.inProducts.value = '2 sambal products';
    $$('.sugg-b', p).forEach((b, i) => { const t = ['Prepare Mak Teh Sambal’s halal certification application.', 'Check every supplier certificate before I renew.', 'Check my premises photos for halal risks.'][i]; if (t) { b.textContent = t; b.onclick = () => { this.inPrompt.value = t; this.inPrompt.focus(); }; } });
    const steps = $$('.hsteps li > span:last-child', p); if (steps[2]) steps[2].textContent = 'Three agents in parallel';
  }
  trayOf(f) {
    if (f.category) return f.category;
    const n = f.filename.toLowerCase();
    if (/photo|zone|site|\.(jpe?g|heic)$/.test(n) && !/cert/.test(n)) return 'site';
    if (/recipe|resipi|label|product|ingredient/.test(n)) return 'products';
    if (/cert|sijil|invoice|invois|supplier|pembekal/.test(n)) return 'suppliers';
    return 'company';
  }
  syncInput() {
    const s = this.snap; if (!s || !this.inTiles) return;
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
        h('span', { class: 'tile-foot' }, h('span', { class: 'tile-n tnum' }, String(n)), h('span', null, n === 1 ? 'file' : 'files'),
          h('span', { class: 'tile-ok', html: n ? icon('done') + (fs.every(f => f.category) ? 'Sorted' : 'In the pile') : '' })));
      t.addEventListener('click', () => {
        if (this.openTile === key) { this.openTile = null; list.hidden = true; this.syncInput(); return; }
        this.openTile = key; this.syncInput();
      });
      this.inTiles.append(t);
      if (open === key) {
        list.innerHTML = '';
        list.append(h('div', { class: 'tile-list-h' }, h('span', { class: 'mono-l' }, title), h('span', { class: 'mono-l ok' }, n + (n === 1 ? ' file' : ' files'))),
          h('ul', null, ...fs.map(f => h('li', null, h('span', { html: icon(/\.xlsx?$/i.test(f.filename) ? 'sheet' : key === 'site' ? 'eye' : 'doc') }),
            h('a', { class: 'fn', href: fileUrl(f.id), target: '_blank', rel: 'noopener' }, f.filename)))));
        list.hidden = false;
      }
    });
    if (!open) list.hidden = true;
    const total = s.files.length;
    if (this.inFilesHead) this.inFilesHead.textContent = total ? total + ' files loaded' : 'No files yet';
    if (this.inFilesChip) this.inFilesChip.innerHTML = icon('done') + (total ? total + ' files attached' : 'No files yet');
    this.inFilesChip?.classList.toggle('ok', total > 0);
    this.sampleBtn.hidden = total > 0;
    this.startBtn.disabled = !!this.started;
    this.startBtn.querySelector('span').textContent = this.started ? 'Run started' : 'Start the run';
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
          h('span', { class: 'mono-l sec' }, 'Certificate'),
          grid([['Brand', i.brand || '—'], ['Certificate no.', i.cert_number || '—'], ['Issued by', i.status === 'unclear' ? 'Unreadable' : (i.issuer || '—'), true], ['Used in', (i.products || []).join(', ') || '—', true], ['Checked by', 'Certificate Checker'], ['Tool', 'record_certificate'], ['File', certFile ? certFile.filename : 'None on file', true]]));
        if (ST_RESULT[i.status] !== 'ok' || i.cert_file_id) html.push(h('button', { class: 'btn btn-ink btn-sm dbtn', type: 'button', onclick: () => this.openEvidence('ing:' + i.id) }, icon('eye'), 'See the evidence'));
      } else if (m.kind === 'zone') {
        const z = s.site.zones.find(x => x.zone === m.zone.zone) || m.zone;
        html.push(head('eye', ZONE_LABEL[z.zone], 'Site photo, checked by the On-site Inspector'), boxes(['Result', bad ? 'Possible issue' : 'Clear', bad ? 'bad' : 'ok'], ['Findings', String(z.findings.length)]),
          grid(z.findings.map(f => [f.severity === 'ok' ? 'Checked' : 'Flagged', f.title + (f.detail ? '. ' + f.detail : ''), true]).concat([['Tool', 'save_site_finding']])),
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
      const prog = { checker: [checked, s.ingredients.length], inspector: [s.site.zones.filter(z => z.status !== 'unchecked').length, 5], writer: [s.documents.length, 3], auditor: [s.documents.filter(d => d.status !== 'draft').length, 3], pack: [this.filesReady, 6] }[id] || (mine.length ? [mine.filter(t => t.status === 'done').length, mine.length] : null);
      const firstEv = this.log.find(e => e.agent === id);
      const recent = this.log.filter(e => e.agent === id).slice(-3).reverse();
      html = [
        h('div', { class: 'dhead' }, h('span', { class: 'dico' + (a.human ? ' human' : ''), html: a.human ? '<b>MT</b>' : icon(a.icon) }),
          h('div', null, h('b', null, a.human ? 'Mak Teh (you)' : a.name), h('span', { class: 'dsub mono' }, a.human ? 'Owner, approves the plan and messages' : 'workbuddy/sub-agent/' + (AGENT_SLUG[id] || id)))),
        boxes(['Status', STATE_LABEL[st], st === 'waiting' ? 'warn' : st === 'flag' ? 'bad' : st === 'done' ? 'ok' : st === 'working' ? 'ink' : ''], ['Progress', prog ? prog[0] + ' / ' + prog[1] : '—']),
        h('p', { class: 'dnow' }, this.status[id] || ''),
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
  openFileView(fid, title) {
    this.drawerTitle.textContent = title || 'File';
    this.drawerBody.innerHTML = '';
    this.drawerBody.append(h('div', { class: 'evd' }, h('div', { class: 'evd-src' }, h('img', { class: 'evd-img', src: fileUrl(fid), alt: title || '' }))));
    this.drawer.classList.add('open');
  }
  openEvidence(key) {
    const s = this.snap; if (!s || !key) return;
    const [kind, ref] = key.split(':');
    const wrap = h('div', { class: 'evd' });
    const rows = h('dl', { class: 'evd-rows' });
    const row = (k, v) => rows.append(h('div', { class: 'evd-row' }, h('dt', null, k), h('dd', { html: v })));
    let title = 'Evidence', fileId = null, caption = '';
    if (kind === 'ing') {
      const i = s.ingredients.find(x => String(x.id) === ref); if (!i) return;
      title = i.source === 'found_on_site' ? 'Undeclared item: ' + (i.brand || i.name) : i.name + ': ' + (ST_TEXT[i.status] || i.status).toLowerCase();
      if (i.source === 'found_on_site') {
        const photo = s.files.find(f => f.zone === 'store'); fileId = photo && photo.id; caption = photo ? photo.filename + ', store shelf' : '';
        row('Found by', 'On-site Inspector <span class="tool">compare_store_brands</span>, then Certificate Checker <span class="tool">check_brand</span>');
        row('Checked', 'Every brand on the store shelf against your declared ingredient list and the certificates on file');
        row('Read on the label', '<span class="mono">' + esc(i.brand || '') + '</span>');
        row('Result', '<strong>Not on your ingredient list, and no certificate on file</strong>');
        row('Next step', 'Remove it from the store, or declare it with its supplier and a valid certificate.');
      } else {
        const inv = i.status === 'missing' ? s.files.find(f => /invoice|invois/i.test(f.filename) && (i.supplier_name || '').split(' ').some(w => w.length > 3 && f.filename.toLowerCase().includes(w.toLowerCase()))) : null;
        fileId = i.cert_file_id || (inv && inv.id);
        const f = fileId && s.files.find(x => x.id === fileId); caption = f ? f.filename : 'No file on record';
        row('Found by', 'Certificate Checker <span class="tool">record_certificate</span>');
        row('Checked', i.status === 'missing' ? 'Every certificate in the Suppliers tray, for ' + esc(i.name) + ' (' + esc(i.brand || '') + ')' : i.status === 'unclear' ? 'Image sharpness, then the issuer, number and expiry date on the scan' : 'Issuer against JAKIM’s recognised list, and the expiry date against today, ' + niceDate(s.overview.today));
        row('Result', '<strong>' + esc({ missing: 'No certificate on file' + (inv ? '; the invoice proves ' + esc(i.supplier_name) + ' supplies it' : ''), unclear: 'The scan is too blurred to read. Nothing on it was guessed.', expired: 'Expired on ' + niceDate(i.expiry_date), unrecognised_issuer: esc(i.issuer) + ' is not on the recognised list', valid: 'Valid until ' + niceDate(i.expiry_date) + (i.issuer ? ', issued by ' + i.issuer : ''), expiring: 'Expires on ' + niceDate(i.expiry_date) }[i.status] || i.status) + '</strong>');
        row('Next step', esc({ missing: 'Supplier Chaser drafted a message to ' + (i.supplier_name || 'the supplier') + '. It waits for your approval.', unclear: 'Upload a clearer copy or photo of the certificate.', expired: 'Ask the supplier for the renewed certificate.', unrecognised_issuer: 'Ask for a certificate from a recognised body, or switch supplier.', valid: 'Nothing to do.', expiring: 'Renewal Watch will ask the supplier before it expires.' }[i.status] || ''));
      }
    } else if (kind === 'zone') {
      const z = s.site.zones.find(x => x.zone === ref); if (!z) return;
      const photo = s.files.find(f => f.zone === ref); fileId = photo && photo.id; caption = photo ? photo.filename : 'No photo';
      title = ZONE_LABEL[ref] + (z.status === 'issue' ? ': possible issue' : ': checked');
      row('Found by', 'On-site Inspector <span class="tool">save_site_finding</span>');
      row('Checked', 'Brands against the declared list; chemicals near food, pests, uncovered waste, cleanliness');
      z.findings.forEach(f => row(f.severity === 'ok' ? 'Seen' : 'Flagged', '<strong>' + esc(f.title) + '</strong>' + (f.detail ? '<br>' + esc(f.detail) : '')));
      row('Next step', z.status === 'issue' ? 'Fix it, or explain it to the Inspector. It stays open in the Premises Fix Tracker.' : 'Nothing to do.');
    }
    const src = h('div', { class: 'evd-src' }, fileId ? h('img', { class: 'evd-img', src: fileUrl(fileId), alt: caption }) : h('p', { class: 'evd-none' }, 'No file on record'));
    wrap.append(src, h('p', { class: 'evd-cap', html: icon('eye') + '<span>' + esc(caption) + '</span>' }), rows);
    this.drawerTitle.textContent = title;
    this.drawerBody.innerHTML = '';
    this.drawerBody.append(wrap);
    this.drawer.classList.add('open');
    this.lastFocus = document.activeElement;
    setTimeout(() => this.drawerClose.focus({ preventScroll: true }), 60);
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
      this.pkList, this.pkTodoBox, this.pkDownload,
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
    LIVE_FILES.forEach(f => { const b = this.fileBtns[f.id], ok = this.fileReady(f.id); b.dataset.state = ok ? 'ready' : 'pending'; b.querySelector('.pk-st').textContent = ok ? 'Ready' : 'Waiting'; });
    const pk = this.snap.pack;
    this.pkHeadTotal.textContent = ' of ' + pk.items_total + ' items ready';
    this.pkTodo.innerHTML = '';
    pk.missing.forEach(m => {
      const ev = m.key.startsWith('cert:') ? 'ing:' + m.key.split(':')[1] : m.key.startsWith('zone:') ? m.key : null;
      this.pkTodo.append(h('li', null, h('label', null, h('input', { type: 'checkbox' }), h('span', null, m.label + ': ' + (m.reason || 'missing'))),
        ev ? h('button', { class: 'fb-ev', type: 'button', onclick: () => this.openEvidence(ev) }, 'Evidence') : null));
    });
    this.pkTodoBox.hidden = !this.snap.overview.latest_pack || !pk.missing.length;
    this.pkDownload.hidden = !this.snap.overview.latest_pack;
  }
  showFile(id) { this.pkFile = id; this.pkSub = 0; this.renderPack(); }
  renderPack() {
    if (!this.pkView) return;
    const s = this.snap;
    this.pkLock.hidden = !!this.started;
    Object.entries(this.fileBtns).forEach(([fid, b]) => b.setAttribute('aria-selected', fid === this.pkFile ? 'true' : 'false'));
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
      body = [tool([h('b', null, 'Tracker')], [pill('5 zones'), pill(s.site.zones.filter(z => z.status === 'issue').length + ' open')]),
        sheet(['Zone', 'What the photo shows', 'Result', 'Fix', 'Owner'], ['18%', '40%', '10%', '22%', '10%'], rows, ['Tracker', 'Photos']),
        photo ? h('figure', { class: 'vw-fig' }, h('img', { class: 'evd-img', src: fileUrl(photo.id), alt: 'Store photo' }), h('figcaption', null, 'Photo attached to the store row: ' + photo.filename)) : null];
    } else if (f.id === 'f1') {
      const pk = s.pack, r = s.overview.readiness;
      const page = h('article', { class: 'pg' }, letter('Ref. MTS/HR/2026/01'),
        h('h1', null, 'Halal certification readiness report'),
        h('dl', { class: 'pg-meta' }, ...[['Prepared', DATE + (s.overview.latest_pack ? ', ' + liveTime(s.overview.latest_pack.created_at).slice(0, 5) : '')], ['Prepared by', 'HalalReady, Coordinator agent'], ['For', 'Mak Teh, Managing Director']].map(([k, x]) => h('div', null, h('dt', null, k), h('dd', null, x)))),
        h('h2', null, '1. Summary'),
        h('p', null, s.overview.status_sentence + ' Readiness: ' + r.score + '% (' + r.done + ' of ' + r.total + ' items).'),
        h('h2', null, '2. Requirements by area'),
        h('table', { class: 'pg-t' }, h('thead', null, h('tr', null, h('th', null, 'Area'), h('th', null, 'Ready'), h('th', null, 'Open items'))),
          h('tbody', null, ...pk.sections.map(g => h('tr', null, h('td', null, g.title.replace(/^\d+\.\s*/, '')), h('td', null, g.items.filter(i => i.status === 'ready').length + ' / ' + g.items.length),
            h('td', null, g.items.filter(i => i.status !== 'ready').map(i => i.label).join('; ') || '—'))))),
        h('h2', null, '3. Actions before submission'),
        h('ol', null, ...(pk.missing.length ? pk.missing.map(m => h('li', null, m.label + ': ' + (m.reason || 'missing'))) : [h('li', null, 'Nothing open.')])),
        h('footer', { class: 'pg-foot' }, h('span', null, 'Prepared with HalalReady. Certification decisions rest with JAKIM.'), h('span', null, 'Page 1 of 1')));
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

  /* ---------- demo controls (stage helpers) ---------- */
  build() {
    super.build();
    const menu = h('div', { class: 'demo-menu' });
    const list = h('div', { class: 'demo-list', role: 'menu', hidden: true });
    const btn = h('button', { class: 'btn btn-line btn-sm', type: 'button', 'aria-haspopup': 'true', onclick: e => { e.stopPropagation(); list.hidden = !list.hidden; } }, 'Demo');
    const item = (label, sub, fn) => h('button', { type: 'button', role: 'menuitem', onclick: () => { list.hidden = true; fn(); } }, h('b', null, label), h('span', null, sub));
    const call = (path, ok, after) => livePost(path).then(r => { this.toast(ok(r)); after && after(); this.refreshSoon(); }).catch(err => this.toast(err.message));
    const clock = (today, ok) => liveApi('/clock', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ today }) }).then(r => { this.toast(ok(r)); this.refreshSoon(); }).catch(err => this.toast(err.message));
    list.append(
      item('Reset the demo', 'Empty case, date 15 Oct 2026', () => call('/demo/reset', () => 'Demo reset.', () => setTimeout(() => location.reload(), 400))),
      item('Load the sample case', '15 files, unsorted', () => call('/demo/load-sample', r => r.files + ' sample files loaded.')),
      item('Supplier replies (fallback)', 'Minyak Murni sends the oil certificate', () => call('/demo/supplier-reply', () => 'Minyak Murni replied with the certificate.')),
      item('Owner sends clearer copy', 'Ikan bilis certificate, readable', () => call('/demo/owner-copy', () => 'Clearer copy sent to the Certificate Checker.')),
      item('Jump 4 months ahead', '15 Feb 2027, wakes Renewal Watch', () => clock('2027-02-15', r => 'Date is now ' + niceDate(r.today) + '. ' + r.triggered_tasks.length + ' renewal task(s).')),
      item('Back to the demo date', '15 Oct 2026', () => clock('2026-10-15', () => 'Back to 15 Oct 2026.')));
    document.addEventListener('click', e => { if (!menu.contains(e.target)) list.hidden = true; });
    menu.append(btn, list);
    const end = $('.dt-end', this.root);
    end.insertBefore(menu, end.children[1] || null);
  }
}
