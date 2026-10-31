/* 04 Polymers: particle size by year, each polymer's rolling year, share of the corpus,
   and the evidence gap map. Every panel's pick drives its own Open in Papers link and
   the card's header button. */
(() => {
  const B = window.POLYMERS || {};
  const T = DEBRIS.T;
  const colour = (k) => DEBRIS.colourFor(k);
  const SHORT = B.polymer_short || {};
  const LABELS = B.polymer_labels || {};
  const shortOf = (k) => SHORT[k] || k;
  const labelOf = (k) => LABELS[k] || k;
  const GHOST = '#C9CEDC';

  const setCard = DEBRIS.papersButton(document.getElementById('card-polymers'));
  const panelSet = (name, qs, sel) => {
    DEBRIS.setOpen(document.querySelector(`[data-open="${name}"]`), qs, sel);
    setCard(sel ? qs : '', sel);
  };

  const trend = B.trend || [];
  const x = trend.map((r) => r.date);
  const series = (k) => trend.map((r) => (r.by || {})[k] || 0);
  const total = trend.map((r) => r.n);
  const latest = (k) => (trend.length ? ((trend[trend.length - 1].by || {})[k] || 0) : 0);
  // Polymers with papers in the latest twelve months, most studied first; the catch-all last.
  const named = (B.polymer_order || []).filter((k) => latest(k) > 0)
    .sort((a, b) => (a === 'mixed_unspecified') - (b === 'mixed_unspecified') || latest(b) - latest(a));

  /* ------------------------------------------------------------------ particle size */
  function size() {
    const thisYear = new Date().getFullYear();
    const rows = (B.size || []).filter((r) => r.year <= thisYear
      && (r.micro + r.nano + r.mixed + r.unspecified) >= 20);
    if (!rows.length) return;
    const KINDS = [['micro', '#4F7CC4'], ['nano', T.pet], ['mixed', GHOST]];
    const NAMES = { micro: 'Microplastic', nano: 'Nanoplastic', mixed: 'Mixed sizes' };
    const lab = rows.map((r) => (r.year === thisYear ? `${r.year} to date` : String(r.year)));
    const sum = rows.map((r) => r.micro + r.nano + r.mixed);
    let pick = null;   // {size, year}
    const draw = () => {
      DEBRIS.plot('size', KINDS.map(([k, c]) => ({
        type: 'bar', name: NAMES[k], x: lab, y: rows.map((r, i) => (100 * r[k]) / sum[i]),
        customdata: rows.map((r) => [r[k], r.year]),
        marker: { color: c, line: { color: T.ink,
          width: rows.map((r) => (pick && pick.size === k && pick.year === r.year ? 2.5 : 0)) } },
        hovertemplate: `${NAMES[k]}, %{x}: %{y:.0f}% (%{customdata[0]:,} papers)<extra></extra>`,
      })), { barmode: 'stack', bargap: 0.18, hovermode: 'closest',
        margin: { l: 46, r: 16, t: 8, b: 70 },
        legend: { orientation: 'h', y: -0.22, itemclick: false, itemdoubleclick: false },
        xaxis: { tickangle: -45, tickfont: { size: 10, color: T.muted } },
        yaxis: { ticksuffix: '%', range: [0, 100], title: { text: 'Share of the year\'s papers', font: { size: 11 } } } });
      const el = document.getElementById('size');
      if (el.removeAllListeners) el.removeAllListeners('plotly_click');
      el.on('plotly_click', (ev) => {
        const p = ev.points[0];
        const next = { size: KINDS[p.curveNumber][0], year: p.customdata[1] };
        pick = pick && pick.size === next.size && pick.year === next.year ? null : next;
        panelSet('size', pick ? new URLSearchParams({ size_class: pick.size, year: pick.year }).toString() : '', !!pick);
        draw();
      });
    };
    draw();
  }

  /* ------------------------------------------------------------------ small multiples */
  function multiples() {
    const box = document.getElementById('multiples');
    if (!trend.length) { box.innerHTML = '<p class="empty">No data yet.</p>'; return; }
    const keys = named.slice(0, 12);
    const tpeak = Math.max(...total, 1);
    let picked = null;
    const end = x[x.length - 1].slice(0, 10);
    const start = new Date(end + 'T00:00:00Z');
    start.setUTCDate(start.getUTCDate() - 365);
    const lastYear = { from: start.toISOString().slice(0, 10), to: end };
    box.innerHTML = keys.map((k) => `<div class="tile" role="button" tabindex="0" data-k="${k}"
        aria-pressed="false" title="${DEBRIS.esc(labelOf(k))}">
        <div class="tilehead"><b>${DEBRIS.esc(shortOf(k))}</b><span class="mono" title="papers in the past 12 months">${DEBRIS.fmt(latest(k))} past year</span></div>
        <div class="tileplot" id="tile-${k}"></div></div>`).join('');
    keys.forEach((k) => {
      const y = series(k);
      const peak = Math.max(...y, 1);
      DEBRIS.plot(`tile-${k}`, [
        { type: 'scatter', mode: 'lines', x, y: total.map((v) => (v * peak) / tpeak), hoverinfo: 'skip',
          line: { color: GHOST, width: 1, shape: 'spline' } },
        { type: 'scatter', mode: 'lines', x, y, fill: 'tozeroy', fillcolor: colour(k) + '26',
          line: { color: colour(k), width: 2, shape: 'spline' },
          hovertemplate: `${shortOf(k)}, 12 months to %{x|%b %Y}: %{y:,}<extra></extra>` },
      ], { margin: { l: 4, r: 4, t: 2, b: 4 }, showlegend: false, hovermode: 'closest',
        xaxis: { visible: false }, yaxis: { visible: false, rangemode: 'tozero' } });
    });
    const tiles = [...box.querySelectorAll('.tile')];
    const choose = (k) => {
      picked = picked === k ? null : k;
      tiles.forEach((t) => t.setAttribute('aria-pressed', t.dataset.k === picked ? 'true' : 'false'));
      // The tile's number is the latest twelve months, so the link opens the same window.
      panelSet('multiples', picked ? new URLSearchParams({ polymers: picked,
        entered_from: lastYear.from, entered_to: lastYear.to }).toString() : '', !!picked);
    };
    tiles.forEach((t) => {
      t.addEventListener('click', () => choose(t.dataset.k));
      t.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(t.dataset.k); } });
    });
  }

  /* ------------------------------------------------------------------ share of the corpus */
  function share() {
    if (!trend.length) return;
    const keys = named.filter((k) => k !== 'mixed_unspecified').slice(0, 10);
    const el = document.getElementById('share');
    let chosen = new Set();   // polymers the reader brought forward
    let lit = null;           // hovered polymer
    let windowPick = null;    // {from, to, polymer} from a point click
    const on = (k) => (lit ? k === lit : (!chosen.size || chosen.has(k)));
    const traces = () => keys.map((k) => ({
      type: 'scatter', mode: 'lines', name: shortOf(k), x,
      y: series(k).map((v, i) => (total[i] ? (100 * v) / total[i] : null)),
      line: { color: on(k) ? colour(k) : GHOST, width: on(k) && (lit || chosen.size) ? 3.2 : 1.8, shape: 'spline' },
      hovertemplate: `${shortOf(k)}, 12 months to %{x|%b %Y}: %{y:.1f}% of papers<extra></extra>`,
    }));
    const layout = { margin: { l: 46, r: 16, t: 8, b: 38 }, showlegend: false, hovermode: 'closest',
      xaxis: { type: 'date', dtick: 'M24', tickformat: '%Y', range: [x[0], x[x.length - 1]] },
      yaxis: { ticksuffix: '%', rangemode: 'tozero', title: { text: 'Papers naming the polymer', font: { size: 11 } } } };
    DEBRIS.plot('share', traces(), layout);
    const legend = document.getElementById('share-legend');
    legend.innerHTML = keys.map((k) => `<button type="button" class="series" data-k="${k}" aria-pressed="false"
        title="${DEBRIS.esc(labelOf(k))}"><i style="background:${colour(k)}"></i>${DEBRIS.esc(shortOf(k))}</button>`).join('');
    const items = [...legend.querySelectorAll('.series')];
    const paint = () => {
      const t = traces();
      Plotly.restyle(el, { 'line.color': t.map((d) => d.line.color), 'line.width': t.map((d) => d.line.width) });
      items.forEach((b) => {
        b.setAttribute('aria-pressed', chosen.has(b.dataset.k) ? 'true' : 'false');
        b.classList.toggle('lit', b.dataset.k === lit);
      });
    };
    const sync = () => {
      if (windowPick) {
        panelSet('share', new URLSearchParams({ entered_from: windowPick.from, entered_to: windowPick.to,
          polymers: windowPick.polymer }).toString(), true);
        return;
      }
      panelSet('share', chosen.size ? 'polymers=' + [...chosen].join(',') : '', chosen.size > 0);
    };
    const hover = (k) => { if (lit !== k) { lit = k; paint(); } };
    items.forEach((b) => {
      const k = b.dataset.k;
      b.addEventListener('mouseenter', () => hover(k));
      b.addEventListener('focus', () => hover(k));
      b.addEventListener('mouseleave', () => hover(null));
      b.addEventListener('blur', () => hover(null));
      b.addEventListener('click', () => {
        if (chosen.has(k)) chosen.delete(k); else chosen.add(k);
        windowPick = null;
        paint(); sync();
      });
    });
    el.on('plotly_hover', (ev) => hover(keys[ev.points[0].curveNumber]));
    el.on('plotly_unhover', () => hover(null));
    el.on('plotly_click', (ev) => {
      const p = ev.points[0];
      const end = p.x.slice(0, 10);
      const start = new Date(end + 'T00:00:00Z');
      start.setUTCDate(start.getUTCDate() - 365);
      const next = { from: start.toISOString().slice(0, 10), to: end, polymer: keys[p.curveNumber] };
      windowPick = windowPick && windowPick.to === next.to && windowPick.polymer === next.polymer ? null : next;
      sync();
    });
  }

  /* ------------------------------------------------------------------ evidence gap map */
  const DISEASE_SHORT = {
    neuroinflammation_neurodegeneration: 'Neurodegeneration', atherosclerosis_mace: 'Cardiovascular',
    ibd_gut: 'Gut inflammation', liver_disease: 'Liver disease', immune_dysfunction: 'Immune dysfunction',
    cancer_other: 'Other cancers', cancer_colorectal: 'Colorectal cancer', pregnancy_outcomes: 'Pregnancy',
    metabolic_syndrome: 'Metabolic syndrome', kidney_disease: 'Kidney disease', copd_asthma: 'COPD and asthma',
    pulmonary_fibrosis: 'Lung fibrosis', hypertension_arrhythmia: 'Hypertension', anaemia_haemolysis: 'Anaemia',
    thrombosis: 'Thrombosis', sleep_circadian: 'Sleep',
  };
  function gap() {
    const G = B.gap || { polymers: [], diseases: [], cells: [] };
    if (!G.cells.length) { document.getElementById('gap').innerHTML = '<p class="empty">No data yet.</p>'; return; }
    const at = {};
    G.cells.forEach((c) => { at[c.p + '|' + c.d] = c; });
    const ylab = G.diseases.map((d) => DISEASE_SHORT[d] || (B.disease_labels || {})[d] || d);
    const z = G.diseases.map((d) => G.polymers.map((p) => {
      const c = at[p + '|' + d];
      return c ? Math.round((100 * c.human) / c.n) : null;
    }));
    const text = G.diseases.map((d, i) => G.polymers.map((p) => {
      const c = at[p + '|' + d];
      if (!c) return `${shortOf(p)} · ${ylab[i]}<br>No papers yet`;
      return `${shortOf(p)} · ${ylab[i]}<br>${DEBRIS.fmt(c.n)} papers, ${DEBRIS.fmt(c.human)} with evidence in people`
        + (c.best ? `<br>Strongest: ${G.tiers[String(c.best)]}` : '');
    }));
    let pick = null;   // {p, d}
    const draw = () => {
      const shapes = pick ? [{ type: 'rect', xref: 'x', yref: 'y',
        x0: G.polymers.indexOf(pick.p) - 0.5, x1: G.polymers.indexOf(pick.p) + 0.5,
        y0: G.diseases.indexOf(pick.d) - 0.5, y1: G.diseases.indexOf(pick.d) + 0.5,
        line: { color: T.pet, width: 3 } }] : [];
      DEBRIS.plot('gap', [{
        type: 'heatmap', x: G.polymers.map(shortOf), y: ylab, z, text, zmin: 0, zmax: 100,
        xgap: 3, ygap: 3, hoverongaps: true, hovertemplate: '%{text}<extra></extra>',
        colorscale: [[0, '#EEF1F8'], [0.5, '#7F95CF'], [1, T.ink]],
        colorbar: { title: { text: 'In people', side: 'right', font: { size: 11 } }, ticksuffix: '%',
                    thickness: 10, len: 0.9, outlinewidth: 0, tickfont: { size: 10, color: T.muted } },
      }], { margin: { l: 132, r: 12, t: 8, b: 40 }, shapes,
        yaxis: { autorange: 'reversed', gridcolor: 'rgba(0,0,0,0)', tickfont: { size: 11 } },
        xaxis: { gridcolor: 'rgba(0,0,0,0)', side: 'bottom', tickfont: { size: 11 } } });
      const el = document.getElementById('gap');
      if (el.removeAllListeners) el.removeAllListeners('plotly_click');
      el.on('plotly_click', (ev) => {
        const pt = ev.points[0];
        const next = { p: G.polymers[pt.pointNumber[1]], d: G.diseases[pt.pointNumber[0]] };
        if (!at[next.p + '|' + next.d]) return;
        pick = pick && pick.p === next.p && pick.d === next.d ? null : next;
        panelSet('gap', pick ? new URLSearchParams({ polymers: pick.p, disease: pick.d }).toString() : '', !!pick);
        draw();
      });
    };
    draw();
  }

  size();
  multiples();
  share();
  gap();
})();
