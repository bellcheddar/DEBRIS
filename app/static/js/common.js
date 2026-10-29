/* DEBRIS shared front-end helpers: tokens, Plotly defaults, chips, the paper drawer.
   Every colour comes from the CSS custom properties so the Elora tokens stay the
   single source of truth (spec 6.2). */
const DEBRIS = (() => {
  const css = (name) => getComputedStyle(document.documentElement)
    .getPropertyValue(name).trim();

  const T = {
    blue: css('--el-blue'), ink: css('--el-ink'), soft: css('--el-soft'),
    tint: css('--el-tint'), muted: css('--el-muted'), line: css('--el-line'),
    card: css('--el-card'), fg: css('--el-fg'),
    pet: css('--pet'), ps: css('--ps'), pepp: css('--pe-pp'), pvc: css('--pvc'),
    other: css('--other'), new: css('--new'),
  };

  // PET is --pet in every chart (spec 6.2); the rest fall back to the Elora ramp.
  const POLYMER_COLOUR = {
    PET: T.pet, PS: T.ps, PE: T.pepp, PP: T.pepp, PVC: T.pvc,
  };
  const colourFor = (key) => POLYMER_COLOUR[key] || T.other;

  const FONT = { family: 'Montserrat, Helvetica, Arial, sans-serif', size: 12, color: T.fg };
  const layout = (extra = {}) => Object.assign({
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: FONT, margin: { l: 56, r: 18, t: 14, b: 44 },
    xaxis: { gridcolor: T.line, zerolinecolor: T.line, tickfont: { size: 11, color: T.muted } },
    yaxis: { gridcolor: T.line, zerolinecolor: T.line, tickfont: { size: 11, color: T.muted } },
    hoverlabel: { bgcolor: T.ink, font: { family: FONT.family, size: 12, color: '#fff' } },
    legend: { font: { size: 11, color: T.muted }, orientation: 'h', y: -0.18 },
  }, extra);
  const config = { displayModeBar: false, responsive: true };

  const plot = (id, traces, extraLayout = {}) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (!traces || !traces.length) { el.innerHTML = '<p class="empty">No data yet.</p>'; return; }
    Plotly.newPlot(el, traces, layout(extraLayout), config);
  };

  const fmt = (n) => (n === null || n === undefined) ? '0' : n.toLocaleString('en-GB');

  const label = (dict, key) => (dict && dict[key]) || key;

  /* Chip groups: one pressed at a time, callback with the chosen value. */
  const chips = (selector, onChange) => {
    const group = document.querySelectorAll(selector);
    group.forEach((chip) => chip.addEventListener('click', () => {
      group.forEach((c) => c.setAttribute('aria-pressed', c === chip ? 'true' : 'false'));
      onChange(chip.dataset.value, chip);
    }));
  };

  const polymerTagClass = (p) => ({ PET: 'pet', PS: 'ps', PE: 'pepp', PP: 'pepp', PVC: 'pvc' }[p] || 'other');

  /* The detail drawer, shared by the Papers table and the Body panel. */
  async function openPaper(pmid) {
    const drawer = document.getElementById('drawer');
    if (!drawer) { window.location = '/papers?q=' + pmid; return; }
    drawer.removeAttribute('inert');
    drawer.querySelector('.body').innerHTML = '<p class="empty">Loading…</p>';
    let p;
    try {
      const res = await fetch('/paper/' + encodeURIComponent(pmid));
      if (!res.ok) throw new Error(res.status);
      p = await res.json();
    } catch (err) {
      drawer.querySelector('.body').innerHTML = '<p class="empty">Could not load this paper.</p>';
      return;
    }
    const chipsHtml = (arr, cls) => (arr || []).map((v) =>
      `<span class="tag ${cls === 'poly' ? polymerTagClass(v) : ''}">${esc(v)}</span>`).join(' ');
    const doiLink = p.doi ? `<a href="https://doi.org/${esc(p.doi)}" class="mono">${esc(p.doi)}</a>` : '<span class="mono">none</span>';
    drawer.querySelector('h2').innerHTML = (p.retracted ? '<span class="badge-novel">Retracted</span> ' : '') + esc(p.title || '');
    drawer.querySelector('.body').innerHTML = `
      <dl>
        <dt>PMID</dt><dd><a class="mono" href="https://pubmed.ncbi.nlm.nih.gov/${esc(p.pmid)}/">${esc(p.pmid)}</a></dd>
        <dt>DOI</dt><dd>${doiLink} <span class="tag">${esc(p.doi_status || 'unknown')}</span></dd>
        <dt>Journal</dt><dd>${esc(p.journal || '')} ${p.year ? '(' + p.year + ')' : ''}</dd>
        <dt>Polymers</dt><dd>${chipsHtml(p.polymers, 'poly') || '<span class="empty">untagged</span>'}</dd>
        <dt>Organs</dt><dd>${chipsHtml(p.organ_systems) || '—'}</dd>
        <dt>Pathways</dt><dd>${chipsHtml(p.pathways) || '—'}</dd>
        <dt>Rungs</dt><dd>${(p.rungs || []).map((r) => `<span class="tag rung">${r}</span>`).join(' ') || '—'}</dd>
        <dt>Model</dt><dd>${esc(p.model_type || '—')} · ${esc(p.size_class || '—')}</dd>
        <dt>Confidence</dt><dd class="mono">${p.confidence !== null && p.confidence !== undefined ? p.confidence.toFixed(2) : '—'} · self-consistency ${p.self_consistency !== null && p.self_consistency !== undefined ? p.self_consistency.toFixed(2) : '—'}</dd>
        <dt>Tag source</dt><dd>${esc(p.tag_source || 'untagged')} ${p.model_version ? '· ' + esc(p.model_version) : ''}</dd>
        ${p.review ? `<dt>Review</dt><dd>${esc(p.review.reason)}</dd>` : ''}
        ${(p.novelty || []).length ? `<dt>Novel</dt><dd>${p.novelty.map((n) => `<span class="tag">${esc(n.kind)}: ${esc(n.key)}</span>`).join(' ')}</dd>` : ''}
      </dl>
      ${p.summary ? `<p class="abstract"><b>Tagged summary.</b> ${esc(p.summary)}</p>` : ''}
      <h3 style="font-size:10px;letter-spacing:0.3em;text-transform:uppercase;color:var(--el-muted);margin-top:18px">Abstract</h3>
      <p class="abstract">${esc(p.abstract || 'No abstract in the PubMed record.')}</p>
      ${p.mesh ? `<h3 style="font-size:10px;letter-spacing:0.3em;text-transform:uppercase;color:var(--el-muted);margin-top:16px">MeSH</h3><p class="abstract">${esc(p.mesh)}</p>` : ''}
      ${p.tag_json ? `<h3 style="font-size:10px;letter-spacing:0.3em;text-transform:uppercase;color:var(--el-muted);margin-top:16px">Tag JSON</h3><pre>${esc(JSON.stringify(p.tag, null, 1))}</pre>` : ''}
    `;
  }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function wireDrawer() {
    const drawer = document.getElementById('drawer');
    if (!drawer) return;
    const close = () => drawer.setAttribute('inert', '');
    drawer.querySelector('.close').addEventListener('click', close);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
  }

  document.addEventListener('DOMContentLoaded', wireDrawer);
  return { T, colourFor, layout, config, plot, fmt, chips, openPaper, esc, label, polymerTagClass };
})();
