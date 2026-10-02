(function () {
  'use strict';
  var form = document.getElementById('build-form');
  var urlMode = document.getElementById('url-mode');
  var textMode = document.getElementById('text-mode');
  var toggle = document.getElementById('mode-toggle');
  var errorBox = document.getElementById('form-error');
  var useText = false;

  function savedBots() {
    try { return JSON.parse(localStorage.getItem('greetwell:bots')) || []; } catch (e) { return []; }
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.classList.toggle('hidden', !message);
  }

  toggle.addEventListener('click', function () {
    useText = !useText;
    urlMode.classList.toggle('hidden', useText);
    textMode.classList.toggle('hidden', !useText);
    toggle.textContent = useText ? 'Use my website address instead' : 'No website? Describe your business instead';
    showError('');
    document.getElementById(useText ? 'text' : 'url').focus();
  });

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    showError('');
    var body = useText
      ? { text: document.getElementById('text').value.trim() }
      : { url: document.getElementById('url').value.trim() };
    if (!useText && !body.url) return showError('Enter your website address.');
    if (useText && body.text.length < 80) return showError('Tell us a little more: a few sentences about what you offer.');

    var buttons = form.querySelectorAll('button[type=submit]');
    buttons.forEach(function (b) { b.disabled = true; b.textContent = 'Starting…'; });
    fetch('/api/bots', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (res) { return res.json().then(function (data) { return { ok: res.ok, data: data }; }); })
      .then(function (result) {
        if (!result.ok) throw new Error(result.data.error || 'Something went wrong. Please try again.');
        var bots = savedBots();
        bots.unshift({ id: result.data.botId, key: result.data.adminKey, label: body.url || 'From description', at: new Date().toISOString() });
        try { localStorage.setItem('greetwell:bots', JSON.stringify(bots.slice(0, 20))); } catch (e) { /* private mode */ }
        location.href = '/dashboard.html#' + result.data.botId + '.' + result.data.adminKey;
      })
      .catch(function (err) {
        showError(err.message === 'Failed to fetch' ? 'Could not reach the server. Check your connection and try again.' : err.message);
        buttons.forEach(function (b) { b.disabled = false; b.textContent = 'Build my assistant'; });
      });
  });

  // Returning owners: link back to the dashboards this browser created.
  var bots = savedBots();
  if (bots.length) {
    var mine = document.getElementById('mine');
    mine.classList.remove('hidden');
    mine.appendChild(document.createTextNode('Welcome back. Your assistants: '));
    bots.slice(0, 4).forEach(function (bot, index) {
      if (index) mine.appendChild(document.createTextNode(' · '));
      var link = document.createElement('a');
      link.href = '/dashboard.html#' + bot.id + '.' + bot.key;
      link.textContent = String(bot.label || bot.id).replace(/^https?:\/\//, '').replace(/\/$/, '');
      mine.appendChild(link);
    });
  }
})();
