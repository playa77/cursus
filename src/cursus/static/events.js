/* Payloads are text; only server-rendered pages determine available controls. */
(() => {
  const root = document.documentElement;
  const media = matchMedia('(prefers-color-scheme: dark)');
  function theme() {
    root.dataset.theme = root.dataset.behavior === 'system' ? (media.matches ? 'dark' : 'light') : root.dataset.behavior;
  }
  theme(); media.addEventListener('change', theme);
  document.querySelectorAll('[name="theme-behavior"]').forEach(input => {
    input.checked = input.value === root.dataset.behavior;
    input.addEventListener('change', () => {
      root.dataset.behavior = input.value; theme();
      document.cookie = `cursus_theme=${input.value}; Path=/; Max-Age=31536000; Secure; SameSite=Strict`;
    });
  });
  const filter = document.querySelector('#phase-filter');
  filter?.addEventListener('input', () => document.querySelectorAll('[data-filter]').forEach(row => {
    row.hidden = !row.textContent.toLowerCase().includes(filter.value.toLowerCase());
  }));
  const source = document.querySelector('#source-kind');
  source?.addEventListener('change', () => document.querySelectorAll('[data-source]').forEach(section => {
    section.hidden = section.dataset.source !== source.value;
  }));
  const dialog = document.querySelector('#confirmation');
  let confirmed = null;
  document.addEventListener('submit', event => {
    const form = event.target;
    if (!form.dataset.confirm || confirmed === form) { confirmed = null; return; }
    event.preventDefault(); event.stopImmediatePropagation();
    document.querySelector('#confirmation-text').textContent = form.dataset.confirm;
    dialog.returnValue = 'cancel';
    dialog.onclose = () => { if (dialog.returnValue === 'confirm') { confirmed = form; form.requestSubmit(); } };
    dialog.showModal();
  }, true);
  document.body.addEventListener('htmx:responseError', event => {
    // Failed writes preserve form UUID and input; a full safe Problem response
    // replaces content, never treats an error as a committed success.
    const doc = new DOMParser().parseFromString(event.detail.xhr.responseText, 'text/html');
    const problem = doc.querySelector('.problem');
    if (problem) document.querySelector('#main').prepend(problem);
  });
  const log = document.querySelector('[data-events]');
  if (!log) return;
  let cursor = Number(log.dataset.cursor), paused = false;
  const pause = document.querySelector('#pause-log');
  function setPause(value) { paused = value; pause.textContent = paused ? 'Resume autoscroll' : 'Pause autoscroll'; }
  pause?.addEventListener('click', () => { setPause(!paused); if (!paused) log.scrollTop = log.scrollHeight; });
  log.addEventListener('scroll', () => { if (log.scrollTop + log.clientHeight < log.scrollHeight - 10) setPause(true); });
  document.querySelector('#copy-log')?.addEventListener('click', () => navigator.clipboard.writeText(log.textContent));
  const banner = document.querySelector('#connection');
  const refresh = document.querySelector('#refresh-state');
  refresh?.addEventListener('click', () => location.reload());
  const stream = new EventSource(`${log.dataset.events}?cursor=${cursor}`);
  stream.onopen = () => { banner.hidden = true; };
  stream.onerror = () => { banner.hidden = false; };
  stream.addEventListener('reset', () => { stream.close(); location.reload(); });
  stream.addEventListener('committed', event => {
    const id = Number(event.lastEventId);
    if (!Number.isSafeInteger(id) || id <= cursor) return;
    cursor = id;
    const item = JSON.parse(event.data);
    if (!log.dataset.attempt || item.attempt_id === log.dataset.attempt || item.payload.attempt_id === log.dataset.attempt) {
      const line = document.createElement('span');
      line.className = `event-line event-kind-${item.kind}`;
      line.textContent = `${item.time} ${id} ${item.kind} ${JSON.stringify(item.payload)}\n`;
      log.append(line);
      // Bound DOM memory independently of server replay/history retention.
      while (log.childNodes.length > 500) log.firstChild.remove();
      if (!paused) log.scrollTop = log.scrollHeight;
    }
    if (!['log','usage'].includes(item.kind)) {
      refresh.hidden = false;
      // Do not discard a draft answer, steer or recovery reason.
      const editing = [...document.querySelectorAll('textarea')].some(input => input.value.trim());
      if (!editing && !dialog.open) { stream.close(); location.reload(); }
    }
  });
  addEventListener('pagehide', () => stream.close(), {once:true});
})();
