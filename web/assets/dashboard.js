(function () {
  'use strict';

  var app = document.getElementById('app');
  var parts = location.hash.slice(1).split('.');
  var botId = parts[0], adminKey = parts.slice(1).join('.');
  var state = { bot: null, leads: [], sessions: [], tab: 'overview', filter: 'all', timer: null };
  var STAGES = [['queued', 'Getting started'], ['reading', 'Reading your website'], ['learning', 'Learning your business'], ['done', 'Ready']];
  var STATUSES = ['new', 'contacted', 'qualified', 'won', 'lost'];
  var TABS = ['overview', 'leads', 'conversations', 'knowledge', 'settings'];
  var wanted = new URLSearchParams(location.search).get('tab');
  if (TABS.indexOf(wanted) !== -1) state.tab = wanted;

  // ------------------------------------------------------------ helpers

  function h(tag, attrs) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      var value = attrs[key];
      if (value == null || value === false) return;
      if (key === 'text') node.textContent = value;
      else if (key === 'class') node.className = value;
      else if (key.slice(0, 2) === 'on') node.addEventListener(key.slice(2), value);
      else if (key === 'value') node.value = value;
      else node.setAttribute(key, value === true ? '' : value);
    });
    for (var i = 2; i < arguments.length; i++) append(node, arguments[i]);
    return node;
  }
  function append(node, child) {
    if (child == null || child === false) return;
    if (Array.isArray(child)) child.forEach(function (c) { append(node, c); });
    else node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  }
  function mount(node) { app.textContent = ''; append(app, node); }

  function api(method, path, body) {
    return fetch('/api' + path, {
      method: method,
      headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
      body: body ? JSON.stringify(body) : undefined
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) { var err = new Error(data.error || 'Something went wrong.'); err.status = res.status; throw err; }
        return data;
      });
    });
  }

  function toast(message, bad) {
    var old = document.querySelector('.toast');
    if (old) old.remove();
    var node = h('div', { class: 'toast' + (bad ? ' bad' : ''), role: 'status', text: message });
    document.body.appendChild(node);
    setTimeout(function () { node.remove(); }, 3200);
  }

  function copy(text, label) {
    var done = function () { toast(label + ' copied'); };
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(done, function () { toast('Copy failed. Select and copy it by hand.', true); });
    var area = h('textarea', { value: text, style: 'position:fixed;opacity:0' });
    document.body.appendChild(area); area.select();
    try { document.execCommand('copy'); done(); } catch (e) { toast('Copy failed. Select and copy it by hand.', true); }
    area.remove();
  }

  function ago(iso) {
    if (!iso) return '';
    var seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (seconds < 60) return 'just now';
    if (seconds < 3600) return Math.floor(seconds / 60) + ' min ago';
    if (seconds < 86400) return Math.floor(seconds / 3600) + ' h ago';
    if (seconds < 86400 * 14) return Math.floor(seconds / 86400) + ' d ago';
    return new Date(iso).toLocaleDateString();
  }
  function when(iso) { return h('span', { title: iso ? new Date(iso).toLocaleString() : '', text: ago(iso) }); }
  function pill(label, score) { return h('span', { class: 'pill ' + (label || 'cold'), text: (label || 'cold') + (score != null ? ' · ' + score : '') }); }
  function lines(text) { return String(text || '').split('\n').map(function (s) { return s.trim(); }).filter(Boolean); }
  function embedCode() { return '<script src="' + location.origin + '/widget.js" data-bot="' + botId + '" async></' + 'script>'; }

  // ------------------------------------------------------------ boot

  function fatal(title, message) {
    mount(h('div', { class: 'center' }, h('div', { class: 'box' },
      h('h1', { text: title }), h('p', { class: 'muted', text: message }),
      h('p', { style: 'margin-top:22px' }, h('a', { class: 'btn', href: '/', text: 'Build an assistant' })))));
  }

  function boot() {
    if (!botId || !adminKey) return fatal('No dashboard link', 'Open the private dashboard link you were given when you built your assistant.');
    load();
  }

  function load() {
    api('GET', '/bots/' + botId).then(function (bot) {
      state.bot = bot;
      document.getElementById('bot-name').textContent = bot.name || '';
      if (bot.status === 'building') { renderBuilding(bot); state.timer = setTimeout(load, 1800); return; }
      if (bot.status === 'failed') return renderFailed(bot);
      document.title = (bot.name || 'Dashboard') + ' · Greetwell';
      document.getElementById('top-actions').classList.remove('hidden');
      document.getElementById('preview-link').href = '/preview.html?bot=' + encodeURIComponent(botId);
      return Promise.all([refreshLeads(), refreshSessions()]).then(render);
    }).catch(function (err) {
      if (err.status === 403 || err.status === 404) fatal('This dashboard link isn\'t valid', 'The assistant may have been deleted, or the link is incomplete.');
      else fatal('Could not load the dashboard', err.message);
    });
  }

  function refreshLeads() { return api('GET', '/bots/' + botId + '/leads').then(function (d) { state.leads = d.leads; }); }
  function refreshSessions() { return api('GET', '/bots/' + botId + '/sessions').then(function (d) { state.sessions = d.sessions; }); }

  function renderBuilding(bot) {
    var current = Math.max(0, STAGES.findIndex(function (s) { return s[0] === bot.stage; }));
    mount(h('div', { class: 'center' }, h('div', { class: 'box' },
      h('div', { class: 'spinner' }),
      h('h1', { text: 'Building your assistant' }),
      h('p', { class: 'muted', text: bot.url ? 'Reading ' + bot.url.replace(/^https?:\/\//, '').replace(/\/$/, '') + '. This usually takes under a minute.' : 'This usually takes under a minute.' }),
      h('ul', { class: 'steps' }, STAGES.slice(0, 3).map(function (stage, index) {
        return h('li', { class: index < current ? 'done' : index === current ? 'now' : '', text: stage[1] });
      })))));
  }

  function renderFailed(bot) {
    mount(h('div', { class: 'center' }, h('div', { class: 'box' },
      h('h1', { text: 'We couldn\'t build your assistant' }),
      h('p', { class: 'alert', text: bot.error || 'Something went wrong.' }),
      h('p', { style: 'margin-top:22px' }, h('a', { class: 'btn', href: '/#build', text: 'Try again' })))));
  }

  // ------------------------------------------------------------ layout

  function render() {
    var bot = state.bot;
    var tabs = [['overview', 'Overview'], ['leads', 'Leads', state.leads.length], ['conversations', 'Conversations', state.sessions.length], ['knowledge', 'Knowledge'], ['settings', 'Settings']];
    var views = { overview: viewOverview, leads: viewLeads, conversations: viewConversations, knowledge: viewKnowledge, settings: viewSettings };
    mount([
      h('div', { class: 'tabs', role: 'tablist' }, tabs.map(function (tab) {
        return h('button', {
          class: 'tab', role: 'tab', 'aria-selected': String(state.tab === tab[0]),
          onclick: function () { state.tab = tab[0]; render(); }
        }, tab[1], tab[2] ? h('span', { class: 'count', text: String(tab[2]) }) : null);
      })),
      h('div', { class: 'stack', role: 'tabpanel' }, views[state.tab](bot))
    ]);
  }

  function card(title, subtitle) {
    var node = h('section', { class: 'card panel' }, title ? h('h2', { text: title }) : null, subtitle ? h('p', { class: 'muted small', text: subtitle }) : null);
    for (var i = 2; i < arguments.length; i++) append(node, arguments[i]);
    return node;
  }

  // ------------------------------------------------------------ overview

  function viewOverview(bot) {
    var rate = bot.conversations ? Math.round(100 * bot.leads / bot.conversations) + '%' : '–';
    var hot = state.leads.filter(function (l) { return l.label === 'hot'; }).length;
    var stat = function (label, value, sub) {
      return h('div', { class: 'stat' }, h('div', { class: 'label', text: label }), h('div', { class: 'value', text: String(value) }), h('div', { class: 'sub', text: sub }));
    };
    return [
      h('div', { class: 'banner' },
        h('span', {}, h('strong', { text: 'Save this page\'s link. ' }), 'It is the only key to your dashboard; there is no password to reset.'),
        h('button', { class: 'btn ghost sm', onclick: function () { copy(location.href, 'Dashboard link'); }, text: 'Copy dashboard link' })),
      h('div', { class: 'stats' },
        stat('Conversations', bot.conversations || 0, 'visitors who chatted'),
        stat('Messages', bot.messages || 0, 'answered by the assistant'),
        stat('Leads', bot.leads || 0, hot + ' hot'),
        stat('Lead rate', rate, 'conversations that became leads')),
      card('Install on your website', 'Paste this one line just before the closing </body> tag, or into your site builder\'s custom code setting.',
        h('div', { class: 'snippet' },
          h('pre', { text: embedCode() }),
          h('button', { class: 'btn', onclick: function () { copy(embedCode(), 'Embed code'); }, text: 'Copy code' })),
        h('p', { class: 'hint' }, 'Not ready to install? ', h('a', { href: '/preview.html?bot=' + encodeURIComponent(botId), target: '_blank', rel: 'noopener', text: 'Try your assistant on a sample page' }), '.')),
      card('Latest leads', state.leads.length ? null : 'Leads appear here as soon as a visitor shares what they need and how to reach them.',
        state.leads.length ? leadTable(state.leads.slice(0, 5)) : null,
        state.leads.length > 5 ? h('p', { style: 'margin-top:12px' }, h('button', { class: 'btn ghost sm', onclick: function () { state.tab = 'leads'; render(); }, text: 'See all leads' })) : null)
    ];
  }

  // ------------------------------------------------------------ leads

  function leadTable(leads) {
    return h('div', { class: 'table-card' }, h('table', {},
      h('thead', {}, h('tr', {}, h('th', { text: 'Score' }), h('th', { text: 'Lead' }), h('th', { class: 'hide-sm', text: 'Wants' }), h('th', { text: 'Status' }), h('th', { class: 'hide-sm', text: 'When' }))),
      h('tbody', {}, leads.map(function (lead) {
        var select = h('select', { 'aria-label': 'Lead status', onclick: function (e) { e.stopPropagation(); }, onchange: function (e) { setStatus(lead, e.target.value); } },
          STATUSES.map(function (s) { return h('option', { value: s, selected: lead.status === s, text: s.charAt(0).toUpperCase() + s.slice(1) }); }));
        return h('tr', { tabindex: '0', onclick: function () { openLead(lead); }, onkeydown: function (e) { if (e.key === 'Enter' && e.target === e.currentTarget) openLead(lead); } },
          h('td', {}, pill(lead.label, lead.score)),
          h('td', {}, h('div', { class: 'who', text: lead.name || 'Visitor' }), h('div', { class: 'muted small', text: lead.email || lead.phone || '' })),
          h('td', { class: 'hide-sm' }, h('div', { class: 'need', text: lead.need || '' })),
          h('td', {}, select),
          h('td', { class: 'hide-sm muted small' }, when(lead.createdAt)));
      }))));
  }

  function setStatus(lead, status) {
    api('PATCH', '/bots/' + botId + '/leads/' + lead.id, { status: status })
      .then(function (updated) { Object.assign(lead, updated); toast('Marked as ' + status); })
      .catch(function (err) { toast(err.message, true); render(); });
  }

  function viewLeads() {
    var shown = state.leads.filter(function (l) { return state.filter === 'all' || l.label === state.filter; });
    var filters = h('div', { class: 'filters' },
      ['all', 'hot', 'warm', 'cold'].map(function (f) {
        var count = f === 'all' ? state.leads.length : state.leads.filter(function (l) { return l.label === f; }).length;
        return h('button', { class: 'chip', 'aria-pressed': String(state.filter === f), onclick: function () { state.filter = f; render(); }, text: f.charAt(0).toUpperCase() + f.slice(1) + ' (' + count + ')' });
      }),
      h('button', { class: 'btn ghost sm', onclick: function () { refreshLeads().then(function () { render(); toast('Leads refreshed'); }); }, text: 'Refresh' }),
      state.leads.length ? h('button', { class: 'btn ghost sm', style: 'margin-left:0', onclick: exportCsv, text: 'Export CSV' }) : null);
    if (!state.leads.length) {
      return [filters, h('div', { class: 'card empty' }, h('h3', { text: 'No leads yet' }),
        h('p', { text: 'Install the widget, or try it yourself: tell the assistant what you need and leave an email address.' }),
        h('p', { style: 'margin-top:16px' }, h('a', { class: 'btn', href: '/preview.html?bot=' + encodeURIComponent(botId), target: '_blank', rel: 'noopener', text: 'Try the assistant' })))];
    }
    return [filters, shown.length ? h('div', { class: 'card', style: 'padding:6px 8px' }, leadTable(shown)) : h('div', { class: 'card empty', text: 'No ' + state.filter + ' leads.' })];
  }

  function exportCsv() {
    var columns = ['createdAt', 'label', 'score', 'status', 'name', 'email', 'phone', 'company', 'need', 'budget', 'timeline', 'intent', 'notes', 'pageUrl'];
    var cell = function (value) {
      var text = value == null ? '' : String(value);
      if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;  // stop spreadsheets running it as a formula
      return '"' + text.replace(/"/g, '""') + '"';
    };
    var rows = [columns.join(',')].concat(state.leads.map(function (lead) { return columns.map(function (c) { return cell(lead[c]); }).join(','); }));
    var link = h('a', { href: URL.createObjectURL(new Blob(['﻿' + rows.join('\r\n')], { type: 'text/csv' })), download: 'greetwell-leads.csv' });
    document.body.appendChild(link); link.click(); link.remove();
  }

  // ------------------------------------------------------------ drawer

  function drawer(title, headExtra, body) {
    closeDrawer();
    var overlay = h('div', { class: 'overlay', onclick: closeDrawer });
    var panel = h('aside', { class: 'drawer', role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
      h('div', { class: 'drawer-head' }, h('div', {}, h('h2', { text: title }), headExtra), h('button', { class: 'btn ghost sm', onclick: closeDrawer, text: 'Close' })),
      h('div', { class: 'drawer-body' }, body));
    document.body.appendChild(overlay); document.body.appendChild(panel);
    panel.querySelector('button').focus();
  }
  function closeDrawer() { document.querySelectorAll('.overlay, .drawer').forEach(function (n) { n.remove(); }); }
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeDrawer(); });

  function transcript(sessionId) {
    var box = h('div', { class: 'transcript' }, h('span', { class: 'muted small', text: 'Loading conversation…' }));
    api('GET', '/bots/' + botId + '/sessions/' + sessionId).then(function (session) {
      box.textContent = '';
      session.messages.forEach(function (m) { box.appendChild(h('div', { class: 'b ' + (m.r === 'u' ? 'me' : 'them'), text: m.t })); });
    }).catch(function (err) { box.textContent = ''; box.appendChild(h('span', { class: 'muted small', text: err.message })); });
    return box;
  }

  function openLead(lead) {
    var rows = [['Email', lead.email], ['Phone', lead.phone], ['Company', lead.company], ['Wants', lead.need], ['Budget', lead.budget], ['Timeline', lead.timeline], ['Notes', lead.notes], ['Page', lead.pageUrl], ['Captured', lead.createdAt && new Date(lead.createdAt).toLocaleString()]];
    var contact = lead.email ? h('a', { class: 'btn sm', href: 'mailto:' + lead.email, text: 'Email ' + (lead.name || 'lead') })
      : lead.phone ? h('a', { class: 'btn sm', href: 'tel:' + lead.phone.replace(/[^\d+]/g, ''), text: 'Call ' + (lead.name || 'lead') }) : null;
    drawer(lead.name || 'Visitor', h('div', { class: 'row', style: 'margin-top:6px' }, pill(lead.label, lead.score), h('span', { class: 'pill plain', text: lead.status })), [
      h('div', {}, h('h3', { text: 'Why this score' }), h('div', { class: 'tags' }, (lead.reasons || []).map(function (r) { return h('span', { class: 'pill plain', text: r }); }))),
      h('div', {}, h('h3', { text: 'Details' }), h('dl', { class: 'kv' }, rows.filter(function (r) { return r[1]; }).map(function (r) { return [h('dt', { text: r[0] }), h('dd', { text: r[1] })]; })),
        contact ? h('p', { style: 'margin-top:14px' }, contact) : null),
      h('div', {}, h('h3', { text: 'Conversation' }), transcript(lead.sessionId || lead.id))
    ]);
  }

  // ------------------------------------------------------------ conversations

  function viewConversations() {
    if (!state.sessions.length) {
      return h('div', { class: 'card empty' }, h('h3', { text: 'No conversations yet' }), h('p', { text: 'Every chat with your assistant shows up here, whether or not it becomes a lead.' }));
    }
    return card('Conversations', 'The most recent 100. Conversations are deleted automatically after 45 days.',
      h('ul', { class: 'list' }, state.sessions.map(function (s) {
        return h('li', {}, h('div', { class: 'row', style: 'justify-content:space-between' },
          h('button', { class: 'build-alt', style: 'text-align:left;font-size:15px', onclick: function () { drawer('Conversation', h('div', { class: 'muted small', text: (s.count || 0) + ' messages · ' + ago(s.updatedAt) }), [h('div', {}, transcript(s.id))]); }, text: s.preview || '(no text)' }),
          h('span', { class: 'row muted small' }, s.hasLead ? h('span', { class: 'pill ok', text: 'Lead' }) : null, h('span', { text: (s.count || 0) + ' msg' }), when(s.updatedAt))));
      })));
  }

  // ------------------------------------------------------------ knowledge

  function viewKnowledge(bot) {
    var profile = bot.profile || {};
    var notes = h('textarea', { rows: '6', maxlength: '6000', value: bot.notes || '', placeholder: 'Example: We are closed on public holidays. Until 31 October, new customers get 10% off.' });
    var canRefresh = bot.sourceType === 'url';
    return [
      bot.error ? h('div', { class: 'alert', text: 'The last refresh failed, so the assistant is still using what it learned before. ' + bot.error }) : null,
      card('What your assistant knows', profile.one_liner || null,
        profile.summary ? h('p', { text: profile.summary }) : null,
        (profile.offerings || []).length ? h('div', { class: 'tags', style: 'margin-top:14px' }, profile.offerings.map(function (o) { return h('span', { class: 'pill plain', text: o }); })) : null,
        (profile.faqs || []).length ? h('ul', { class: 'list', style: 'margin-top:14px' }, profile.faqs.map(function (f) { return h('li', {}, h('strong', { text: f.q }), h('div', { class: 'muted', text: f.a })); })) : null),
      card('Pages it learned from', Math.round((bot.kbChars || 0) / 1000) + 'k characters of text · last read ' + ago(bot.kbVersion),
        h('ul', { class: 'list' }, (bot.pages || []).map(function (p) {
          return h('li', { class: 'row', style: 'justify-content:space-between' },
            p.url ? h('a', { href: p.url, target: '_blank', rel: 'noopener noreferrer', text: p.title || p.url }) : h('span', { text: p.title || 'Your description' }),
            h('span', { class: 'muted small', text: Math.max(1, Math.round(p.chars / 100) / 10) + 'k chars' }));
        })),
        canRefresh ? h('p', { style: 'margin-top:14px' }, h('button', { class: 'btn ghost sm', disabled: bot.rebuilding, onclick: rebuild, text: bot.rebuilding ? 'Re-reading your site…' : 'Re-read my website' }),
          h('span', { class: 'hint', style: 'margin-left:10px', text: 'Use this after you update your site.' })) : null),
      card('Notes for your assistant', 'Facts that aren\'t on your website. The assistant treats these as true.',
        notes,
        h('p', { style: 'margin-top:12px' }, h('button', { class: 'btn sm', onclick: function () { saveSettings({ notes: notes.value }, 'Notes saved'); }, text: 'Save notes' })))
    ];
  }

  function rebuild() {
    api('POST', '/bots/' + botId + '/rebuild').then(function () {
      state.bot.rebuilding = true; render(); toast('Re-reading your website…');
      var poll = function () {
        api('GET', '/bots/' + botId).then(function (bot) {
          state.bot = bot;
          if (bot.rebuilding) return setTimeout(poll, 2000);
          render(); toast(bot.error ? 'Refresh failed' : 'Knowledge updated', !!bot.error);
        });
      };
      setTimeout(poll, 2000);
    }).catch(function (err) { toast(err.message, true); });
  }

  // ------------------------------------------------------------ settings

  function saveSettings(changes, message) {
    return api('PATCH', '/bots/' + botId, changes).then(function (bot) {
      state.bot = bot;
      document.getElementById('bot-name').textContent = bot.name || '';
      toast(message || 'Saved');
      return bot;
    }).catch(function (err) { toast(err.message, true); });
  }

  function viewSettings(bot) {
    var name = h('input', { type: 'text', id: 'f-name', maxlength: '60', value: bot.name || '' });
    var color = h('input', { type: 'color', id: 'f-color', value: bot.color || '#4f46e5' });
    var greeting = h('textarea', { id: 'f-greeting', rows: '2', maxlength: '300', value: bot.greeting || '', style: 'min-height:64px' });
    var starters = h('textarea', { id: 'f-starters', rows: '3', value: (bot.starters || []).join('\n'), style: 'min-height:84px' });
    var questions = h('textarea', { id: 'f-questions', rows: '4', value: (bot.questions || []).join('\n') });
    var webhook = h('input', { type: 'url', id: 'f-webhook', maxlength: '500', value: bot.webhookUrl || '', placeholder: 'https://hooks.slack.com/services/…' });
    var field = function (label, input, hint) { return h('div', { class: 'field' }, h('label', { for: input.id, text: label }), input, hint ? h('div', { class: 'hint', text: hint }) : null); };

    return [
      card('Assistant', 'Changes apply to your live widget straight away.',
        h('div', { class: 'field-row' }, field('Name', name, 'Shown at the top of the chat window.'), field('Colour', color, 'Match your brand.')),
        field('Greeting', greeting, 'The first thing visitors see.'),
        field('Starter questions', starters, 'One per line, up to 4. Shown as buttons before the visitor types.'),
        field('Qualifying questions', questions, 'One per line, up to 6. What you need to know to tell a serious enquiry from a casual one.'),
        h('button', { class: 'btn', text: 'Save changes', onclick: function () {
          saveSettings({ name: name.value, color: color.value, greeting: greeting.value, starters: lines(starters.value), questions: lines(questions.value) });
        } })),
      card('Send leads to Slack, Zapier or your CRM', 'Each new lead is sent to this address as JSON the moment it is captured. The payload has a "text" summary, so a Slack incoming webhook works as is.',
        field('Webhook address', webhook),
        h('div', { class: 'row' },
          h('button', { class: 'btn sm', text: 'Save webhook', onclick: function () { saveSettings({ webhookUrl: webhook.value.trim() }, 'Webhook saved'); } }),
          h('button', { class: 'btn ghost sm', text: 'Send a test lead', onclick: function () {
            api('POST', '/bots/' + botId + '/webhook-test').then(function (r) { toast(r.ok ? 'Test lead delivered' : 'The webhook answered with status ' + r.status, !r.ok); }).catch(function (err) { toast(err.message, true); });
          } }))),
      card('Delete this assistant', 'Removes the assistant, its knowledge, every conversation and every lead. This cannot be undone, and the widget stops appearing on your site.',
        h('button', { class: 'btn danger', text: 'Delete assistant and all data', onclick: function () {
          if (!window.confirm('Delete "' + (bot.name || 'this assistant') + '" and all of its leads and conversations? This cannot be undone.')) return;
          api('DELETE', '/bots/' + botId).then(function () {
            try {
              var saved = JSON.parse(localStorage.getItem('greetwell:bots')) || [];
              localStorage.setItem('greetwell:bots', JSON.stringify(saved.filter(function (b) { return b.id !== botId; })));
            } catch (e) { /* private mode */ }
            location.href = '/';
          }).catch(function (err) { toast(err.message, true); });
        } }))
    ];
  }

  boot();
})();
