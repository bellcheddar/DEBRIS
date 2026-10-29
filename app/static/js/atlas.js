/* 01 Atlas: the polymer Venn, the evidence ladder and the year series.
   D3 is used for circle placement and region centroids only; the drawing is plain
   SVG so every region can carry its own link and accessible name. */
(() => {
  const B = window.ATLAS || {};
  if (!B.cells) { document.getElementById('venn-main').innerHTML = ''; return; }

  let organ = 'all';
  let petOnly = false;
  let ladderScope = 'all';

  const cell = () => (B.cells[organ] || B.cells.all || {})[petOnly ? 'pet' : 'all'] || {};

  /* ------------------------------------------------------------------- Venn */
  // A symmetric three-set Venn: three equal circles whose centres sit on an
  // equilateral triangle, so every one of the seven regions has room for a count.

  function venn3(svg, sets, regions, keys) {
    const cx = 215, cy = 160, r = 94, d = 58;
    const centres = [
      { x: cx, y: cy - d * 0.62 },
      { x: cx + d * 0.86, y: cy + d * 0.52 },
      { x: cx - d * 0.86, y: cy + d * 0.52 },
    ];
    const colours = [DEBRIS.T.pet, DEBRIS.T.ps, DEBRIS.T.pepp];
    // Region label anchors for the seven regions of a symmetric 3-set Venn,
    // expressed as offsets from the centroid so they scale with r and d.
    const anchors = {
      '100': { x: cx, y: cy - d - 34 },
      '010': { x: cx + d + 40, y: cy + d + 18 },
      '001': { x: cx - d - 40, y: cy + d + 18 },
      '110': { x: cx + d * 0.70, y: cy - d * 0.18 },
      '101': { x: cx - d * 0.70, y: cy - d * 0.18 },
      '011': { x: cx, y: cy + d + 4 },
      '111': { x: cx, y: cy + d * 0.26 },
    };
    const labels = {
      '100': sets[0], '010': sets[1], '001': sets[2],
      '110': sets[0] + ' + ' + sets[1], '101': sets[0] + ' + ' + sets[2],
      '011': sets[1] + ' + ' + sets[2], '111': 'all three',
    };
    let html = '';
    centres.forEach((c, i) => {
      html += `<circle cx="${c.x}" cy="${c.y}" r="${r}" fill="${colours[i]}" fill-opacity="0.17"
        stroke="${colours[i]}" stroke-width="2"></circle>`;
    });
    centres.forEach((c, i) => {
      const lx = [cx, cx + d * 1.55, cx - d * 1.55][i];
      const ly = [cy - d - 62, cy + d + 54, cy + d + 54][i];
      html += `<text class="nodelabel" x="${lx}" y="${ly}" text-anchor="middle"
        fill="${colours[i]}">${DEBRIS.esc(sets[i])}</text>`;
    });
    Object.entries(anchors).forEach(([code, pos]) => {
      const n = regions[code] || 0;
      const query = vennQuery(code, keys);
      html += `<g class="venn-region" role="link" tabindex="0" style="cursor:pointer"
        data-query="${query}" aria-label="${DEBRIS.esc(labels[code])}: ${n} papers">
        <text class="count" x="${pos.x}" y="${pos.y}" text-anchor="middle"
          style="font-size:15px;font-weight:500;fill:var(--el-ink)">${DEBRIS.fmt(n)}</text></g>`;
    });
    svg.innerHTML = html;
    svg.querySelectorAll('.venn-region').forEach((g) => {
      const go = () => { window.location = '/papers?' + g.dataset.query; };
      g.addEventListener('click', go);
      g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    });
  }

  function venn2(svg, sets, regions, keys) {
    const cy = 160, r = 96, dx = 56;
    const centres = [{ x: 215 - dx, y: cy }, { x: 215 + dx, y: cy }];
    const colours = [DEBRIS.T.pvc, DEBRIS.T.other];
    let html = '';
    centres.forEach((c, i) => {
      html += `<circle cx="${c.x}" cy="${c.y}" r="${r}" fill="${colours[i]}" fill-opacity="0.17"
        stroke="${colours[i]}" stroke-width="2"></circle>`;
      html += `<text class="nodelabel" x="${c.x + (i ? 52 : -52)}" y="${cy - r - 18}"
        text-anchor="middle" fill="${colours[i]}">${DEBRIS.esc(sets[i])}</text>`;
    });
    const anchors = { '10': { x: 215 - dx - 54, y: cy + 5 }, '01': { x: 215 + dx + 54, y: cy + 5 },
                      '11': { x: 215, y: cy + 5 } };
    const labels = { '10': sets[0], '01': sets[1], '11': sets[0] + ' + ' + sets[1] };
    Object.entries(anchors).forEach(([code, pos]) => {
      const n = regions[code] || 0;
      html += `<g class="venn-region" role="link" tabindex="0" style="cursor:pointer"
        data-query="${vennQuery(code, keys)}" aria-label="${DEBRIS.esc(labels[code])}: ${n} papers">
        <text class="count" x="${pos.x}" y="${pos.y}" text-anchor="middle"
          style="font-size:15px;font-weight:500;fill:var(--el-ink)">${DEBRIS.fmt(n)}</text></g>`;
    });
    svg.innerHTML = html;
    svg.querySelectorAll('.venn-region').forEach((g) => {
      const go = () => { window.location = '/papers?' + g.dataset.query; };
      g.addEventListener('click', go);
      g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    });
  }

  /* A membership code such as '101' becomes "papers with these polymers and not
     those", which /api/papers answers with polymers= and not_polymers=. */
  function vennQuery(code, keys) {
    const inside = [], outside = [];
    code.split('').forEach((bit, i) => (bit === '1' ? inside : outside).push(keys[i].join(',')));
    const qs = new URLSearchParams();
    if (inside.length) qs.set('polymers', inside.join('|'));
    if (outside.length) qs.set('not_polymers', outside.join(','));
    const organs = (B.organ_map && B.organ_map[organ]) || [];
    if (organs.length) qs.set('organs', organs.join(','));
    if (petOnly) qs.set('pet', '1');
    return qs.toString();
  }

  /* ----------------------------------------------------------------- ladder */
  function ladder() {
    const data = (B.ladder || {})[ladderScope] || [];
    if (!data.length) { document.getElementById('ladder').innerHTML = '<p class="empty">No tagged papers yet.</p>'; return; }
    const rungLabels = B.rung_labels || {};
    // Rungs 1 to 5 in the Elora ramp; rung 6 in --pet, drawn even when empty.
    const rungColour = (r) => r === 6 ? DEBRIS.T.pet
      : ['#C7D0E8', '#9FADD4', '#7589BE', '#4F67A8', '#2A3C78'][r - 1];
    const traces = [1, 2, 3, 4, 5, 6].map((r) => ({
      type: 'bar', orientation: 'h', name: 'Rung ' + r,
      y: data.map((d) => d.label), x: data.map((d) => d.rungs[r - 1] || 0),
      marker: { color: rungColour(r), line: { color: '#fff', width: 1 } },
      hovertemplate: `%{y}<br>Rung ${r}: ${DEBRIS.esc(rungLabels[r] || '')}<br>%{x} papers<extra></extra>`,
    }));
    DEBRIS.plot('ladder', traces, {
      barmode: 'stack', bargap: 0.28,
      margin: { l: 230, r: 20, t: 8, b: 44 },
      xaxis: { title: { text: 'Papers', font: { size: 11 } }, gridcolor: DEBRIS.T.line },
      yaxis: { automargin: true, tickfont: { size: 11 } },
      legend: { orientation: 'h', y: -0.1, font: { size: 10 } },
    });
    document.getElementById('ladder-legend').innerHTML = [1, 2, 3, 4, 5, 6].map((r) =>
      `<span><i style="background:${rungColour(r)}"></i>${r}: ${DEBRIS.esc(rungLabels[r] || '')}</span>`)
      .join('') + '<span style="color:var(--pet)">Rung 6 is the rung an enzyme therapeutic can test.</span>';
    const el = document.getElementById('ladder');
    el.removeAllListeners && el.removeAllListeners('plotly_click');
    el.on && el.on('plotly_click', (ev) => {
      const point = ev.points[0];
      const row = data[point.pointIndex];
      const rung = point.curveNumber + 1;
      const qs = new URLSearchParams({ disease: row.key, rung: String(rung) });
      if (ladderScope === 'pet') qs.set('pet', '1');
      window.location = '/papers?' + qs.toString();
    });
  }

  /* ------------------------------------------------------------------ years */
  function years() {
    const rows = B.years || [];
    if (!rows.length) return;
    DEBRIS.plot('years', [
      { type: 'scatter', mode: 'lines', name: 'All polymers', x: rows.map((r) => r.year),
        y: rows.map((r) => r.n), line: { color: DEBRIS.T.blue, width: 2.5, shape: 'spline' },
        fill: 'tozeroy', fillcolor: 'rgba(56,80,152,0.10)' },
      { type: 'scatter', mode: 'lines', name: 'PET-specific', x: rows.map((r) => r.year),
        y: rows.map((r) => r.pet_n), line: { color: DEBRIS.T.pet, width: 2.5, shape: 'spline' } },
    ], { margin: { l: 50, r: 16, t: 8, b: 38 },
         xaxis: { dtick: 2, gridcolor: 'rgba(0,0,0,0)' },
         yaxis: { title: { text: 'Papers', font: { size: 11 } } } });
  }

  function redrawVenn() {
    const c = cell();
    venn3(document.getElementById('venn-main'), B.venn_main_sets || ['PET', 'PS', 'PE+PP'],
          c.venn_main || {}, B.venn_main_keys || [['PET'], ['PS'], ['PE', 'PP']]);
    venn2(document.getElementById('venn-secondary'), B.venn_secondary_sets || ['PVC', 'Other'],
          c.venn_secondary || {}, B.venn_secondary_keys || [['PVC'], ['other']]);
    document.getElementById('kpi-verified').textContent = DEBRIS.fmt(c.verified ?? 0);
    document.getElementById('kpi-pet').textContent = DEBRIS.fmt(c.pet ?? 0);
    document.getElementById('kpi-organs').textContent = DEBRIS.fmt(c.organs ?? 0);
  }

  DEBRIS.chips('.organ-chip', (value) => { organ = value; redrawVenn(); });
  DEBRIS.chips('.ladder-chip', (value) => { ladderScope = value; ladder(); });
  document.getElementById('pet-only').addEventListener('change', (e) => {
    petOnly = e.target.checked; redrawVenn();
  });

  redrawVenn();
  ladder();
  years();
})();
