/* The relations page: three lenses (map, docket, board) over one nodes-and-links
   document. Everything shown comes from that document, already sanitised where it was
   made; this script only ever sets textContent, never markup. No request goes anywhere. */
(function () {
  'use strict';
  var DOC = JSON.parse(document.getElementById('relations-data').textContent);
  var CFG = JSON.parse(document.getElementById('relations-config').textContent);
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k];
      else if (k === 'on') Object.keys(attrs.on).forEach(function (ev) { e.addEventListener(ev, attrs.on[ev]); });
      else if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) e.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (kid) { if (kid) e.appendChild(typeof kid === 'string' ? document.createTextNode(kid) : kid); });
    return e;
  }

  /* ---------- the document, indexed ---------- */
  var N = new Map(DOC.nodes.map(function (n) { return [n.id, n]; }));
  var OUT = {}, IN = {};
  DOC.links.forEach(function (l) {
    ((OUT[l.type] = OUT[l.type] || {})[l.source] = (OUT[l.type] || {})[l.source] || []).push(l);
    ((IN[l.type] = IN[l.type] || {})[l.target] = (IN[l.type] || {})[l.target] || []).push(l);
  });
  function outs(type, id) { return ((OUT[type] || {})[id] || []); }
  function ins(type, id) { return ((IN[type] || {})[id] || []); }
  var LINK_TYPES = DOC.graph.types.link;
  var DERIVED = Object.keys(LINK_TYPES).filter(function (t) { return LINK_TYPES[t].how === 'derived' && t !== 'works_on' && t !== 'refers_to_repo'; });
  var SESSIONS = DOC.nodes.filter(function (n) { return n.type === 'session'; });
  var OWNER = 'owner:me';
  var CLASSES = ['needs', 'working', 'closable', 'quiet', 'gone'];
  var CLASS_WORDS = { needs: 'need you', working: 'working', closable: 'can be closed', quiet: 'quiet', gone: 'exited' };
  var WHY_WORDS = { decision: 'Decisions', action: 'Errands', question: 'Questions', '': 'Waiting' };
  function cls(n) {
    var d = n.data;
    if (d.status === 'exited') return 'gone';
    if (d.group === 'needs_you' || d.status === 'waiting') return 'needs';
    if (d.group === 'working' || d.status === 'busy' || d.status === 'shell') return 'working';
    if (d.group === 'safe_to_close') return 'closable';
    return 'quiet';
  }
  var PLACE = new Map();
  function placeOf(id) {
    if (PLACE.has(id)) return PLACE.get(id).at;
    var found = { at: '', how: 'recorded' }, repo = outs('works_on', id)[0];
    if (repo) found.at = repo.target;
    else {
      var about = outs('refers_to_repo', id).slice().sort(function (a, b) { return (b.data.paths || 1) - (a.data.paths || 1); })[0];
      var folder = outs('works_in', id)[0];
      if (about) found = { at: about.target, how: 'inferred' };
      else if (folder) found.at = folder.target;
    }
    PLACE.set(id, found);
    return found.at;
  }
  function placeHow(id) { placeOf(id); return PLACE.get(id).how; }
  function label(id) { var n = N.get(id); return n ? (n.data.label || id) : id; }
  function byInterest(a, b) { return (b.data.interest - a.data.interest) || (a.data.label < b.data.label ? -1 : 1); }
  var BY_CLASS = {};
  CLASSES.forEach(function (c) { BY_CLASS[c] = []; });
  SESSIONS.forEach(function (n) { BY_CLASS[cls(n)].push(n); });
  CLASSES.forEach(function (c) { BY_CLASS[c].sort(byInterest); });

  /* ---------- state, kept in the address so a reload or a link reopens the same view ---------- */
  var SHOW = { key: 0.7, more: 0.5, all: 0 };
  var VIEWS = [
    ['all', 'Overview', 'Every live session, boxed by what it works on. Amber needs you, teal is working.'],
    ['needs', 'Needs you', 'What waits on you and what is moving: you in the middle, each session beside the place it works in.'],
    ['places', 'Places', 'Which sessions share a repository or folder: one box per place.'],
    ['family', 'Family', 'Who started whom: each dispatcher and the sessions it spawned.'],
    ['talk', 'Talk', 'Who messaged whom, and what you asked of a session.'],
    ['free', 'Free', 'Everything shown, pulled together by its links: what clusters around what.']
  ];
  var S = { lens: CFG.entry === 'docket' || CFG.entry === 'board' ? CFG.entry : 'map', view: 'all', show: 'key', focus: '', sel: '', on: [], refs: false };
  var expanded = new Set();
  function readHash() {
    new URLSearchParams(location.hash.slice(1)).forEach(function (v, k) {
      if (k === 'on') S.on = v ? v.split(',') : [];
      else if (k === 'refs') S.refs = v === '1';
      else if (k in S) S[k] = v;
    });
  }
  function writeHash(push) {
    var p = new URLSearchParams();
    ['lens', 'view', 'show', 'focus', 'sel'].forEach(function (k) { if (S[k]) p.set(k, S[k]); });
    if (S.on.length) p.set('on', S.on.join(','));
    if (S.refs) p.set('refs', '1');
    var url = '#' + p.toString();
    if (url === location.hash) return;
    try { history[push ? 'pushState' : 'replaceState'](null, '', url); } catch (e) { /* a sandboxed frame: the view still works */ }
  }
  window.addEventListener('popstate', function () { S.sel = ''; S.focus = ''; readHash(); sheetPushed = false; render(); if (S.sel) { sheetFor(S.sel); } else hideSheet(); });

  /* ---------- times: always the source's, with its age beside it ---------- */
  var AS_OF = new Date(DOC.graph.as_of);
  function two(x) { return (x < 10 ? '0' : '') + x; }
  function clock(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return '';
    var t = two(d.getHours()) + ':' + two(d.getMinutes());
    return d.toDateString() === new Date().toDateString() ? t : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + t;
  }
  function age(iso, from) {
    var d = new Date(iso);
    if (isNaN(d)) return '';
    var m = Math.max(0, Math.round(((from || new Date()) - d) / 60000));
    return m < 1 ? 'just now' : m < 60 ? m + ' min ago' : m < 1440 ? Math.round(m / 60) + ' h ago' : Math.round(m / 1440) + ' d ago';
  }
  function tickAge() {
    var m = Math.round((new Date() - AS_OF) / 60000);
    var chip = $('asof');
    chip.textContent = 'as of ' + clock(DOC.graph.as_of) + (m >= 1 ? ', ' + age(DOC.graph.as_of).replace(' min', 'm').replace(' h', 'h').replace(' d', 'd') : '');
    var old = m >= (CFG.stale_minutes || 10);
    chip.classList.toggle('stale', old);
    $('stale').hidden = !old;
    $('stale-text').textContent = 'This snapshot is ' + age(DOC.graph.as_of).replace(' ago', '') + ' old.';
  }

  /* ---------- the sentence every lens starts with ---------- */
  function sentence() {
    var box = $('sentence');
    box.textContent = '';
    var why = { decision: 0, action: 0, question: 0 };
    BY_CLASS.needs.forEach(function (n) { why[n.data.why in why ? n.data.why : 'question'] += 1; });
    var mine = [[why.decision, 'decision', 'decisions'], [why.action, 'errand', 'errands']].filter(function (p) { return p[0]; })
      .map(function (p) { return p[0] + ' ' + (p[0] === 1 ? p[1] : p[2]); });
    var lead = mine.length ? mine.join(' and ') + (why.decision + why.action === 1 ? ' waits on you' : ' wait on you') : (why.question ? 'No decision or errand waits on you' : 'Nothing waits on you');
    box.appendChild(el('b', { text: lead + (why.question ? ', and ' + why.question + (why.question === 1 ? ' question.' : ' questions.') : '.') }));
    box.appendChild(document.createTextNode(' ' + BY_CLASS.working.length + ' working, ' + BY_CLASS.closable.length + ' can be closed, ' + BY_CLASS.quiet.length + ' quiet.'));
  }
  function linked(text) { /* a line of text, its owner/repo#N references as links */
    var out = document.createDocumentFragment(), re = /\b([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)#(\d+)\b/g, last = 0, m;
    while ((m = re.exec(text))) {
      out.appendChild(document.createTextNode(text.slice(last, m.index)));
      out.appendChild(el('a', { href: 'https://github.com/' + m[1] + '/' + m[2] + '/issues/' + m[3], target: '_blank', rel: 'noopener noreferrer', text: m[0] }));
      last = m.index + m[0].length;
    }
    out.appendChild(document.createTextNode(text.slice(last)));
    return out;
  }
  function plainAsk(n) { return String(n.data.ask || n.data.state || n.data.waiting_for || '').replace(/^[\s\-–•*]+/, '').replace(/^owner( items?)?:\s*/i, ''); }

  /* ---------- the details sheet: one node, what it says, what it is linked to ---------- */
  function press(button) { button.setAttribute('data-pressed', ''); setTimeout(function () { button.removeAttribute('data-pressed'); }, 160); }
  function chip(text, kind) { return el('span', { class: 'chip ' + (kind || ''), text: text }); }
  function nodeRow(id, note) {
    var n = N.get(id);
    var kind = n.type === 'session' ? cls(n) : n.type;
    return el('button', { class: 'rel-row', type: 'button', on: { click: function () { select(id, true); } } }, [
      el('span', { class: 'dot ' + kind }), el('span', { class: 'rel-name', text: label(id) }), note ? el('span', { class: 'rel-note', text: note }) : null]);
  }
  function section(title, ids, noteOf, limit) {
    if (!ids.length) return null;
    var box = el('div', { class: 'rel-sec' }, [el('h4', { text: title + (ids.length > 1 ? ' (' + ids.length + ')' : '') })]);
    var cap = limit || 6;
    ids.slice(0, cap).forEach(function (id) { box.appendChild(nodeRow(id, noteOf ? noteOf(id) : '')); });
    if (ids.length > cap) {
      var rest = el('details', { class: 'more' }, [el('summary', { text: (ids.length - cap) + ' more' })]);
      ids.slice(cap).forEach(function (id) { rest.appendChild(nodeRow(id, noteOf ? noteOf(id) : '')); });
      box.appendChild(rest);
    }
    return box;
  }
  function uniq(list) { return Array.from(new Set(list)); }
  function sheetFor(id) {
    var body = $('sheet-body');
    body.textContent = '';
    if (id.indexOf('bundle:') === 0) { return bundleSheet(id, body); }
    var n = N.get(id);
    if (!n) return closeSheet();
    var d = n.data, kind = n.type === 'session' ? cls(n) : n.type;
    body.appendChild(el('div', { class: 'sheet-head' }, [el('span', { class: 'dot big ' + kind }), el('h3', { text: d.label || id }),
      chip(n.type === 'session' ? CLASS_WORDS[kind] : n.type, kind)]));
    var said = d.ask || d.state || d.waiting_for;
    if (said) {
      body.appendChild(el('p', { class: 'said' }, [d.said_at ? el('time', { text: clock(d.said_at) + ' · ' + age(d.said_at) + ' ' }) : null, linked(plainAsk(n))]));
    }
    var facts = [];
    if (n.type === 'session') { if (d.model) facts.push(d.model); if (d.status) facts.push(d.status + (d.since ? ' since ' + clock(d.since) : '')); }
    if (d.path) facts.push(d.path);
    if (d.state && n.type !== 'session') facts.push(d.state);
    if (facts.length) body.appendChild(el('p', { class: 'facts', text: facts.join(' · ') }));
    var acts = el('div', { class: 'acts' });
    /* Only a web address becomes a link: a reference is text a session wrote. */
    if (/^https?:\/\//i.test(d.url || '')) acts.appendChild(el('a', { class: 'btn', href: d.url, target: '_blank', rel: 'noopener noreferrer', text: n.type === 'session' ? 'Open session ↗' : 'Open ↗' }));
    acts.appendChild(el('button', { class: 'btn', type: 'button', text: 'Focus here', on: { click: function () { press(this); hideSheet(); sheetPushed = false; S.lens = 'map'; S.view = 'focus'; S.focus = id; writeHash(true); render(); } } }));
    body.appendChild(acts);
    var t = function (type, dir) { return (dir === 'in' ? ins(type, id).map(function (l) { return l.source; }) : outs(type, id).map(function (l) { return l.target; })); };
    var linkAge = function (type, dir) { return function (other) { var l = (dir === 'in' ? ins(type, id) : outs(type, id)).filter(function (x) { return (dir === 'in' ? x.source : x.target) === other; })[0]; return l && l.data.at ? age(l.data.at) : (l && l.data.count ? l.data.count + '×' : ''); }; };
    if (n.type === 'session') {
      [section('Works on', uniq(t('works_on').concat(t('works_on').length ? [] : t('works_in')))),
        section('Started by', t('spawned', 'in')), section('Started', t('spawned'), null, 5),
        section('Messaged', t('messaged'), linkAge('messaged')), section('Messaged by', t('messaged', 'in'), linkAge('messaged', 'in')),
        section('Same repository as', uniq(t('same_repo').concat(t('same_repo', 'in')))),
        section('Refers to the same thing as', uniq(t('same_reference').concat(t('same_reference', 'in')))),
        section('Refers to', t('mentions'), linkAge('mentions'), 5)].forEach(function (s) { if (s) body.appendChild(s); });
    } else if (n.type === 'owner') {
      [section('Waiting on you', t('waits_on_owner', 'in').sort(function (a, b) { return byInterest(N.get(a), N.get(b)); }), linkAge('waits_on_owner', 'in'), 8),
        section('You asked', t('told'), linkAge('told'))].forEach(function (s) { if (s) body.appendChild(s); });
    } else {
      var here = uniq(t('works_on', 'in').concat(t('works_in', 'in')).concat(t('mentions', 'in')).concat(t('runs_on', 'in')));
      here.sort(function (a, b) { return byInterest(N.get(a), N.get(b)); });
      [section(n.type === 'repo' || n.type === 'folder' || n.type === 'machine' ? 'Sessions here' : 'Referred to by', here, function (s) { return CLASS_WORDS[cls(N.get(s))]; }, 8),
        section('Folders', t('in_repo', 'in')), section('Repository', t('in_repo'))].forEach(function (s) { if (s) body.appendChild(s); });
    }
    openSheet();
  }
  function bundleSheet(id, body) {
    var b = bundles[id];
    if (!b) return closeSheet();
    body.appendChild(el('div', { class: 'sheet-head' }, [el('h3', { text: b.title })]));
    body.appendChild(el('div', { class: 'acts' }, [el('button', { class: 'btn', type: 'button', text: 'Show these on the map', on: { click: function () { press(this); b.members.forEach(function (m) { expanded.add(m); }); closeSheet(); render(); } } })]));
    body.appendChild(section('Sessions', b.members, function (s) { return CLASS_WORDS[cls(N.get(s))]; }, 12));
    openSheet();
  }
  var sheetPushed = false;
  function openSheet() { $('sheet').hidden = false; document.body.classList.add('sheet-open'); }
  function hideSheet() { $('sheet').hidden = true; document.body.classList.remove('sheet-open'); S.sel = ''; if (cy) cy.$(':selected').unselect(); }
  function closeSheet() {
    if ($('sheet').hidden) return;
    if (sheetPushed) { sheetPushed = false; try { history.back(); return; } catch (e) { /* fall through */ } }
    hideSheet();
    writeHash();
  }
  function select(id, centre) {
    var fresh = !S.sel;
    S.sel = id;
    sheetFor(id);
    if (fresh) { writeHash(true); sheetPushed = true; } else writeHash();
    if (!cy || S.lens !== 'map') return;
    var node = cy.getElementById(id);
    if (!node.length && N.has(id) && N.get(id).type === 'session') { expanded.add(id); drawMap(); node = cy.getElementById(id); }
    cy.$(':selected').unselect();
    if (!node.length) return;
    node.select();
    var at = node.renderedPosition(), st = stage();
    if (narrow(st) && at.y > st.h * 0.3) cy.animate({ panBy: { x: 0, y: st.h * 0.22 - at.y } }, { duration: 220 });
    else if (centre) cy.animate({ center: { eles: node } }, { duration: 250 });
  }

  /* ---------- the map: which nodes a view shows, and where each goes ---------- */
  var cy = null, bundles = {};
  function stage() { var b = $('cy').getBoundingClientRect(); return { w: Math.max(b.width, 300), h: Math.max(b.height, 320) }; }
  function narrow(st) { return st.w < 560; }
  function ringOf(rx, ry, tight) {
    /* Places around an ellipse where labels fit: close together where the ring runs up
       and down (labels sit beside the nodes and stack), far apart where it runs across. */
    var M = 720, cum = [0], th = [], i;
    for (i = 0; i <= M; i++) th.push(-Math.PI / 2 + 2 * Math.PI * i / M);
    for (i = 0; i < M; i++) {
      var t = (th[i] + th[i + 1]) / 2, dx = -rx * Math.sin(t), dy = ry * Math.cos(t), len = Math.hypot(dx, dy) || 1;
      cum.push(cum[i] + len * (2 * Math.PI / M) / (tight + 64 * Math.abs(dx / len)));
    }
    return {
      room: cum[M],
      at: function (frac) {
        var want = (((frac % 1) + 1) % 1) * cum[M], lo = 0, hi = M;
        while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (cum[mid] <= want) lo = mid; else hi = mid; }
        return th[lo] + (th[hi] - th[lo]) * (want - cum[lo]) / ((cum[hi] - cum[lo]) || 1);
      }
    };
  }
  function sessionRing(st, grow) {
    var slim = narrow(st), g = grow || 1;
    var RX = (st.w / 2 - (slim ? 106 : 118)) * g, RY = (st.h / 2 - (slim ? 70 : 92)) * g, k = slim ? 1 : 0.6;
    return { RX: RX, RY: RY, k: k, slim: slim, ring: ringOf(RX * k, RY * k, slim ? 40 : 30) };
  }
  function ringRoom(st) { var r = sessionRing(st); return Math.max(6, Math.min(Math.floor(r.ring.room), r.slim ? 16 : 40)); }
  function visibleSessions(room) {
    var live = SESSIONS.filter(function (n) { return cls(n) !== 'gone'; }), picked;
    if (S.show === 'all') picked = live;
    else if (S.show === 'more') picked = live.filter(function (n) { var c = cls(n); return n.data.interest >= SHOW.more || c === 'working' || c === 'needs'; });
    else {
      room = room || 18;
      var working = BY_CLASS.working.slice(0, Math.max(2, Math.round(room * 0.25)));
      var needs = BY_CLASS.needs.slice(0, Math.max(room - working.length, 3));
      picked = needs.concat(working.slice(0, Math.max(room - needs.length, 2)));
    }
    var ids = new Set(picked.map(function (n) { return n.id; }));
    live.forEach(function (n) { if (expanded.has(n.id) && !ids.has(n.id)) picked.push(n); });
    return picked.sort(byInterest);
  }
  function side(th) { var c = Math.cos(th); return Math.abs(c) > 0.5 ? { lh: c > 0 ? 'right' : 'left' } : { lv: Math.sin(th) < 0 ? 'top' : 'bottom' }; }
  function bundle(key, members, title, x, y, out, text) {
    if (!members.length) return;
    var id = 'bundle:' + key, words = text || ('+' + members.length + ' ' + title.replace(/^\d+ more /, ''));
    bundles[id] = { members: members.map(function (m) { return m.id || m; }), title: title };
    out.nodes.push({ id: id, type: 'bundle', label: words, x: x, y: y, w: 7 * words.length + 18 });
  }
  function addSession(n, x, y, out, parent, extra) {
    out.nodes.push(Object.assign({ id: n.id, type: 'session', cls: cls(n), why: n.data.why || '', label: n.data.label, x: x, y: y, size: 20 + 12 * n.data.interest, parent: parent }, extra || {}));
  }
  function addOther(id, x, y, out, extra) {
    var n = N.get(id);
    out.nodes.push(Object.assign({ id: id, type: n.type, label: n.data.label || id, x: x, y: y }, extra || {}));
  }
  function portrait() { var st = stage(); return st.h > st.w * 1.15; }
  function restBundles(shown, out) {
    var seen = new Set(shown.map(function (n) { return n.id; }));
    out.rest = [];
    ['needs', 'working', 'closable', 'quiet'].forEach(function (c) {
      var rest = BY_CLASS[c].filter(function (n) { return !seen.has(n.id); });
      if (!rest.length) return;
      var id = 'bundle:rest-' + c;
      bundles[id] = { members: rest.map(function (n) { return n.id; }), title: rest.length + ' more ' + CLASS_WORDS[c] };
      out.rest.push([id, '+' + rest.length + ' ' + CLASS_WORDS[c], c]);
    });
  }
  function wedges(keys, sizes, total) { /* a share of the ring per place, none over a third of it, a gap between two */
    var gap = keys.length > 1 ? 0.012 : 0, room = 1 - gap * keys.length, cap = keys.length > 1 ? 0.42 : room;
    var share = {}, open = keys.slice(), left = room, weight = total;
    for (var pass = 0; pass < keys.length; pass++) {
      var over = open.filter(function (k) { return left * sizes[k] / weight > cap; });
      if (!over.length) break;
      over.forEach(function (k) { share[k] = cap; left -= cap; weight -= sizes[k]; });
      open = open.filter(function (k) { return over.indexOf(k) < 0; });
    }
    open.forEach(function (k) { share[k] = left * sizes[k] / Math.max(weight, 1); });
    return { share: share, gap: gap };
  }
  function viewNeeds() {
    var out = { nodes: [], edges: [] }, st = stage(), shown = visibleSessions(ringRoom(st));
    var sectors = {}, sizes = {};
    shown.forEach(function (n) { var p = placeOf(n.id) || 'none'; (sectors[p] = sectors[p] || []).push(n); });
    var keys = Object.keys(sectors).sort(function (a, b) { return label(a) < label(b) ? -1 : 1; });
    keys.forEach(function (k) { sizes[k] = sectors[k].length; });
    var R = sessionRing(st, Math.max(1, shown.length / Math.max(sessionRing(st).ring.room, 1)));
    var w = wedges(keys, sizes, shown.length), at = -(w.share[keys[0]] || 0) / 2;
    addOther(OWNER, 0, 0, out, { size: 44 });
    keys.forEach(function (p) {
      var members = sectors[p], span = w.share[p], mid = R.ring.at(at + span / 2);
      members.forEach(function (n, i) {
        var theta = R.ring.at(at + span * (i + 0.5) / members.length);
        var extra = side(theta);
        if (R.slim && p !== 'none') { extra.label = n.data.label + '\n' + label(p); extra.two = 1; }
        addSession(n, R.RX * R.k * Math.cos(theta), R.RY * R.k * Math.sin(theta), out, null, extra);
        if (cls(n) === 'needs') out.edges.push({ s: n.id, t: OWNER, type: 'waits_on_owner', conf: (outs('waits_on_owner', n.id)[0] || { data: {} }).data.confidence || 'observed' });
        if (p !== 'none' && !R.slim) out.edges.push({ s: n.id, t: p, type: 'works_on', conf: placeHow(n.id) });
      });
      if (p !== 'none' && !R.slim) addOther(p, R.RX * Math.cos(mid), R.RY * Math.sin(mid), out, side(mid));
      at += span + w.gap;
    });
    crossLinks(shown, out, ['messaged']);
    restBundles(shown, out);
    return out;
  }
  function viewPlaces() {
    var out = { nodes: [], edges: [] }, st = stage(), shown = visibleSessions(Math.max(8, Math.floor(st.w * st.h / 16000))), groups = {};
    shown.forEach(function (n) { var p = placeOf(n.id) || 'none'; (groups[p] = groups[p] || []).push(n); });
    var keys = Object.keys(groups).sort(function (a, b) { return (groups[b].length - groups[a].length) || (label(a) < label(b) ? -1 : 1); });
    var cw = 96, ch = 66, pad = 22, wrap = Math.max(st.w - 40, 300) * Math.max(1, Math.sqrt(shown.length * 16000 / (st.w * st.h))), x = 0, y = 0, rowH = 0;
    keys.forEach(function (p) {
      var members = groups[p], cols = Math.min(members.length, Math.max(1, Math.round(Math.sqrt(members.length * (portrait() ? 0.8 : 1.6)))));
      var rows = Math.ceil(members.length / cols), w = cols * cw, h = rows * ch;
      if (x && x + w > wrap) { x = 0; y += rowH + pad * 2.4; rowH = 0; }
      var parent = p === 'none' ? null : 'box:' + p;
      if (parent) out.nodes.push({ id: parent, type: 'box', label: label(p), of: p });
      members.forEach(function (n, i) { addSession(n, x + (i % cols) * cw + cw / 2, y + Math.floor(i / cols) * ch + ch / 2, out, parent); });
      x += w + pad * 1.6; rowH = Math.max(rowH, h);
    });
    crossLinks(shown, out, ['messaged', 'spawned']);
    restBundles(shown, out);
    return out;
  }
  function viewAll() {
    var out = { nodes: [], edges: [] }, st = stage(), groups = {}, calm = [];
    var live = SESSIONS.filter(function (n) { return cls(n) !== 'gone'; });
    live.forEach(function (n) { var p = placeOf(n.id) || 'none'; (groups[p] = groups[p] || []).push(n); });
    var tally = function (list, c) { return list.filter(function (n) { return cls(n) === c; }).length; };
    var keys = Object.keys(groups).filter(function (p) {
      if (tally(groups[p], 'needs') || tally(groups[p], 'working')) return true;
      calm = calm.concat(groups[p]);
      return false;
    }).sort(function (a, b) { return label(a).toLowerCase() < label(b).toLowerCase() ? -1 : 1; });
    var order = { needs: 0, working: 1, closable: 2, quiet: 3 }, cell = 24, pad = 30, wrap = Math.max(st.w - 16, 300) * Math.max(1, Math.sqrt(live.length * 2600 / (st.w * st.h))), x = 0, y = 0, rowH = 0;
    function box(id, name, members, of) {
      members.sort(function (a, b) { return (order[cls(a)] - order[cls(b)]) || byInterest(a, b); });
      var cols = Math.min(members.length, Math.max(2, Math.ceil(Math.sqrt(members.length * 1.8)))), rows = Math.ceil(members.length / cols);
      var w = Math.max(cols * cell, 7 * Math.min(name.length, 18) + 6), h = rows * cell;
      if (x && x + w > wrap) { x = 0; y += rowH + pad + 20; rowH = 0; }
      out.nodes.push({ id: id, type: 'box', label: name, of: of, tight: 1, tw: w + 14 });
      members.forEach(function (n, i) {
        var c = cls(n);
        addSession(n, x + (w - cols * cell) / 2 + (i % cols) * cell + cell / 2, y + Math.floor(i / cols) * cell + cell / 2, out, id, { dot: 1, size: c === 'needs' ? 17 : c === 'working' ? 15 : 11 });
      });
      x += w + pad; rowH = Math.max(rowH, h);
    }
    keys.forEach(function (p) {
      var asks = tally(groups[p], 'needs'), name = p === 'none' ? 'no folder' : label(p);
      box('box:' + p, asks ? name + ' · ' + asks : name, groups[p], p === 'none' ? '' : p);
    });
    if (calm.length) {
      bundles['bundle:calm'] = { members: calm.map(function (n) { return n.id; }), title: calm.length + ' sessions quiet or done in ' + (Object.keys(groups).length - keys.length) + ' other places' };
      box('box:calm', 'quiet or done elsewhere', calm, 'bundle:calm');
    }
    return out;
  }
  function crossLinks(shown, out, types) {
    var ids = new Set(shown.map(function (n) { return n.id; }));
    types.concat(S.on).forEach(function (type) {
      shown.forEach(function (n) {
        outs(type, n.id).forEach(function (l) { if (ids.has(l.target)) out.edges.push({ s: l.source, t: l.target, type: type, conf: l.data.confidence, sym: l.data.symmetric }); });
      });
    });
  }
  function viewFamily() {
    var out = { nodes: [], edges: [] }, floor = SHOW[S.show], slot = 0, dx = portrait() ? 150 : 210, dy = 40;
    var kids = function (id) { return outs('spawned', id).map(function (l) { return N.get(l.target); }).filter(Boolean); };
    var roots = SESSIONS.filter(function (n) { return !ins('spawned', n.id).length && kids(n.id).length; }).sort(byInterest);
    function place(n, depth) {
      var all = kids(n.id).sort(byInterest);
      var keep = all.filter(function (k) { return k.data.interest >= floor || expanded.has(k.id) || kids(k.id).length; });
      var rest = all.filter(function (k) { return keep.indexOf(k) < 0; });
      var first = slot;
      keep.forEach(function (k) { place(k, depth + 1); out.edges.push({ s: n.id, t: k.id, type: 'spawned', tree: 1, conf: (ins('spawned', k.id)[0] || { data: {} }).data.confidence }); });
      if (rest.length) {
        var words = CLASSES.map(function (c) { var m = rest.filter(function (k) { return cls(k) === c; }).length; return m ? m + ' ' + CLASS_WORDS[c] : ''; }).filter(Boolean).join(', ');
        var text = '+' + rest.length + ': ' + words;
        bundle('kids-' + n.id, rest, rest.length + ' more started by ' + n.data.label, (depth + 1) * dx + (7 * text.length + 18) / 2 - 12, slot * dy, out, text);
        out.edges.push({ s: n.id, t: 'bundle:kids-' + n.id, type: 'spawned', tree: 1, conf: 'recorded' });
        slot += 1;
      }
      var y = slot === first ? slot++ * dy : (first + slot - 1) / 2 * dy;
      out.nodes.push(Object.assign({ id: n.id, type: 'session', cls: cls(n), why: n.data.why || '', label: n.data.label, x: depth * dx, y: y, size: 20 + 12 * n.data.interest }, all.length ? { lv: 'top' } : { side: true }));
    }
    roots.forEach(function (r) { place(r, 0); slot += 0.6; });
    return out;
  }
  function viewTalk() {
    var out = { nodes: [], edges: [] }, ids = new Set(), pairs = [];
    ['messaged', 'told'].forEach(function (type) {
      Object.keys(OUT[type] || {}).forEach(function (src) { OUT[type][src].forEach(function (l) { ids.add(l.source); ids.add(l.target); pairs.push(l); }); });
    });
    ids.delete(OWNER);
    var list = Array.from(ids).map(function (id) { return N.get(id); }).filter(Boolean).sort(function (a, b) { return a.data.label < b.data.label ? -1 : 1; });
    var st = stage(), R = sessionRing(st, 1), grow = Math.max(1, list.length / Math.max(R.ring.room, 1));
    R = sessionRing(st, grow);
    if (pairs.some(function (l) { return l.source === OWNER; })) addOther(OWNER, 0, 0, out, { size: 44 });
    list.forEach(function (n, i) { var th = R.ring.at(i / list.length); addSession(n, R.RX * R.k * Math.cos(th), R.RY * R.k * Math.sin(th), out, null, side(th)); });
    pairs.forEach(function (l) { out.edges.push({ s: l.source, t: l.target, type: l.type, conf: l.data.confidence, count: l.data.count }); });
    out.empty = list.length ? '' : 'No message between sessions is on record yet.';
    return out;
  }
  function viewFree() {
    var out = viewNeeds(), shown = out.nodes.filter(function (n) { return n.type === 'session'; }).map(function (n) { return N.get(n.id); });
    out.nodes = out.nodes.filter(function (n) { return n.type !== 'bundle'; });
    out.nodes.forEach(function (n) { delete n.lh; delete n.lv; });
    crossLinks(shown, out, ['messaged', 'spawned']);
    out.layout = 'cose';
    return out;
  }
  function viewFocus() {
    /* One node in the middle, what it is linked to around it, and what those are linked to
       beyond: drawn as the paths that lead out from the middle, not every link among them.
       A neighbour with many links of its own (a dispatcher, the owner) is shown and not opened. */
    var out = { nodes: [], edges: [] }, start = N.has(S.focus) ? S.focus : OWNER;
    var types = Object.keys(LINK_TYPES).filter(function (t) { return (LINK_TYPES[t].how === 'read' && t !== 'runs_on' && t !== 'works_in') || t === 'works_on' || S.on.indexOf(t) >= 0; });
    var ring = [[start]], seen = new Set([start]), CAP = Math.max(10, ringRoom(stage()) + 6), HUB = 12, shut = [];
    function near(id) {
      var found = [];
      types.forEach(function (type) {
        outs(type, id).forEach(function (l) { found.push({ o: l.target, e: { s: l.source, t: l.target, type: type, conf: l.data.confidence } }); });
        ins(type, id).forEach(function (l) { found.push({ o: l.source, e: { s: l.source, t: l.target, type: type, conf: l.data.confidence } }); });
      });
      return found.filter(function (f) { var n = N.get(f.o); return n && !(n.type === 'folder' && outs('in_repo', f.o).length); });
    }
    for (var hop = 0; hop < 2; hop++) {
      var next = [], edges = {};
      ring[hop].forEach(function (id) {
        var around = near(id);
        if (hop && uniq(around.map(function (f) { return f.o; })).length > HUB) { shut.push(label(id)); return; }
        around.forEach(function (f) {
          var n = N.get(f.o);
          if (!S.refs && (hop || n.type === 'doc') && (n.type === 'issue' || n.type === 'pr' || n.type === 'doc')) return;
          if (seen.has(f.o) && next.indexOf(f.o) < 0) { if (!hop || ring[hop].indexOf(f.o) < 0) return; }
          if (!seen.has(f.o)) { seen.add(f.o); next.push(f.o); }
          (edges[f.o] = edges[f.o] || []).push(f.e);
        });
      });
      next.sort(function (a, b) { return byInterest(N.get(a), N.get(b)); });
      ring.push(next.slice(0, CAP));
      ring[hop + 1].forEach(function (id) { (edges[id] || []).forEach(function (e) { out.edges.push(e); }); });
      if (next.length > CAP) ring.overflow = (ring.overflow || 0) + next.length - CAP;
    }
    var st = stage(), slim = narrow(st), mx = slim ? 106 : 130, my = slim ? 70 : 92;
    var base = ringOf(st.w / 2 - mx, st.h / 2 - my, slim ? 40 : 30).room, grow = Math.max(1, ring[2].length / Math.max(base, 1), ring[1].length / Math.max(base * 0.5, 1));
    ring.forEach(function (ids, hop) {
      var k = [0, ring[2].length ? 0.5 : 1, 1][hop], rx = (st.w / 2 - mx) * grow * k, ry = (st.h / 2 - my) * grow * k, around = ringOf(rx || 1, ry || 1, slim ? 40 : 30);
      ids.forEach(function (id, i) {
        var th = around.at((i + (hop === 2 ? 0.5 : 0)) / Math.max(ids.length, 1)), n = N.get(id);
        var x = rx * Math.cos(th), y = ry * Math.sin(th), where = hop === 2 || (hop === 1 && !ring[2].length) ? side(th) : (hop ? { lv: Math.sin(th) < 0 ? 'top' : 'bottom' } : null);
        if (n.type === 'session') addSession(n, x, y, out, null, where); else addOther(id, x, y, out, Object.assign(id === start ? { size: 44 } : {}, where || {}));
      });
    });
    out.note = 'Around ' + label(start) + '.' + (shut.length ? ' Not opened further: ' + uniq(shut).join(', ') + '.' : '') + (ring.overflow ? ' ' + ring.overflow + ' more not drawn.' : '');
    return out;
  }
  var BUILD = { all: viewAll, needs: viewNeeds, places: viewPlaces, family: viewFamily, talk: viewTalk, free: viewFree, focus: viewFocus };

  /* ---------- drawing ---------- */
  function token(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function style() {
    var ink = token('--ink'), soft = token('--ink-soft'), rule = token('--rule'), surface = token('--surface'), ground = token('--ground');
    var needs = token('--needs'), accent = token('--accent'), free = token('--free'), waits = token('--waits'), unsure = token('--unsure');
    var font = token('--mono') || 'monospace';
    return [
      { selector: 'node', style: { 'label': 'data(label)', 'font-family': font, 'font-size': 11, 'color': ink, 'text-valign': 'bottom', 'text-margin-y': 4, 'text-wrap': 'ellipsis', 'text-max-width': 96, 'min-zoomed-font-size': 6, 'width': 'data(size)', 'height': 'data(size)', 'background-color': waits, 'border-width': 0, 'text-outline-color': ground, 'text-outline-width': 2, 'text-outline-opacity': 0.9 } },
      { selector: 'node[lv="top"]', style: { 'text-valign': 'top', 'text-margin-y': -4 } },
      { selector: 'node[lh="right"]', style: { 'text-valign': 'center', 'text-halign': 'right', 'text-margin-x': 5, 'text-margin-y': 0 } },
      { selector: 'node[lh="left"]', style: { 'text-valign': 'center', 'text-halign': 'left', 'text-margin-x': -5, 'text-margin-y': 0 } },
      { selector: 'node[?dot]', style: { 'font-size': 7, 'min-zoomed-font-size': 12 * (window.devicePixelRatio || 1), 'text-max-width': 60, 'text-margin-y': 2 } },
      { selector: 'node[?tight]', style: { 'padding': 7, 'font-size': 11, 'text-max-width': 'data(tw)', 'compound-sizing-wrt-labels': 'exclude' } },
      { selector: 'node[?two]', style: { 'text-wrap': 'wrap', 'line-height': 1.15 } },
      { selector: 'node[?side]', style: { 'text-valign': 'center', 'text-halign': 'right', 'text-margin-x': 6, 'text-margin-y': 0, 'text-max-width': 150 } },
      { selector: 'node[cls="needs"]', style: { 'background-color': needs } },
      { selector: 'node[cls="needs"][why="decision"]', style: { 'border-width': 3, 'border-color': ink } },
      { selector: 'node[cls="working"]', style: { 'background-color': accent } },
      { selector: 'node[cls="closable"]', style: { 'background-color': free, 'opacity': 0.75 } },
      { selector: 'node[cls="quiet"]', style: { 'background-color': waits, 'opacity': 0.7 } },
      { selector: 'node[cls="gone"]', style: { 'background-color': surface, 'border-width': 2, 'border-color': waits, 'border-style': 'dashed' } },
      { selector: 'node[type="owner"]', style: { 'background-color': ink, 'color': ink, 'font-size': 13, 'font-weight': 700, 'shape': 'star' } },
      { selector: 'node[type="repo"], node[type="folder"]', style: { 'shape': 'round-rectangle', 'background-color': surface, 'border-width': 2, 'border-color': soft, 'width': 30, 'height': 22, 'color': soft } },
      { selector: 'node[type="folder"]', style: { 'border-style': 'dashed' } },
      { selector: 'node[type="machine"]', style: { 'shape': 'hexagon', 'background-color': surface, 'border-width': 2, 'border-color': soft, 'width': 28, 'height': 28 } },
      { selector: 'node[type="issue"], node[type="pr"]', style: { 'shape': 'diamond', 'background-color': surface, 'border-width': 2, 'border-color': unsure, 'width': 18, 'height': 18, 'font-size': 9, 'color': soft } },
      { selector: 'node[type="doc"]', style: { 'shape': 'rectangle', 'background-color': surface, 'border-width': 2, 'border-color': rule, 'width': 14, 'height': 18, 'font-size': 9, 'color': soft } },
      { selector: 'node[type="bundle"]', style: { 'shape': 'round-rectangle', 'background-color': surface, 'border-width': 1.5, 'border-style': 'dashed', 'border-color': soft, 'width': 'data(w)', 'height': 26, 'text-valign': 'center', 'text-halign': 'center', 'text-margin-x': 0, 'text-margin-y': 0, 'text-max-width': 460, 'color': soft, 'text-outline-width': 0 } },
      { selector: 'node[type="box"]', style: { 'compound-sizing-wrt-labels': 'exclude', 'shape': 'round-rectangle', 'background-color': surface, 'background-opacity': 0.6, 'border-width': 1.5, 'border-color': rule, 'padding': 14, 'text-valign': 'top', 'text-halign': 'center', 'text-margin-y': -4, 'color': soft, 'font-size': 12, 'text-max-width': 200 } },
      { selector: 'node:selected', style: { 'border-width': 4, 'border-color': accent, 'border-style': 'solid', 'opacity': 1 } },
      { selector: 'edge', style: { 'width': 1.4, 'line-color': rule, 'curve-style': 'bezier', 'target-arrow-shape': 'none', 'target-arrow-color': rule, 'arrow-scale': 0.9, 'opacity': 0.9 } },
      { selector: 'edge[conf="observed"]', style: { 'line-style': 'dashed' } },
      { selector: 'edge[conf="inferred"]', style: { 'line-style': 'dotted', 'line-color': unsure, 'opacity': 0.75 } },
      { selector: 'edge[type="works_on"][conf="recorded"]', style: { 'line-style': 'solid', 'line-color': rule } },
      { selector: 'edge[type="waits_on_owner"]', style: { 'line-color': needs, 'target-arrow-color': needs, 'target-arrow-shape': 'triangle', 'width': 2 } },
      { selector: 'edge[type="told"]', style: { 'line-color': ink, 'target-arrow-color': ink, 'target-arrow-shape': 'triangle' } },
      { selector: 'edge[type="messaged"]', style: { 'line-color': accent, 'target-arrow-color': accent, 'target-arrow-shape': 'triangle', 'width': 2 } },
      { selector: 'edge[type="spawned"]', style: { 'line-color': soft, 'target-arrow-color': soft, 'target-arrow-shape': 'triangle' } },
      { selector: 'edge[?tree]', style: { 'curve-style': 'taxi', 'taxi-direction': 'rightward', 'taxi-turn': 22, 'taxi-turn-min-distance': 6 } },
      { selector: 'edge[type="mentions"]', style: { 'line-color': rule, 'width': 1 } },
      { selector: '.faded', style: { 'opacity': 0.12, 'text-opacity': 0 } }
    ];
  }
  function elements(built) {
    var list = built.nodes.map(function (n) {
      var data = { id: n.id, label: n.label, type: n.type, size: n.size || 26 };
      ['cls', 'why', 'parent', 'side', 'of', 'lh', 'lv', 'w', 'two', 'dot', 'tight', 'tw'].forEach(function (k) { if (n[k]) data[k] = n[k]; });
      return n.type === 'box' ? { group: 'nodes', data: data } : { group: 'nodes', data: data, position: { x: n.x, y: n.y } };
    });
    var seen = new Set(built.nodes.map(function (n) { return n.id; })), dup = new Set();
    built.edges.forEach(function (e) {
      var id = e.type + ':' + e.s + '>' + e.t;
      if (dup.has(id) || !seen.has(e.s) || !seen.has(e.t)) return;
      dup.add(id);
      list.push({ group: 'edges', data: Object.assign({ id: id, source: e.s, target: e.t, type: e.type, conf: e.conf || 'observed' }, e.tree ? { tree: 1 } : {}) });
    });
    return list;
  }
  function drawMap() {
    if (!window.cytoscape) { $('map-empty').textContent = 'The map could not start in this browser. The docket and the board hold the same sessions.'; $('map-empty').hidden = false; return; }
    bundles = {};
    var built = (BUILD[S.view] || viewAll)();
    var known = {};
    if (cy) cy.nodes().forEach(function (n) { known[n.id()] = n.position(); });
    if (!cy) {
      cy = window.cytoscape({ container: $('cy'), style: style(), layout: { name: 'preset' }, minZoom: 0.15, maxZoom: 3, boxSelectionEnabled: false, autoungrabify: false });
      cy.on('tap', function (ev) {
        if (ev.target !== cy) { if (ev.target.isNode() && ev.target.data('type') !== 'box') select(ev.target.id()); else if (ev.target.isNode() && ev.target.data('of')) select(ev.target.data('of')); return; }
        var p = ev.renderedPosition, best = null, bestD = 30;
        cy.nodes().forEach(function (n) { if (n.data('type') === 'box') return; var q = n.renderedPosition(), dd = Math.hypot(q.x - p.x, q.y - p.y); if (dd < bestD) { bestD = dd; best = n; } });
        if (best) select(best.id()); else closeSheet();
      });
    }
    var next = elements(built);
    cy.batch(function () {
      cy.elements().remove();
      cy.add(next);
    });
    var rest = $('rest');
    rest.textContent = '';
    (built.rest || []).forEach(function (r) { rest.appendChild(el('button', { type: 'button', class: 'restb ' + r[2], text: r[1], on: { click: function () { press(this); select(r[0]); } } })); });
    rest.hidden = !(built.rest || []).length;
    document.body.classList.toggle('has-rest', !rest.hidden);
    $('map-empty').hidden = !built.empty;
    $('map-empty').textContent = built.empty || '';
    if (built.layout === 'cose') {
      cy.layout({ name: 'cose', animate: false, randomize: false, nodeRepulsion: function () { return 60000; }, idealEdgeLength: function () { return 90; }, gravity: 0.4, numIter: 1500, padding: 20, nodeDimensionsIncludeLabels: true }).run();
    } else {
      cy.nodes().forEach(function (n) { var was = known[n.id()], to = n.position(); if (was && n.data('type') !== 'box' && (was.x !== to.x || was.y !== to.y)) { var goal = { x: to.x, y: to.y }; n.position(was); n.animate({ position: goal }, { duration: 320 }); } });
    }
    cy.resize();
    fit();
    var note = VIEWS.filter(function (v) { return v[0] === S.view; })[0];
    $('view-note').textContent = built.note || (note ? note[2] : '');
    if (S.sel && cy.getElementById(S.sel).length) cy.getElementById(S.sel).select();
  }
  function fit() { if (!cy) return; var pad = 14; cy.fit(cy.elements(), pad); if (cy.zoom() > 1.15) { cy.zoom(1.15); cy.center(); } setTimeout(function () { cy.animate({ fit: { eles: cy.elements(), padding: pad } }, { duration: 200, complete: function () { if (cy.zoom() > 1.15) { cy.zoom(1.15); cy.center(); } } }); }, 360); }

  /* ---------- the docket: the same sessions as a list a thumb can read ---------- */
  function docketRow(n) {
    var d = n.data, c = cls(n), where = placeOf(n.id);
    return el('button', { class: 'row ' + c, type: 'button', on: { click: function () { select(n.id); } } }, [
      el('span', { class: 'row-say', text: plainAsk(n) || CLASS_WORDS[c] }),
      el('span', { class: 'row-meta' }, [el('time', { text: clock(d.said_at || d.since) }), el('b', { text: d.label }), where ? el('span', { class: 'row-place', text: label(where) }) : null])]);
  }
  function listOf(title, nodes, open, cap) {
    if (!nodes.length) return null;
    var box = el('section', { class: 'reg' }, [el('h2', {}, [title, el('span', { class: 'count', text: String(nodes.length) })])]);
    nodes.slice(0, cap).forEach(function (n) { box.appendChild(docketRow(n)); });
    if (nodes.length > cap) {
      var more = el('details', { class: 'more' }, [el('summary', { text: (nodes.length - cap) + ' more' })]);
      nodes.slice(cap).forEach(function (n) { more.appendChild(docketRow(n)); });
      box.appendChild(more);
    }
    if (!open) { var fold = el('details', { class: 'fold' }, [el('summary', {}, [title, el('span', { class: 'count', text: String(nodes.length) })])]); Array.from(box.children).slice(1).forEach(function (c) { fold.appendChild(c); }); return fold; }
    return box;
  }
  function drawDocket(into, cap) {
    into.textContent = '';
    var any = false;
    ['decision', 'action', 'question'].forEach(function (why) {
      var rows = BY_CLASS.needs.filter(function (n) { return (n.data.why || 'question') === why; });
      var made = listOf(WHY_WORDS[why], rows, true, cap);
      if (made) { into.appendChild(made); any = true; }
    });
    if (!any) into.appendChild(el('p', { class: 'calm', text: 'Nothing waits on you.' }));
    [['Working', BY_CLASS.working], ['Can be closed', BY_CLASS.closable], ['Quiet', BY_CLASS.quiet]].forEach(function (g) {
      var made = listOf(g[0], g[1], false, 12);
      if (made) into.appendChild(made);
    });
  }

  function drawBrief() {
    var into = $('brief'), wide = window.matchMedia && window.matchMedia('(min-width: 60rem)').matches, cap = wide ? 8 : 3;
    into.textContent = '';
    var rank = { decision: 0, action: 1 }, first = BY_CLASS.needs.slice().sort(function (a, b) { var x = rank[a.data.why], y = rank[b.data.why]; return ((x === undefined ? 2 : x) - (y === undefined ? 2 : y)) || byInterest(a, b); });
    first.slice(0, cap).forEach(function (n) { into.appendChild(docketRow(n)); });
    if (BY_CLASS.needs.length > cap) into.appendChild(el('button', { class: 'all', type: 'button', text: (BY_CLASS.needs.length - cap) + ' more in the docket', on: { click: function () { S.lens = 'docket'; writeHash(); render(); } } }));
    if (!BY_CLASS.needs.length) into.appendChild(el('p', { class: 'calm', text: 'Nothing waits on you.' }));
  }

  /* ---------- the board: one card per place ---------- */
  function drawBoard() {
    var into = $('board');
    into.textContent = '';
    var groups = {};
    SESSIONS.forEach(function (n) { if (cls(n) === 'gone') return; var p = placeOf(n.id) || 'none'; (groups[p] = groups[p] || []).push(n); });
    var rank = function (list) { return [list.filter(function (n) { return cls(n) === 'needs'; }).length, list.filter(function (n) { return cls(n) === 'working'; }).length, list.length]; };
    var keys = Object.keys(groups).sort(function (a, b) { var x = rank(groups[a]), y = rank(groups[b]); return (y[0] - x[0]) || (y[1] - x[1]) || (y[2] - x[2]); });
    keys.forEach(function (p) {
      var list = groups[p].sort(byInterest), counts = CLASSES.map(function (c) { return [c, list.filter(function (n) { return cls(n) === c; }).length]; }).filter(function (c) { return c[1]; });
      var card = el('details', { class: 'card' + (counts[0][0] === 'needs' ? ' hot' : '') }, [el('summary', {}, [
        el('span', { class: 'card-name', text: p === 'none' ? 'no folder' : label(p) }),
        el('span', { class: 'card-dots' }, counts.map(function (c) { return el('span', { class: 'tally ' + c[0], text: c[1] + ' ' + CLASS_WORDS[c[0]] }); })),
        list[0] && cls(list[0]) === 'needs' ? el('span', { class: 'card-say', text: plainAsk(list[0]) }) : null])]);
      list.forEach(function (n) { card.appendChild(docketRow(n)); });
      into.appendChild(card);
    });
  }

  /* ---------- controls ---------- */
  function chips(into, items, current, pick) {
    into.textContent = '';
    items.forEach(function (it) {
      into.appendChild(el('button', { type: 'button', class: 'pick', 'aria-pressed': String(it[0] === current), title: it[2] || '', text: it[1], on: { click: function () { press(this); pick(it[0]); } } }));
    });
  }
  function layers() {
    var box = $('layers-body');
    box.textContent = '';
    box.appendChild(el('h4', { text: 'How much' }));
    var how = el('div', { class: 'picks' });
    chips(how, [['key', 'Important'], ['more', 'More'], ['all', 'Everything']], S.show, function (v) { S.show = v; expanded.clear(); writeHash(); render(); });
    box.appendChild(how);
    box.appendChild(el('h4', { text: 'Derived links' }));
    DERIVED.forEach(function (t) {
      var id = 'on-' + t, input = el('input', { type: 'checkbox', id: id, on: { change: function () { S.on = S.on.filter(function (x) { return x !== t; }); if (this.checked) S.on.push(t); writeHash(); if (S.view === 'needs') S.view = 'free'; render(); } } });
      input.checked = S.on.indexOf(t) >= 0;
      box.appendChild(el('label', { class: 'check', for: id }, [input, el('span', {}, [el('b', { text: t.replace(/_/g, ' ') }), ' ', LINK_TYPES[t].says])]));
    });
    var refs = el('input', { type: 'checkbox', id: 'on-refs', on: { change: function () { S.refs = this.checked; writeHash(); render(); } } });
    refs.checked = S.refs;
    box.appendChild(el('label', { class: 'check', for: 'on-refs' }, [refs, el('span', {}, [el('b', { text: 'references' }), ' issues, pull requests and pages, two links out, when a node is in focus'])]));
    box.appendChild(el('h4', { text: 'Find' }));
    var results = el('div', { class: 'results' });
    box.appendChild(el('input', { type: 'search', class: 'find', placeholder: 'a session, a repository, an issue', 'aria-label': 'Find a node', on: { input: function () {
      var q = this.value.trim().toLowerCase();
      results.textContent = '';
      if (q.length < 2) return;
      DOC.nodes.filter(function (n) { return (n.data.label || '').toLowerCase().indexOf(q) >= 0; }).sort(byInterest).slice(0, 12).forEach(function (n) { results.appendChild(nodeRow(n.id, n.type)); });
    } } }));
    box.appendChild(results);
    box.appendChild(el('h4', { text: 'Reading the map' }));
    [['dot needs', 'needs you (a ring: a decision)'], ['dot working', 'working'], ['dot closable', 'can be closed'], ['dot quiet', 'quiet'], ['dot repo', 'a repository or folder'], ['line solid', 'recorded'], ['line dashed', 'seen, not recorded'], ['line dotted', 'derived by a rule']].forEach(function (k) {
      box.appendChild(el('p', { class: 'key' }, [el('span', { class: k[0] }), k[1]]));
    });
  }
  function render() {
    document.body.setAttribute('data-lens', S.lens);
    document.body.classList.toggle('hybrid', CFG.entry === 'hybrid');
    chips($('lenses'), [['map', 'Map'], ['docket', 'Docket'], ['board', 'Board']], S.lens, function (v) { S.lens = v; writeHash(); render(); });
    var views = VIEWS.slice();
    if (S.view === 'focus') views = [['back', '‹ Back', 'Back to the view before'], ['focus', 'Focus on ' + label(S.focus), '']];
    chips($('views'), views, S.view, function (v) { if (v === 'back') { history.back(); return; } S.view = v; if (v !== 'focus') S.focus = ''; writeHash(); render(); });
    sentence();
    layers();
    if (S.lens === 'map') { if (CFG.entry === 'hybrid') drawBrief(); drawMap(); }
    else if (S.lens === 'docket') drawDocket($('docket'), 5);
    else drawBoard();
  }

  /* ---------- wiring ---------- */
  $('sheet-close').addEventListener('click', closeSheet);
  $('reload').addEventListener('click', function () { this.setAttribute('data-pending', ''); this.textContent = 'Reloading…'; location.reload(); });
  $('layers-open').addEventListener('click', function () { press(this); $('layers').hidden = !$('layers').hidden; });
  $('layers-close').addEventListener('click', function () { $('layers').hidden = true; });
  $('fit').addEventListener('click', function () { press(this); fit(); });
  $('nav-open').addEventListener('click', function () { press(this); this.setAttribute('aria-expanded', String($('nav').classList.toggle('open'))); });
  document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') { closeSheet(); $('layers').hidden = true; } });
  window.addEventListener('resize', function () { if (cy && S.lens === 'map') { cy.resize(); fit(); } });
  if (window.matchMedia) { var dark = window.matchMedia('(prefers-color-scheme: dark)'); var restyle = function () { if (cy) cy.style(style()); }; if (dark.addEventListener) dark.addEventListener('change', restyle); }
  readHash();
  tickAge();
  setInterval(tickAge, 30000);
  render();
  if (S.sel) { sheetFor(S.sel); if (cy && cy.getElementById(S.sel).length) cy.getElementById(S.sel).select(); }
})();
