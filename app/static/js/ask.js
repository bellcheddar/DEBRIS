/* 06 DEBRIS LLM: a question built from three fixed choices, answered from the corpus.
   The lead sentence and every count come from the database; the reading under it was
   written offline by the model from the papers listed (D69). The choices live in the URL,
   so an answer can be shared. */
(() => {
  const el = (id) => document.getElementById(id);
  const po = el('ask-po'), pl = el('ask-pl'), q = el('ask-q'), out = el('ask-answer');
  let B = null;

  function readUrl() {
    const u = new URLSearchParams(location.search);
    const ok = (sel, v) => v && [...sel.options].some((o) => o.value === v);
    if (ok(po, u.get('plastic'))) po.value = u.get('plastic');
    if (ok(pl, u.get('body'))) pl.value = u.get('body');
    if (ok(q, u.get('q'))) q.value = u.get('q');
  }

  function writeUrl() {
    const u = new URLSearchParams({ plastic: po.value, body: pl.value, q: q.value });
    history.replaceState(null, '', `${location.pathname}?${u}`);
  }

  function papersQuery(r) {
    const u = new URLSearchParams({ organs: pl.value, rungs: String(r) });
    if (po.value !== 'ANY') u.set('polymers', po.value);
    return u.toString();
  }

  function draw() {
    const r = +q.value;
    const cell = B.cells[`${po.value}|${pl.value}`];
    const a = B.answers[`${po.value}|${pl.value}|${r}`];
    const place = B.places.find((x) => x.k === pl.value);
    const plastic = B.plastics.find((x) => x.k === po.value);
    const ladder = B.questions.map((x, i) => `<button type="button" data-r="${x.r}" aria-pressed="${x.r === r}">
        <span class="c">${DEBRIS.fmt(cell.ladder[i])}</span><span class="l">${x.short}</span></button>`).join('');
    const papers = a.papers.map((p) => `<li><a href="/papers?q=${p[0]}" data-pmid="${p[0]}">${DEBRIS.esc(p[1])}</a>
        <span class="src">${DEBRIS.esc(p[2] || '')} ${p[3] || ''}</span></li>`).join('');
    const mech = r === 4 && cell.paths.length
      ? `<div class="askmech"><span class="lab">Commonest mechanisms</span>${cell.paths.map((m) =>
        `<span class="tag">${DEBRIS.esc(m[0])} ${m[1]}</span>`).join('')}</div>` : '';
    const caveat = r === 2 && a.n
      ? '<p class="askcaveat">These are associations. They do not show that plastics cause the problem.</p>' : '';
    out.innerHTML = `
      <p class="asklead">${DEBRIS.esc(a.lead)}</p>
      ${a.reading ? `<p class="askreading">${DEBRIS.esc(a.reading)}</p>` : ''}
      ${caveat}
      <div class="askctx">${DEBRIS.fmt(cell.total)} papers in all on ${DEBRIS.esc(plastic.name)} and
        ${DEBRIS.esc(place.l)}. Each step of the evidence ladder:</div>
      <div class="askladder" role="group" aria-label="Evidence ladder">${ladder}</div>
      ${mech}
      ${a.papers.length ? `<h3 class="askhead">Newest papers</h3><ol class="askpapers">${papers}</ol>
        <a class="btn" href="/papers?${papersQuery(r)}">Open in Papers (${DEBRIS.fmt(a.n)})</a>` : ''}
      <p class="asknote">${a.reading
        ? 'The counted sentence comes from the database. The sentences under it were written by a language model from the papers listed, and checked for causal claims before publication.'
        : 'The counted sentence comes from the database.'}</p>`;
    out.querySelectorAll('.askladder button').forEach((b) => b.addEventListener('click', () => {
      q.value = b.dataset.r; changed();
    }));
  }

  // Each drop-down is as wide as the words chosen in it, so the sentence reads as one.
  const ruler = document.createElement('span');
  ruler.className = 'askruler';
  document.body.appendChild(ruler);
  function fit() {
    [po, pl, q].forEach((s) => {
      const cs = getComputedStyle(s);
      ruler.style.font = cs.font;
      ruler.textContent = s.options[s.selectedIndex] ? s.options[s.selectedIndex].text : '';
      s.style.width = `${Math.ceil(ruler.getBoundingClientRect().width) + 40}px`;
    });
  }
  window.addEventListener('resize', fit);

  function changed() { writeUrl(); fit(); draw(); }

  out.addEventListener('click', (e) => {
    const a = e.target.closest('a[data-pmid]');
    if (!a) return;
    e.preventDefault();
    DEBRIS.openPaper(a.dataset.pmid);
  });

  fetch(window.ASK_URL).then((r) => r.json()).then((data) => {
    B = data;
    po.innerHTML = B.plastics.map((x) => `<option value="${x.k}">${DEBRIS.esc(x.l)}</option>`).join('');
    pl.innerHTML = B.places.map((x) => `<option value="${x.k}">${DEBRIS.esc(x.l)}</option>`).join('');
    q.innerHTML = B.questions.map((x) => `<option value="${x.r}">${DEBRIS.esc(x.l)}</option>`).join('');
    po.value = 'PET'; pl.value = 'reproductive_placental'; q.value = '1';
    readUrl();
    [po, pl, q].forEach((s) => s.addEventListener('change', changed));
    fit();
    draw();
    if (document.fonts) document.fonts.ready.then(fit);
  }).catch(() => {
    out.innerHTML = '<p class="empty">The answers could not be loaded. Try again in a moment.</p>';
  });
})();
