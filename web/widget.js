/*! Greetwell chat widget. Embed with:
 *  <script src="https://YOUR-SITE/widget.js" data-bot="BOT_ID" async></script>
 * Optional attributes: data-open="true" (start open), data-position="left".
 */
(function () {
  'use strict';
  var script = document.currentScript;
  if (!script) return;
  var botId = script.getAttribute('data-bot');
  if (!botId) return;
  window.__greetwell = window.__greetwell || {};
  if (window.__greetwell[botId]) return;
  window.__greetwell[botId] = true;

  var base = new URL(script.src, location.href).origin;
  var startOpen = script.getAttribute('data-open') === 'true';
  var onLeft = script.getAttribute('data-position') === 'left';
  var storeKey = 'greetwell:' + botId;
  var MAX_LEN = 1000;

  function load() {
    try { return JSON.parse(localStorage.getItem(storeKey)) || {}; } catch (e) { return {}; }
  }
  function save() {
    try { localStorage.setItem(storeKey, JSON.stringify({ sid: state.sid, messages: state.messages.slice(-40) })); } catch (e) { /* private mode */ }
  }
  function newSessionId() {
    var bytes = new Uint8Array(18);
    (window.crypto || window.msCrypto).getRandomValues(bytes);
    return 's_' + Array.prototype.map.call(bytes, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
  }

  var saved = load();
  var state = { sid: saved.sid || newSessionId(), messages: saved.messages || [], open: false, busy: false, bot: null };

  function el(tag, props, children) {
    var node = document.createElement(tag);
    Object.keys(props || {}).forEach(function (key) {
      if (key === 'text') node.textContent = props[key];
      else if (key === 'class') node.className = props[key];
      else node.setAttribute(key, props[key]);
    });
    (children || []).forEach(function (child) { node.appendChild(child); });
    return node;
  }

  // Render message text safely: plain text nodes, with http(s) links made clickable.
  function fillText(node, text) {
    var pattern = /(https?:\/\/[^\s<>"')]+)/g, last = 0, match;
    while ((match = pattern.exec(text))) {
      node.appendChild(document.createTextNode(text.slice(last, match.index)));
      node.appendChild(el('a', { href: match[1], target: '_blank', rel: 'noopener noreferrer nofollow', text: match[1] }));
      last = match.index + match[1].length;
    }
    node.appendChild(document.createTextNode(text.slice(last)));
  }

  function readableOn(hex) {
    var r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
    return (0.299 * r + 0.587 * g + 0.114 * b) > 165 ? '#111827' : '#ffffff';
  }

  var CSS = [
    ':host{all:initial}',
    '*{box-sizing:border-box;font-family:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}',
    '.root{position:fixed;bottom:20px;z-index:2147483000;color:#111827;font-size:15px;line-height:1.45}',
    '.root.right{right:20px}.root.left{left:20px}',
    '.launcher{width:58px;height:58px;border-radius:50%;border:0;cursor:pointer;background:var(--brand);color:var(--on-brand);',
    'box-shadow:0 8px 24px rgba(15,23,42,.25);display:flex;align-items:center;justify-content:center;transition:transform .15s ease}',
    '.launcher:hover{transform:scale(1.06)}.launcher:focus-visible,.send:focus-visible,.chip:focus-visible,.close:focus-visible{outline:3px solid rgba(99,102,241,.5);outline-offset:2px}',
    '.launcher svg{width:26px;height:26px}',
    '.panel{position:absolute;bottom:72px;width:380px;max-width:calc(100vw - 24px);height:560px;max-height:calc(100vh - 110px);',
    'background:#fff;border-radius:16px;box-shadow:0 18px 50px rgba(15,23,42,.28);display:none;flex-direction:column;overflow:hidden;border:1px solid rgba(15,23,42,.08)}',
    '.right .panel{right:0}.left .panel{left:0}',
    '.open .panel{display:flex;animation:pop .18s ease-out}',
    '@keyframes pop{from{opacity:0;transform:translateY(8px) scale(.98)}to{opacity:1;transform:none}}',
    '.head{background:var(--brand);color:var(--on-brand);padding:14px 16px;display:flex;align-items:center;gap:10px}',
    '.avatar{width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,.22);display:flex;align-items:center;justify-content:center;font-weight:700;flex:none}',
    '.title{font-weight:650;font-size:15px;line-height:1.2}.sub{font-size:12px;opacity:.85}',
    '.close{margin-left:auto;background:transparent;border:0;color:inherit;cursor:pointer;padding:6px;border-radius:8px;display:flex}',
    '.close:hover{background:rgba(255,255,255,.18)}.close svg{width:18px;height:18px}',
    '.log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px;background:#f8fafc}',
    '.msg{max-width:84%;padding:10px 13px;border-radius:14px;white-space:pre-wrap;word-wrap:break-word;overflow-wrap:anywhere}',
    '.msg a{color:inherit;text-decoration:underline}',
    '.bot{background:#fff;border:1px solid #e5e7eb;align-self:flex-start;border-bottom-left-radius:4px}',
    '.user{background:var(--brand);color:var(--on-brand);align-self:flex-end;border-bottom-right-radius:4px}',
    '.note{align-self:center;font-size:12px;color:#047857;background:#ecfdf5;border:1px solid #a7f3d0;padding:4px 10px;border-radius:999px}',
    '.err{align-self:center;font-size:12.5px;color:#b91c1c;background:#fef2f2;border:1px solid #fecaca;padding:6px 10px;border-radius:10px;text-align:center}',
    '.typing{display:flex;gap:4px;align-items:center;padding:13px}',
    '.typing i{width:7px;height:7px;border-radius:50%;background:#9ca3af;animation:blink 1.2s infinite ease-in-out}',
    '.typing i:nth-child(2){animation-delay:.15s}.typing i:nth-child(3){animation-delay:.3s}',
    '@keyframes blink{0%,80%,100%{opacity:.3;transform:translateY(0)}40%{opacity:1;transform:translateY(-3px)}}',
    '.chips{display:flex;flex-wrap:wrap;gap:6px;padding:0 16px 10px;background:#f8fafc}',
    '.chip{border:1px solid #d1d5db;background:#fff;border-radius:999px;padding:6px 11px;font-size:13px;cursor:pointer;color:#111827}',
    '.chip:hover{border-color:var(--brand)}',
    '.form{display:flex;gap:8px;padding:10px 12px;border-top:1px solid #e5e7eb;background:#fff;align-items:flex-end}',
    'textarea{flex:1;resize:none;border:1px solid #d1d5db;border-radius:12px;padding:9px 11px;font-size:15px;line-height:1.35;max-height:96px;min-height:40px;outline:none;color:#111827;background:#fff}',
    'textarea:focus{border-color:var(--brand);box-shadow:0 0 0 3px rgba(99,102,241,.15)}',
    '.send{width:40px;height:40px;border-radius:12px;border:0;background:var(--brand);color:var(--on-brand);cursor:pointer;display:flex;align-items:center;justify-content:center;flex:none}',
    '.send:disabled{opacity:.45;cursor:default}.send svg{width:18px;height:18px}',
    '.foot{font-size:11px;color:#6b7280;text-align:center;padding:0 12px 9px;background:#fff}',
    '.foot a{color:inherit}',
    '@media (max-width:480px){.root{bottom:14px}.root.right{right:14px}.root.left{left:14px}',
    '.panel{position:fixed;inset:0;width:100vw;max-width:100vw;height:100%;max-height:100%;border-radius:0;border:0}.open .launcher{display:none}}',
    '@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}'
  ].join('');

  var ICON_CHAT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>';
  var ICON_CLOSE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  var ICON_SEND = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';

  var ui = {};

  function build(bot) {
    var host = el('div', { id: 'greetwell-' + botId });
    var shadow = host.attachShadow({ mode: 'open' });
    shadow.appendChild(el('style', { text: CSS }));

    ui.root = el('div', { class: 'root ' + (onLeft ? 'left' : 'right') });
    ui.root.style.setProperty('--brand', bot.color);
    ui.root.style.setProperty('--on-brand', readableOn(bot.color));

    ui.log = el('div', { class: 'log', role: 'log', 'aria-live': 'polite' });
    ui.chips = el('div', { class: 'chips' });
    ui.input = el('textarea', { rows: '1', placeholder: 'Type your message…', 'aria-label': 'Message', maxlength: String(MAX_LEN) });
    ui.send = el('button', { class: 'send', type: 'submit', 'aria-label': 'Send message' });
    ui.send.innerHTML = ICON_SEND;
    var form = el('form', { class: 'form' }, [ui.input, ui.send]);

    var close = el('button', { class: 'close', type: 'button', 'aria-label': 'Close chat' });
    close.innerHTML = ICON_CLOSE;
    var head = el('div', { class: 'head' }, [
      el('div', { class: 'avatar', text: (bot.name || 'A').trim().charAt(0).toUpperCase(), 'aria-hidden': 'true' }),
      el('div', {}, [el('div', { class: 'title', text: bot.name }), el('div', { class: 'sub', text: 'AI assistant · replies instantly' })]),
      close
    ]);
    var foot = el('div', { class: 'foot' });
    foot.appendChild(document.createTextNode('AI answers can be wrong. Powered by '));
    foot.appendChild(el('a', { href: base + '/', target: '_blank', rel: 'noopener', text: 'Greetwell' }));

    ui.panel = el('div', { class: 'panel', role: 'dialog', 'aria-label': 'Chat with ' + bot.name }, [head, ui.log, ui.chips, form, foot]);
    ui.launcher = el('button', { class: 'launcher', type: 'button', 'aria-label': 'Open chat', 'aria-expanded': 'false' });
    ui.launcher.innerHTML = ICON_CHAT;
    ui.root.appendChild(ui.panel);
    ui.root.appendChild(ui.launcher);
    shadow.appendChild(ui.root);
    document.body.appendChild(host);

    ui.launcher.addEventListener('click', function () { toggle(!state.open); });
    close.addEventListener('click', function () { toggle(false); ui.launcher.focus(); });
    ui.root.addEventListener('keydown', function (e) { if (e.key === 'Escape' && state.open) { toggle(false); ui.launcher.focus(); } });
    form.addEventListener('submit', function (e) { e.preventDefault(); send(ui.input.value); });
    ui.input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(ui.input.value); }
    });
    ui.input.addEventListener('input', function () {
      ui.input.style.height = 'auto';
      ui.input.style.height = Math.min(ui.input.scrollHeight, 96) + 'px';
    });

    render();
    if (startOpen) toggle(true);
  }

  function toggle(open) {
    state.open = open;
    ui.root.classList.toggle('open', open);
    ui.launcher.setAttribute('aria-expanded', String(open));
    ui.launcher.setAttribute('aria-label', open ? 'Close chat' : 'Open chat');
    ui.launcher.innerHTML = open ? ICON_CLOSE : ICON_CHAT;
    if (open) { scrollDown(); setTimeout(function () { ui.input.focus(); }, 60); }
  }

  function scrollDown() { ui.log.scrollTop = ui.log.scrollHeight; }

  function bubble(kind, text) {
    var node = el('div', { class: kind === 'note' || kind === 'err' ? kind : 'msg ' + kind });
    fillText(node, text);
    ui.log.appendChild(node);
    return node;
  }

  function render() {
    ui.log.textContent = '';
    bubble('bot', state.bot.greeting);
    state.messages.forEach(function (m) { bubble(m.r, m.t); });
    renderChips();
    scrollDown();
  }

  function renderChips() {
    ui.chips.textContent = '';
    if (state.messages.length || state.busy) { ui.chips.style.display = 'none'; return; }
    ui.chips.style.display = '';
    (state.bot.starters || []).forEach(function (text) {
      var chip = el('button', { class: 'chip', type: 'button', text: text });
      chip.addEventListener('click', function () { send(text); });
      ui.chips.appendChild(chip);
    });
  }

  function send(raw) {
    var text = (raw || '').trim();
    if (!text || state.busy) return;
    text = text.slice(0, MAX_LEN);
    state.busy = true;
    ui.input.value = '';
    ui.input.style.height = 'auto';
    ui.send.disabled = true;
    Array.prototype.forEach.call(ui.log.querySelectorAll('.err'), function (n) { n.remove(); });
    bubble('user', text);
    renderChips();
    var typing = el('div', { class: 'msg bot typing', 'aria-label': 'Assistant is typing' }, [el('i'), el('i'), el('i')]);
    ui.log.appendChild(typing);
    scrollDown();

    fetch(base + '/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ botId: botId, sessionId: state.sid, message: text, pageUrl: location.href.slice(0, 300) })
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) { return { ok: res.ok, data: data }; });
    }).then(function (result) {
      typing.remove();
      if (!result.ok) {
        ui.log.lastChild && ui.log.lastChild.classList.contains('user') && ui.log.lastChild.remove();
        ui.input.value = text;
        bubble('err', result.data.error || 'Something went wrong. Please try again.');
        return;
      }
      state.messages.push({ r: 'user', t: text }, { r: 'bot', t: result.data.reply });
      bubble('bot', result.data.reply);
      if (result.data.leadCaptured) bubble('note', '✓ Your details were passed to the team');
      save();
    }).catch(function () {
      typing.remove();
      ui.log.lastChild && ui.log.lastChild.classList.contains('user') && ui.log.lastChild.remove();
      ui.input.value = text;
      bubble('err', 'You seem to be offline. Check your connection and try again.');
    }).then(function () {
      state.busy = false;
      ui.send.disabled = false;
      scrollDown();
      if (state.open) ui.input.focus();
    });
  }

  function start() {
    fetch(base + '/api/bots/' + encodeURIComponent(botId) + '/public')
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (bot) {
        // Stay invisible unless the assistant exists and is ready to answer.
        if (!bot || bot.status !== 'ready') return;
        state.bot = bot;
        build(bot);
      })
      .catch(function () { /* never break the host page */ });
  }

  if (document.body) start();
  else document.addEventListener('DOMContentLoaded', start);
})();
