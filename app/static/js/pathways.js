/* 03 Pathways: the Sankey hub, the per-category pathway radar and the new-edge list. */
(() => {
  const B = window.PATHWAYS || {};
  const sankey = B.sankey || { labels: [], links: [] };

  function drawSankey() {
    const el = document.getElementById('sankey');
    if (!sankey.links.length) { el.innerHTML = '<p class="empty">No tagged papers yet.</p>'; return; }
    const linkColour = (l) => l.pet ? 'rgba(200,135,43,0.45)' : 'rgba(56,80,152,0.22)';
    Plotly.newPlot(el, [{
      type: 'sankey', orientation: 'h', arrangement: 'snap',
      node: {
        label: sankey.labels, color: sankey.colours, pad: 13, thickness: 15,
        line: { color: '#fff', width: 1 },
        hovertemplate: '%{label}<br>%{value} papers<extra></extra>',
      },
      link: {
        source: sankey.links.map((l) => l.source),
        target: sankey.links.map((l) => l.target),
        value: sankey.links.map((l) => l.value),
        color: sankey.links.map(linkColour),
        hovertemplate: '%{source.label} to %{target.label}<br>%{value} papers<extra></extra>',
      },
    }], DEBRIS.layout({
      margin: { l: 10, r: 10, t: 10, b: 10 },
      font: { family: 'Montserrat, Helvetica, Arial, sans-serif', size: 11, color: DEBRIS.T.fg },
    }), DEBRIS.config);

    el.on('plotly_click', (ev) => {
      const point = ev.points[0];
      if (point.index === undefined || !sankey.links[point.index]) return;
      const link = sankey.links[point.index];
      const kindOf = (i) => sankey.kinds[i];
      const qs = new URLSearchParams();
      [link.source, link.target].forEach((i) => {
        const key = keyFor(i);
        if (kindOf(i) === 'polymer') qs.set('polymer', key);
        if (kindOf(i) === 'pathway') qs.set('pathway', key);
        if (kindOf(i) === 'disease') qs.set('disease', key);
      });
      if (qs.toString()) window.location = '/papers?' + qs.toString();
    });
  }

  /* Node labels are display names; the keys the API filters on come back from the
     label-to-key map the bundle carries alongside them. */
  function keyFor(index) {
    return (B.sankey.keys && B.sankey.keys[index]) || sankey.labels[index];
  }

  /* --------------------------------------------------------------------- radar */
  const radar = B.radar || {};
  const catKeys = Object.keys(radar);
  const selA = document.getElementById('cat-a');
  const selB = document.getElementById('cat-b');

  DEBRIS.papersButton(document.getElementById('card-sankey'));
  const setRadar = DEBRIS.papersButton(document.getElementById('card-radar'));
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
    setRadar(selA.value ? 'disease=' + encodeURIComponent(selA.value) : '');
    if (!catKeys.length) { el.innerHTML = '<p class="empty">No tagged papers yet.</p>'; return; }
    const axes = (B.axis_labels || []).concat([(B.axis_labels || [])[0]]);
    const close = (arr) => arr.concat([arr[0]]);
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
      margin: { l: 70, r: 70, t: 30, b: 50 },
      showlegend: true, legend: { orientation: 'h', y: -0.08, font: { size: 10 } },
    }), DEBRIS.config);
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

  fillSelects();
  drawSankey();
  drawRadar();
  drawNewEdges();
  [selA, selB, document.getElementById('pet-trace')].forEach((el) =>
    el.addEventListener('change', drawRadar));
})();
