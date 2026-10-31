/* 03 Pathways: flows, the mechanism profile, disease and mechanism bars, and the new-edge list. */
(() => {
  const B = window.PATHWAYS || {};
  const sankey = B.sankey || { labels: [], links: [] };

  const hideOther = () => document.getElementById('hide-other').checked;
  // The card's header button shows whichever panel was picked in last.
  const setCard = DEBRIS.papersButton(document.getElementById('card-pathways'));
  const panelSet = (name, qs, sel) => {
    DEBRIS.setOpen(document.querySelector(`[data-open="${name}"]`), qs, sel);
    setCard(sel ? qs : '', sel);
  };
  let sankeySel = null;

  /* Fixed node positions: three columns, largest at the top, each "other" node last. */
  function positions(links) {
    const value = sankey.labels.map(() => 0);
    const inflow = sankey.labels.map(() => 0);
    links.forEach((l) => { value[l.source] += l.value; inflow[l.target] += l.value; });
    inflow.forEach((v, i) => { value[i] = Math.max(value[i], v); });
    const colX = { polymer: 0.001, pathway: 0.42, disease: 0.999 };
    const x = [], y = [];
    Object.keys(colX).forEach((kind) => {
      const ids = sankey.labels.map((_, i) => i).filter((i) => sankey.kinds[i] === kind && value[i] > 0)
        .sort((p, q) => (sankey.keys[p] === '_other') - (sankey.keys[q] === '_other') || value[q] - value[p]);
      const total = ids.reduce((s, i) => s + value[i], 0) || 1;
      let at = 0;
      ids.forEach((i) => {
        const share = value[i] / total;
        x[i] = colX[kind];
        y[i] = Math.min(0.999, Math.max(0.001, 0.02 + 0.92 * (at + share / 2)));
        at += share;
      });
    });
    return { x: sankey.labels.map((_, i) => x[i] ?? 0.5), y: sankey.labels.map((_, i) => y[i] ?? 0.5) };
  }

  function drawSankey() {
    const el = document.getElementById('sankey');
    const links = sankey.links.filter((l) => !(hideOther() && l.other));
    if (!links.length) { el.innerHTML = '<p class="empty">No tagged papers yet.</p>'; return; }
    const linkColour = (l) => l.other ? 'rgba(138,147,173,0.16)'
      : l.pet ? 'rgba(200,135,43,0.5)' : 'rgba(56,80,152,0.24)';
    const pos = positions(links);
    Plotly.newPlot(el, [{
      type: 'sankey', orientation: 'h', arrangement: 'snap',
      node: {
        label: sankey.labels, color: sankey.colours, pad: 16, thickness: 16,
        x: pos.x, y: pos.y,
        line: { color: '#fff', width: 1 },
        hovertemplate: '%{label}<br>%{value} papers<extra></extra>',
      },
      link: {
        source: links.map((l) => l.source),
        target: links.map((l) => l.target),
        value: links.map((l) => l.value),
        color: links.map(linkColour),
        hovertemplate: '%{source.label} to %{target.label}<br>%{value} papers<extra></extra>',
      },
    }], DEBRIS.layout({
      margin: { l: 8, r: 8, t: 8, b: 8 },
      font: { family: 'Montserrat, Helvetica, Arial, sans-serif', size: 12, color: DEBRIS.T.fg },
    }), DEBRIS.config);

    // A ribbon selects its two ends, a node selects itself; the same again clears it.
    // Plotly reports ribbon clicks, but its node dragging swallows node clicks, so a
    // node is taken from the last hover and selected on the page's own click event.
    el.removeAllListeners && el.removeAllListeners('plotly_click');
    el.removeAllListeners && el.removeAllListeners('plotly_hover');
    el.removeAllListeners && el.removeAllListeners('plotly_unhover');
    let hoverNode = null;
    el.on('plotly_hover', (ev) => {
      const pt = ev.points[0];
      hoverNode = pt && pt.sourceLinks !== undefined ? pt.pointNumber : null;
    });
    el.on('plotly_unhover', () => { hoverNode = null; });
    // During a press Plotly lays a drag cover over the page, so the click never reaches
    // the chart. A press and release a few pixels apart over a node is the click.
    if (el.debrisDown) el.removeEventListener('pointerdown', el.debrisDown, true);
    el.debrisDown = (e) => {
      if (hoverNode === null) return;
      const node = hoverNode, x = e.clientX, y = e.clientY;
      const up = (u) => {
        window.removeEventListener('pointerup', up, true);
        if (Math.abs(u.clientX - x) < 5 && Math.abs(u.clientY - y) < 5) pickEnds([node]);
      };
      window.addEventListener('pointerup', up, true);
    };
    el.addEventListener('pointerdown', el.debrisDown, true);
    el.on('plotly_click', (ev) => {
      const point = ev.points[0];
      if (!(point.source && point.target) || point.sourceLinks !== undefined) return;
      const shown = sankey.links.filter((l) => !(hideOther() && l.other));
      const link = shown[point.index];
      if (!link) return;
      pickEnds([link.source, link.target]);
    });
  }

  function pickEnds(ends) {
    {
      const qs = new URLSearchParams();
      ends.forEach((i) => {
        const key = keyFor(i);
        if (key === '_other') return;
        if (sankey.kinds[i] === 'polymer') qs.set('polymer', key);
        if (sankey.kinds[i] === 'pathway') qs.set('pathway', key);
        if (sankey.kinds[i] === 'disease') qs.set('disease', key);
      });
      const s = qs.toString();
      sankeySel = !s || s === sankeySel ? null : s;
      panelSet('sankey', sankeySel || '', !!sankeySel);
    }
  }

  /* Node labels are display names; the keys the API filters on come back from the
     label-to-key map the bundle carries alongside them. */
  function keyFor(index) {
    return (B.sankey.keys && B.sankey.keys[index]) || sankey.labels[index];
  }

  /* --------------------------------------------------------------------- radar */
  const radar = B.radar || {};
  // Largest disease first, so the profile opens on the most studied one.
  const catKeys = Object.keys(radar).sort((p, q) =>
    radar[q].all.reduce((s, v) => s + v, 0) - radar[p].all.reduce((s, v) => s + v, 0));
  const selA = document.getElementById('cat-a');
  const selB = document.getElementById('cat-b');

  let radarPick = null;   // a mechanism picked on the radar, or null
  // The panel always shows the chosen disease's count; the card follows only a choice
  // the reader made, not the default on load.
  const setRadar = (byReader) => {
    const qs = new URLSearchParams();
    if (selA.value) qs.set('disease', selA.value);
    if (radarPick) qs.set('pathway', radarPick);
    DEBRIS.setOpen(document.querySelector('[data-open="radar"]'), qs.toString(), !!selA.value);
    if (byReader) setCard(qs.toString(), true);
  };
  DEBRIS.papersButton(document.getElementById('card-new'))('novel=1&new=1');

  function fillSelects() {
    catKeys.forEach((key) => {
      selA.add(new Option(radar[key].label, key));
      selB.add(new Option(radar[key].label, key));
    });
    if (catKeys.length) selA.value = catKeys[0];
  }

  function drawRadar() {
    const el = document.getElementById('radar');
    setRadar();
    if (!catKeys.length) { el.innerHTML = '<p class="empty">No tagged papers yet.</p>'; return; }
    const order = (B.axes || []).map((k, i) => i);
    const total = Object.fromEntries((B.pathways || []).map((p) => [p.key, p.n]));
    const named = order.filter((i) => B.axes[i] !== 'other_pathway')
      .sort((p, q) => (total[B.axes[q]] || 0) - (total[B.axes[p]] || 0)).slice(0, 10);
    const otherIdx = order.filter((i) => B.axes[i] === 'other_pathway');
    const pick = named.concat(hideOther() ? [] : otherIdx);
    const axes = pick.map((i) => B.axis_labels[i]).concat([B.axis_labels[pick[0]]]);
    const close = (arr) => pick.map((i) => arr[i]).concat([arr[pick[0]]]);
    const traces = [];
    const a = radar[selA.value];
    if (a) {
      traces.push({ type: 'scatterpolar', mode: 'lines+markers', name: a.label,
        theta: axes, r: close(a.all), fill: 'toself',
        line: { color: DEBRIS.T.blue, width: 2 }, fillcolor: 'rgba(56,80,152,0.14)' });
      if (document.getElementById('pet-trace').checked) {
        traces.push({ type: 'scatterpolar', mode: 'lines+markers', name: a.label + ' (PET only)',
          theta: axes, r: close(a.pet), line: { color: DEBRIS.T.pet, width: 2, dash: 'dot' } });
      }
    }
    const b = radar[selB.value];
    if (b) {
      traces.push({ type: 'scatterpolar', mode: 'lines+markers', name: b.label,
        theta: axes, r: close(b.all), fill: 'toself',
        line: { color: DEBRIS.T.pvc, width: 2 }, fillcolor: 'rgba(110,91,166,0.12)' });
    }
    Plotly.newPlot(el, traces, DEBRIS.layout({
      polar: {
        bgcolor: 'rgba(0,0,0,0)',
        radialaxis: { gridcolor: DEBRIS.T.line, tickfont: { size: 10, color: DEBRIS.T.muted },
                      angle: 90, title: { text: 'Papers' } },
        angularaxis: { gridcolor: DEBRIS.T.line, tickfont: { size: 10, color: DEBRIS.T.muted } },
      },
      margin: { l: 105, r: 105, t: 30, b: 50 },
      showlegend: true, legend: { orientation: 'h', y: -0.08, font: { size: 10 } },
    }), DEBRIS.config);
    el.removeAllListeners && el.removeAllListeners('plotly_click');
    el.on('plotly_click', (ev) => {
      const key = B.axes[pick[ev.points[0].pointNumber % pick.length]];
      radarPick = radarPick === key ? null : key;
      setRadar(true);
    });
  }

  /* ----------------------------------------------------------------- new edges */
  function drawNewEdges() {
    const rows = B.new_edges || [];
    const el = document.getElementById('new-edges');
    if (!rows.length) { el.innerHTML = '<p class="empty">No new combinations in the latest run.</p>'; return; }
    el.innerHTML = '<div class="feed">' + rows.map((r) => `
      <article class="paper">
        <div class="meta"><span class="badge-novel">Novel</span>
          <span class="mono">${DEBRIS.esc(r.key)}</span></div>
        <h3 style="font-size:13px">${DEBRIS.esc(r.title || '')}</h3>
        <div class="meta"><span class="mono">${DEBRIS.esc(r.journal || '')} ${r.year || ''}</span>
          <button class="chip" type="button" data-pmid="${r.pmid}">Detail</button></div>
      </article>`).join('') + '</div>';
    el.querySelectorAll('[data-pmid]').forEach((btn) =>
      btn.addEventListener('click', () => DEBRIS.openPaper(btn.dataset.pmid)));
  }

  /* ---------------------------------------------------------------- the bars */
  // Horizontal bars, largest at the top: PET-specific papers in amber, the rest in blue,
  // so each bar's length is its total. "Other mechanisms" goes last, in grey.
  function bars(id, rows, param, catchAll, linkName) {
    const el = document.getElementById(id);
    if (!rows.length) { el.innerHTML = '<p class="empty">No tagged papers yet.</p>'; return; }
    const ordered = rows.filter((r) => r.key !== catchAll).concat(rows.filter((r) => r.key === catchAll));
    const y = ordered.map((r) => r.label);
    const rest = ordered.map((r) => r.n - r.pet);
    Plotly.newPlot(el, [
      { type: 'bar', orientation: 'h', name: 'PET-specific', y, x: ordered.map((r) => r.pet),
        marker: { color: DEBRIS.T.pet },
        hovertemplate: '%{y}<br>%{x} PET-specific papers<extra></extra>' },
      { type: 'bar', orientation: 'h', name: 'Other papers', y, x: rest,
        marker: { color: ordered.map((r) => r.key === catchAll ? DEBRIS.T.muted : DEBRIS.T.blue) },
        customdata: ordered.map((r) => r.n),
        hovertemplate: '%{y}<br>%{customdata} papers in all<extra></extra>' },
    ], DEBRIS.layout({
      barmode: 'stack', bargap: 0.28,
      margin: { l: 10, r: 16, t: 6, b: 40 },
      yaxis: { autorange: 'reversed', automargin: true, tickfont: { size: 11, color: DEBRIS.T.fg } },
      xaxis: { title: { text: 'Papers', font: { size: 11 } }, gridcolor: DEBRIS.T.line },
      legend: { orientation: 'h', y: -0.14, font: { size: 10 } },
    }), DEBRIS.config);
    const link = document.querySelector(`[data-open="${linkName}"]`);
    let picked = '';
    el.on('plotly_click', (ev) => {
      const row = ordered[ev.points[0].pointIndex];
      const qs = new URLSearchParams({ [param]: row.key });
      if (ev.points[0].curveNumber === 0) qs.set('pet', '1');
      picked = qs.toString() === picked ? '' : qs.toString();
      panelSet(linkName, picked, !!picked);
    });
  }

  fillSelects();
  drawSankey();
  bars('disease-bars', B.diseases || [], 'disease', null, 'diseases');
  bars('pathway-bars', B.pathways || [], 'pathway', 'other_pathway', 'mechanisms');
  drawRadar();
  drawNewEdges();
  [selA, selB, document.getElementById('pet-trace')].forEach((el) =>
    el.addEventListener('change', drawRadar));
  selA.addEventListener('change', () => setRadar(true));
  document.getElementById('hide-other').addEventListener('change', () => { drawSankey(); drawRadar(); });
})();
