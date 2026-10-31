/* 03 Pathways: flows, the mechanism profile, disease and mechanism bars, and the new-edge list. */
(() => {
  const B = window.PATHWAYS || {};
  const sankey = B.sankey || { labels: [], links: [] };

  const hideOther = () => false;   // the catch-all nodes are always drawn (owner)
  // The card's header button shows whichever panel was picked in last.
  const setCard = DEBRIS.papersButton(document.getElementById('card-pathways'));
  const panelSet = (name, qs, sel) => {
    DEBRIS.setOpen(document.querySelector(`[data-open="${name}"]`), qs, sel);
    setCard(sel ? qs : '', sel);
  };
  let sankeySel = null;

  /* Fixed node positions: three columns, largest at the top, each "other" node last, and
     every column spread from the top of the panel to the bottom. Node heights stay true to
     the papers (one scale for all columns, as Plotly draws them); a column with fewer
     papers gets wider gaps instead of ending short. */
  const PAD = 16;
  function positions(links, heightPx) {
    const value = sankey.labels.map(() => 0);
    const inflow = sankey.labels.map(() => 0);
    links.forEach((l) => { value[l.source] += l.value; inflow[l.target] += l.value; });
    inflow.forEach((v, i) => { value[i] = Math.max(value[i], v); });
    const colX = { polymer: 0.001, pathway: 0.42, disease: 0.999 };
    const cols = {};
    Object.keys(colX).forEach((kind) => {
      cols[kind] = sankey.labels.map((_, i) => i).filter((i) => sankey.kinds[i] === kind && value[i] > 0)
        .sort((p, q) => (sankey.keys[p] === '_other') - (sankey.keys[q] === '_other') || value[q] - value[p]);
    });
    // Plotly's own scale: the tightest column decides how tall a paper is.
    const scale = Math.min(...Object.values(cols).filter((c) => c.length).map((c) =>
      (heightPx - (c.length - 1) * PAD) / c.reduce((s, i) => s + value[i], 0)));
    const x = [], y = [];
    Object.entries(cols).forEach(([kind, ids]) => {
      const h = ids.map((i) => (value[i] * scale) / heightPx);
      const gap = ids.length > 1 ? (1 - h.reduce((s, v) => s + v, 0)) / (ids.length - 1) : 0;
      let top = 0;
      ids.forEach((i, n) => {
        x[i] = colX[kind];
        y[i] = Math.min(0.999, Math.max(0.001, top + h[n] / 2));
        top += h[n] + gap;
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
    const pos = positions(links, Math.max(200, el.clientHeight - 16));
    Plotly.newPlot(el, [{
      type: 'sankey', orientation: 'h', arrangement: 'snap',
      node: {
        label: sankey.labels, color: sankey.colours, pad: PAD, thickness: 16,
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
  const overlay = document.getElementById('overlay');

  let radarPick = null;   // a mechanism picked on the radar, or null
  // Every disease's profile is drawn; the overlay box highlights one. The links count the
  // highlighted disease (and a picked mechanism); with nothing highlighted, a mechanism.
  const setRadar = (byReader) => {
    const qs = new URLSearchParams();
    if (overlay.value) qs.set('disease', overlay.value);
    if (radarPick) qs.set('pathway', radarPick);
    const chosen = !!(overlay.value || radarPick);
    DEBRIS.setOpen(document.querySelector('[data-open="radar"]'), qs.toString(), chosen);
    if (byReader) setCard(chosen ? qs.toString() : '', chosen);
  };
  DEBRIS.papersButton(document.getElementById('card-new'))('novel=1&new=1');

  function fillSelects() {
    catKeys.forEach((key) => overlay.add(new Option(radar[key].label, key)));
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
    const pick = named.concat(otherIdx);
    const axes = pick.map((i) => B.axis_labels[i]).concat([B.axis_labels[pick[0]]]);
    const close = (arr) => pick.map((i) => arr[i]).concat([arr[pick[0]]]);
    const hi = overlay.value;
    const traceKeys = catKeys.filter((k) => k !== hi).concat(hi && radar[hi] ? [hi] : []);
    const traces = catKeys.filter((k) => k !== hi).map((k) => ({
      type: 'scatterpolar', mode: 'lines', name: radar[k].label, theta: axes, r: close(radar[k].all),
      line: { color: hi ? 'rgba(138,147,173,0.35)' : 'rgba(56,80,152,0.45)', width: 1.2 },
      hovertemplate: `${DEBRIS.esc(radar[k].label)}<br>%{theta}: %{r} papers<extra></extra>`,
    }));
    if (hi && radar[hi]) {
      traces.push({ type: 'scatterpolar', mode: 'lines+markers', name: radar[hi].label,
        theta: axes, r: close(radar[hi].all), fill: 'toself',
        line: { color: DEBRIS.T.pet, width: 3 }, marker: { size: 6, color: DEBRIS.T.pet },
        fillcolor: 'rgba(200,135,43,0.18)',
        hovertemplate: `${DEBRIS.esc(radar[hi].label)}<br>%{theta}: %{r} papers<extra></extra>` });
    }
    Plotly.newPlot(el, traces, DEBRIS.layout({
      polar: {
        bgcolor: 'rgba(0,0,0,0)',
        radialaxis: { gridcolor: DEBRIS.T.line, tickfont: { size: 10, color: DEBRIS.T.muted },
                      angle: 90, title: { text: 'Papers' } },
        angularaxis: { gridcolor: DEBRIS.T.line, tickfont: { size: 10, color: DEBRIS.T.muted } },
      },
      margin: { l: 105, r: 105, t: 30, b: 30 },
      showlegend: false, hovermode: 'closest',
    }), DEBRIS.config);
    // Hovering a line brings that disease forward; clicking it highlights it, as the box does.
    const base = traces.map((t) => ({ color: t.line.color, width: t.line.width }));
    const lift = (i) => Plotly.restyle(el, {
      'line.color': base.map((b, j) => (i === null || j === i ? (j === i && traceKeys[j] !== hi
        ? 'rgba(200,135,43,0.85)' : b.color) : 'rgba(138,147,173,0.18)')),
      'line.width': base.map((b, j) => (j === i ? Math.max(b.width, 3) : b.width)),
    });
    ['plotly_click', 'plotly_hover', 'plotly_unhover'].forEach((n) =>
      el.removeAllListeners && el.removeAllListeners(n));
    let lit = null;
    el.on('plotly_hover', (ev) => {
      const i = ev.points[0].curveNumber;
      if (i !== lit) { lit = i; lift(i); }
    });
    el.on('plotly_unhover', () => { lit = null; lift(null); });
    el.on('plotly_click', (ev) => {
      const key = traceKeys[ev.points[0].curveNumber];
      overlay.value = overlay.value === key ? '' : key;
      radarPick = null;
      drawRadar();
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
  overlay.addEventListener('change', () => { drawRadar(); setRadar(true); });
})();
