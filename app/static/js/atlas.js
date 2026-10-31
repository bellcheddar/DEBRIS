/* 01 Atlas: four readings of the polymer field, the evidence ladder and the year series.

   The four panels share one selection. Picking a polymer anywhere sets `focus`, and every
   panel repaints from it: the cluster raises that circle and draws its overlaps, the
   packing lifts its family, the matrix lights its row and column, and the bars mark every
   combination containing it. Picking a pair (a matrix cell, or a lens in the cluster) sets
   `pair` as well, which narrows the bars to the combinations holding both.

   Nothing about the polymer roster is written down here. The vocabulary supplies the
   order, the labels, the families and the colours, so going from 13 polymers to 11 named
   ones, or to anything else, is a change to config/vocab.toml alone. */
(() => {
  const B = window.ATLAS || {};
  const svg = (id) => d3.select('#' + id);
  if (!B.cells || !document.getElementById('venn-cluster')) return;

  let organ = 'all';
  let petOnly = false;
  let ladderScope = 'all';
  let focus = null;   // a polymer key, or null
  let pair = null;    // [a, b] sorted, or null

  const ORDER = B.polymer_order || [];
  const LABELS = B.polymer_labels || {};
  const FAMILY = B.polymer_families || {};
  const SHORT = B.polymer_short || {};
  const T = DEBRIS.T;
  const colour = (key) => DEBRIS.colourFor(key);
  const labelOf = (key) => LABELS[key] || key;
  const shortOf = (key) => SHORT[key] || key;

  const cell = () => (B.cells[organ] || B.cells.all || {})[petOnly ? 'pet' : 'all'] || {};
  const rowsOf = () => cell().polymers || [];
  const pairsOf = () => cell().pairs || [];
  const combosOf = () => cell().combos || [];
  const countOf = (key) => (rowsOf().find((r) => r.k === key) || {}).n || 0;
  const pairCount = (a, b) => {
    const hit = pairsOf().find((p) => (p.a === a && p.b === b) || (p.a === b && p.b === a));
    return hit ? hit.n : 0;
  };

  /* ------------------------------------------------------------------ selection */
  function select(key, pairKeys) {
    const samePolymer = key === focus && !pairKeys && !pair;
    const samePair = pairKeys && pair && pairKeys.join() === pair.join();
    if (samePolymer || samePair) { focus = null; pair = null; }
    else { focus = key; pair = pairKeys ? [...pairKeys].sort() : null; }
    paintAll();
  }

  /* The filter a selection stands for, in the terms /api/papers already answers. */
  function query() {
    const qs = new URLSearchParams();
    if (pair) qs.set('polymers', pair.join('|'));
    else if (focus) qs.set('polymer', focus);
    const organs = (B.organ_map && B.organ_map[organ]) || [];
    if (organs.length) qs.set('organs', organs.join(','));
    if (petOnly) qs.set('pet', '1');
    return qs.toString();
  }

  function selbar() {
    const el = document.getElementById('selbar');
    if (!focus && !pair) {
      el.innerHTML = '<span class="idle">Select a polymer in any panel. All four follow it, '
        + 'and the selection becomes a filter you can open in the Papers tab.</span>';
      return;
    }
    const n = pair ? pairCount(pair[0], pair[1]) : countOf(focus);
    const what = pair
      ? `${labelOf(pair[0])} with ${labelOf(pair[1])}`
      : labelOf(focus);
    const swatch = pair
      ? `<i style="background:${colour(pair[0])}"></i><i style="background:${colour(pair[1])}"></i>`
      : `<i style="background:${colour(focus)}"></i>`;
    el.innerHTML =
      `<span class="what">${swatch}${DEBRIS.esc(what)}</span>`
      + `<span class="howmany">${DEBRIS.fmt(n)} papers</span>`
      + '<span class="spacer"></span>'
      + `<a class="btn ghost" href="/papers?${query()}">Open in Papers</a>`
      + '<button class="chip" type="button" id="clearsel">Clear</button>';
    document.getElementById('clearsel').onclick = () => { focus = null; pair = null; paintAll(); };
  }

  function paintAll() {
    cluster.paint(); packing.paint(); matrix.paint(); bars.paint();
    selbar();
    links();
    ['panel-cluster', 'panel-packing', 'panel-matrix', 'panel-bars'].forEach((id) =>
      document.getElementById(id).classList.toggle('lit', !!(focus || pair)));
  }

  /* ------------------------------------------------------------- open in papers */
  const setField = DEBRIS.papersButton(document.getElementById('card-field'));
  const setLadder = DEBRIS.papersButton(document.getElementById('card-ladder'));
  const setYears = DEBRIS.papersButton(document.getElementById('card-years'));

  // The organ chip and the PET switch, which every Atlas figure follows.
  function scope() {
    const qs = new URLSearchParams();
    const organs = (B.organ_map && B.organ_map[organ]) || [];
    if (organs.length) qs.set('organs', organs.join(','));
    if (petOnly) qs.set('pet', '1');
    return qs;
  }

  function links() {
    const q = query();
    setField(q);
    document.querySelectorAll('#card-field [data-open]').forEach((a) => {
      a.href = '/papers' + (q ? '?' + q : '');
    });
    const kpi = (id, extra) => {
      const a = document.getElementById('kpilink-' + id);
      if (!a) return;
      const qs = scope();
      Object.entries(extra || {}).forEach(([k, v]) => qs.set(k, v));
      a.href = '/papers' + (qs.toString() ? '?' + qs.toString() : '');
    };
    ['verified', 'polymers', 'organs', 'tissues', 'pathways', 'models'].forEach((id) => kpi(id));
    kpi('pet', { pet: '1' });
    kpi('human', { rungs: '1,2' });
  }

  function rebuildAll() {
    cluster.build(); packing.build(); matrix.build(); bars.build();
    const c = cell();
    document.getElementById('kpi-verified').textContent = DEBRIS.fmt(c.verified ?? 0);
    document.getElementById('kpi-pet').textContent = DEBRIS.fmt(c.pet ?? 0);
    document.getElementById('kpi-polymers').textContent = DEBRIS.fmt(c.polymer_count ?? 0);
    ['organs', 'human', 'tissues', 'pathways', 'models'].forEach((k) => {
      const el = document.getElementById('kpi-' + k);
      if (el) el.textContent = DEBRIS.fmt(c[k] ?? 0);
    });
    paintAll();
  }

  /* Until the corpus is tagged there is nothing to draw, and four blank frames tell the
     reader the page is broken rather than waiting. Each panel says what will appear. */
  function placeholder(root, width, height, lines) {
    // Only ever adds. The layer groups each panel builds into are long-lived siblings,
    // and clearing them here would leave the panel unable to draw once tags arrive.
    root.selectAll('.placeholder').remove();
    const g = root.append('g').attr('class', 'placeholder')
      .attr('transform', `translate(${width / 2},${height / 2 - 10})`);
    lines.forEach((line, i) => g.append('text').attr('class', i ? 'pinsub' : 'pinlabel')
      .attr('text-anchor', 'middle').attr('y', i * 19)
      .attr('fill', i ? T.muted : T.ink).text(line));
  }

  /* Shared keyboard contract: every selectable mark is a button that Enter and Space fire. */
  function selectable(sel, onPick, nameOf) {
    sel.attr('role', 'button').attr('tabindex', 0)
      .attr('aria-label', nameOf)
      .on('click', onPick)
      .on('keydown', function (event, d) {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onPick.call(this, event, d); }
      });
  }

  /* ------------------------------------------------------------ panel 1: cluster */
  const cluster = (() => {
    const W = 620, H = 390;
    const root = svg('venn-cluster');
    const lensLayer = root.append('g');
    const discLayer = root.append('g').attr('class', 'discs');
    const markLayer = root.append('g');
    let nodes = [], links = [], sim = null;

    function build() {
      root.selectAll('.placeholder').remove();
      const rows = rowsOf();
      if (!rows.length) {
        [lensLayer, discLayer, markLayer].forEach((l) => l.selectAll('*').remove());
        placeholder(root, W, H, ['No tagged papers yet',
          'Each polymer becomes a circle here, sized by its papers and',
          'pulled towards the polymers it is reported alongside.']);
        nodes = []; links = []; if (sim) sim.stop();
        return;
      }
      const max = d3.max(rows, (r) => r.n) || 1;
      const r = d3.scaleSqrt().domain([0, max]).range([0, 74]);
      const was = new Map(nodes.map((n) => [n.k, n]));
      nodes = rows.map((row) => {
        const old = was.get(row.k);
        return Object.assign({ x: W / 2 + (Math.random() - 0.5) * 180,
                               y: H / 2 + (Math.random() - 0.5) * 120 }, old,
                             { k: row.k, n: row.n, r: Math.max(16, r(row.n)) });
      });
      const byKey = new Map(nodes.map((n) => [n.k, n]));
      links = pairsOf().filter((p) => byKey.has(p.a) && byKey.has(p.b)).map((p) => ({
        source: byKey.get(p.a), target: byKey.get(p.b), n: p.n,
        // Jaccard, so a pair is pulled together by the share of papers they agree on
        // rather than by the raw count, which PET would otherwise dominate.
        j: p.n / (byKey.get(p.a).n + byKey.get(p.b).n - p.n),
      }));
      if (sim) sim.stop();
      sim = d3.forceSimulation(nodes)
        .force('x', d3.forceX(W / 2).strength(0.07))
        .force('y', d3.forceY(H / 2).strength(0.1))
        .force('charge', d3.forceManyBody().strength(-70))
        .force('pair', d3.forceLink(links).strength(0.5)
          .distance((l) => (l.source.r + l.target.r) * (1 - Math.min(0.6, l.j * 2.4))))
        // Circles overlap deeply, which is the message, but two centres never come
        // closer than the width of a label: a pile of unreadable captions in the middle
        // is what the long tail of rarely reported polymers does to this layout.
        .force('floor', d3.forceCollide((d) => Math.max(d.r * 0.55, 30)))
        .on('tick', render);
      sim.alpha(0.9).restart();
    }

    /* The lens two overlapping circles share, and the point inside it to label.
       Returns null when one circle contains the other or they do not meet at all. */
    function lens(a, b) {
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy);
      if (!d || d >= a.r + b.r || d <= Math.abs(a.r - b.r)) return null;
      const t = (a.r * a.r - b.r * b.r + d * d) / (2 * d);
      const h = Math.sqrt(Math.max(0, a.r * a.r - t * t));
      const mx = a.x + t * dx / d, my = a.y + t * dy / d;
      const p1 = [mx - h * dy / d, my + h * dx / d];
      const p2 = [mx + h * dy / d, my - h * dx / d];
      return {
        d: `M${p1[0]},${p1[1]}A${a.r},${a.r} 0 0,1 ${p2[0]},${p2[1]}`
          + `A${b.r},${b.r} 0 0,1 ${p1[0]},${p1[1]}`,
        cx: mx, cy: my,
      };
    }

    function render() {
      nodes.forEach((d) => {
        d.x = Math.max(d.r + 10, Math.min(W - d.r - 10, d.x));
        d.y = Math.max(d.r + 24, Math.min(H - d.r - 14, d.y));
      });

      const shown = (focus ? links.filter((l) => l.source.k === focus || l.target.k === focus)
        : []).map((l) => Object.assign({ geo: lens(l.source, l.target) }, l))
        .filter((l) => l.geo);
      lensLayer.selectAll('path').data(shown, (l) => l.source.k + '|' + l.target.k)
        .join('path')
        .attr('d', (l) => l.geo.d)
        .attr('fill', T.ink).attr('fill-opacity', 0.26)
        .attr('stroke', T.ink).attr('stroke-width', 1)
        .style('cursor', 'pointer')
        .on('click', (e, l) => { e.stopPropagation(); select(focus, [l.source.k, l.target.k]); });
      // A polymer as common as PET overlaps almost everything, and a dozen counts stacked
      // in the middle reads as noise. The largest handful carry the message.
      const labelled = [...shown].sort((a, b) => b.n - a.n).slice(0, 5);
      lensLayer.selectAll('text').data(labelled, (l) => l.source.k + '|' + l.target.k)
        .join('text').attr('class', 'pinsub').attr('text-anchor', 'middle')
        .attr('pointer-events', 'none').attr('fill', T.ink)
        .attr('stroke', T.card).attr('stroke-width', 3).attr('paint-order', 'stroke')
        .attr('x', (l) => l.geo.cx).attr('y', (l) => l.geo.cy + 3)
        .text((l) => DEBRIS.fmt(l.n));

      const disc = discLayer.selectAll('circle').data(nodes, (d) => d.k)
        .join('circle').attr('class', 'disc');
      disc.attr('cx', (d) => d.x).attr('cy', (d) => d.y).attr('r', (d) => d.r)
        .attr('fill', (d) => colour(d.k)).attr('stroke', (d) => colour(d.k));

      const mark = markLayer.selectAll('g').data(nodes, (d) => d.k).join((enter) => {
        const g = enter.append('g').style('cursor', 'grab');
        g.append('text').attr('class', 'pinlabel').attr('text-anchor', 'middle').attr('dy', '-0.1em');
        g.append('text').attr('class', 'pinsub').attr('text-anchor', 'middle').attr('dy', '1.3em');
        return g;
      });
      mark.attr('transform', (d) => `translate(${d.x},${d.y})`);
      mark.select('.pinlabel').text((d) => shortOf(d.k));
      mark.select('.pinsub').text((d) => DEBRIS.fmt(d.n));
      selectable(mark, (e, d) => select(d.k, null),
        (d) => `${labelOf(d.k)}: ${DEBRIS.fmt(d.n)} papers`);
      mark.call(d3.drag()
        .on('start', (e, d) => { sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
        .on('end', (e, d) => { sim.alphaTarget(0); d.fx = null; d.fy = null; }));
      paint();
    }

    function paint() {
      discLayer.selectAll('circle')
        .attr('fill-opacity', (d) => !focus ? 0.24 : (d.k === focus ? 0.4
          : (pair && pair.includes(d.k)) ? 0.34 : 0.07))
        .attr('stroke-width', (d) => d.k === focus ? 3 : 1.6)
        .attr('stroke-opacity', (d) => !focus || d.k === focus
          || (pair && pair.includes(d.k)) ? 1 : 0.25);
      markLayer.selectAll('g')
        .attr('opacity', (d) => !focus || d.k === focus
          || (pair && pair.includes(d.k)) ? 1 : 0.3)
        // Bring the selected polymer to the front so its label is never behind a neighbour.
        .filter((d) => d.k === focus).raise();
      if (focus) discLayer.selectAll('circle').filter((d) => d.k === focus).raise();
    }

    return { build, paint };
  })();

  /* ------------------------------------------------------------ panel 2: packing */
  const packing = (() => {
    const W = 620, H = 390;
    const root = svg('venn-packing');
    // Three flat layers rather than nested groups: with the families packed tight, a
    // ring drawn after a neighbour would otherwise cover that neighbour's name.
    const ringLayer = root.append('g');
    const kidLayer = root.append('g');
    const nameLayer = root.append('g');

    function build() {
      root.selectAll('.placeholder').remove();
      const rows = rowsOf().filter((r) => r.n > 0);
      if (!rows.length) {
        [ringLayer, kidLayer, nameLayer].forEach((l) => l.selectAll('*').remove());
        placeholder(root, W, H, ['No tagged papers yet',
          'Polymers will be grouped into their chemical families here,',
          'each circle sized by the papers naming it.']);
        return;
      }
      const byFamily = d3.group(rows, (r) => FAMILY[r.k] || 'Other');
      const tree = d3.hierarchy({
        children: [...byFamily].map(([name, kids]) => ({ name, children: kids })),
      }).sum((d) => d.n);
      d3.pack().size([W - 20, H - 24]).padding(12)(tree);
      const ox = 10, oy = 16;

      ringLayer.selectAll('circle').data(tree.children, (d) => d.data.name)
        .join('circle').attr('class', 'famring')
        .attr('cx', (d) => d.x + ox).attr('cy', (d) => d.y + oy).attr('r', (d) => d.r)
        .attr('fill', T.tint).attr('stroke', T.line);

      const kids = tree.leaves();
      const kid = kidLayer.selectAll('g').data(kids, (d) => d.data.k)
        .join((enter) => {
          const g = enter.append('g').style('cursor', 'pointer');
          g.append('circle');
          g.append('text').attr('class', 'pinlabel').attr('text-anchor', 'middle').attr('dy', '-0.05em');
          g.append('text').attr('class', 'pinsub').attr('text-anchor', 'middle').attr('dy', '1.25em');
          return g;
        });
      kid.attr('transform', (d) => `translate(${d.x + ox},${d.y + oy})`);
      kid.select('circle').attr('r', (d) => d.r).attr('fill', (d) => colour(d.data.k));
      kid.select('.pinlabel').attr('fill', '#fff').text((d) => d.r > 16 ? shortOf(d.data.k) : '');
      kid.select('.pinsub').attr('fill', '#fff').attr('fill-opacity', 0.92)
        .text((d) => d.r > 27 ? DEBRIS.fmt(d.data.n) : '');
      kid.selectAll('title').data((d) => [d]).join('title')
        .text((d) => `${labelOf(d.data.k)}: ${DEBRIS.fmt(d.data.n)} papers`);
      selectable(kid, (e, d) => select(d.data.k, null),
        (d) => `${labelOf(d.data.k)}: ${DEBRIS.fmt(d.data.n)} papers, ${FAMILY[d.data.k] || 'other'}`);

      nameLayer.selectAll('text').data(tree.children, (d) => d.data.name)
        .join('text').attr('class', 'pinsub famlabel').attr('text-anchor', 'middle')
        .attr('x', (d) => d.x + ox).attr('y', (d) => d.y + oy - d.r + 14)
        .attr('fill', T.muted).attr('pointer-events', 'none')
        .attr('stroke', T.card).attr('stroke-width', 3).attr('paint-order', 'stroke')
        .text((d) => d.data.name);
      paint();
    }

    function paint() {
      const family = focus ? (FAMILY[focus] || 'Other') : null;
      ringLayer.selectAll('circle')
        .attr('stroke', (d) => family && d.data.name === family ? T.ink : T.line)
        .attr('stroke-width', (d) => family && d.data.name === family ? 2 : 1)
        .attr('opacity', (d) => !family || d.data.name === family ? 1 : 0.4);
      nameLayer.selectAll('text')
        .attr('opacity', (d) => !family || d.data.name === family ? 1 : 0.4);
      kidLayer.selectAll('g')
        .attr('opacity', (d) => !family || (FAMILY[d.data.k] || 'Other') === family ? 1 : 0.32);
      kidLayer.selectAll('g').select('circle')
        .attr('fill-opacity', (d) => !focus || d.data.k === focus ? 0.9 : 0.5)
        .attr('stroke', (d) => d.data.k === focus ? T.ink : 'none')
        .attr('stroke-width', 2.5);
    }

    return { build, paint };
  })();

  /* ------------------------------------------------------------- panel 3: matrix */
  const matrix = (() => {
    const W = 620, H = 420;
    const root = svg('venn-matrix');
    const layer = root.append('g');
    const note = root.append('text').attr('class', 'pinsub').attr('x', 10).attr('y', H - 8);
    let keys = [];

    function build() {
      root.selectAll('.placeholder').remove();
      const rows = rowsOf();
      keys = ORDER.filter((k) => rows.some((r) => r.k === k));
      if (!keys.length) {
        layer.selectAll('*').remove(); note.text('');
        placeholder(root, W, H, ['No tagged papers yet',
          'Every polymer pair gets a cell here. The empty cells are the',
          'point: a pairing nobody has published on.']);
        return;
      }
      const side = Math.min(26, Math.floor((H - 150) / Math.max(1, keys.length)));
      const left = Math.max(66, (W - side * keys.length) / 2);
      layer.attr('transform', `translate(${left},92)`);

      const cells = [];
      keys.forEach((a, i) => keys.forEach((b, j) => cells.push({
        a, b, i, j, self: a === b, n: a === b ? countOf(a) : pairCount(a, b),
      })));

      const max = d3.max(cells.filter((c) => !c.self), (c) => c.n) || 1;
      const shade = d3.scaleLinear().domain([0, max]).range([0.06, 0.95]).clamp(true);

      const rect = layer.selectAll('rect').data(cells, (c) => c.a + '|' + c.b)
        .join('rect').style('cursor', 'pointer');
      rect.attr('x', (c) => c.j * side).attr('y', (c) => c.i * side)
        .attr('width', side - 2).attr('height', side - 2)
        .attr('fill', (c) => c.self ? colour(c.a) : T.ink)
        .attr('fill-opacity', (c) => c.self ? 0.85 : (c.n ? shade(c.n) : 0))
        .attr('stroke', (c) => c.n === 0 && !c.self ? T.line : 'none')
        .attr('stroke-dasharray', '2 2');
      rect.selectAll('title').data((c) => [c]).join('title').text((c) => c.self
        ? `${labelOf(c.a)}: ${DEBRIS.fmt(c.n)} papers`
        : c.n ? `${c.a} with ${c.b}: ${DEBRIS.fmt(c.n)} papers`
        : `${c.a} with ${c.b}: nothing published`);
      selectable(rect, (e, c) => select(c.self ? c.a : c.a, c.self ? null : [c.a, c.b]),
        (c) => c.self ? `${labelOf(c.a)} alone, ${DEBRIS.fmt(c.n)} papers`
          : `${c.a} with ${c.b}, ${DEBRIS.fmt(c.n)} papers`);

      layer.selectAll('text.rl').data(keys, (k) => k).join('text').attr('class', 'rl pinlabel')
        .attr('x', -10).attr('y', (k, i) => i * side + side / 2 + 1)
        .attr('text-anchor', 'end').attr('dy', '0.1em').text((k) => shortOf(k));
      layer.selectAll('text.cl').data(keys, (k) => k).join('text').attr('class', 'cl pinlabel')
        .attr('transform', (k, j) => `translate(${j * side + side / 2},-10) rotate(-54)`)
        .text((k) => shortOf(k));
      note.attr('fill', T.muted)
        .text('Diagonal: papers naming that polymer. Dashed: the pair has no published paper.');
      paint();
    }

    function paint() {
      layer.selectAll('rect')
        .attr('stroke', (c) => {
          const hit = pair ? (c.a === pair[0] && c.b === pair[1]) || (c.a === pair[1] && c.b === pair[0])
            : focus && c.self && c.a === focus;
          if (hit) return T.ink;
          return c.n === 0 && !c.self ? T.line : 'none';
        })
        .attr('stroke-width', (c) => {
          const hit = pair ? (c.a === pair[0] && c.b === pair[1]) || (c.a === pair[1] && c.b === pair[0])
            : focus && c.self && c.a === focus;
          return hit ? 2.5 : 1;
        })
        // The dash means "nothing published", so a highlighted cell has to drop it.
        .attr('stroke-dasharray', (c) => {
          const hit = pair ? (c.a === pair[0] && c.b === pair[1]) || (c.a === pair[1] && c.b === pair[0])
            : focus && c.self && c.a === focus;
          return hit ? null : '2 2';
        })
        .attr('opacity', (c) => !focus || c.a === focus || c.b === focus ? 1 : 0.25);
      layer.selectAll('text.rl, text.cl')
        .attr('fill', (k) => k === focus ? T.ink : T.muted)
        .attr('opacity', (k) => !focus || k === focus ? 1 : 0.4);
    }

    return { build, paint };
  })();

  /* --------------------------------------------------------------- panel 4: bars */
  const bars = (() => {
    const W = 620, H = 420;
    const root = svg('venn-bars');
    const layer = root.append('g');
    let shown = [], keys = [];

    function build() {
      root.selectAll('.placeholder').remove();
      const rows = rowsOf();
      keys = ORDER.filter((k) => rows.some((r) => r.k === k));
      shown = combosOf().slice(0, 12);
      if (!shown.length || !keys.length) {
        layer.selectAll('*').remove(); shown = [];
        placeholder(root, W, H, ['No tagged papers yet',
          'Exact polymer combinations will be ranked here: papers naming',
          'these polymers and no others.']);
        return;
      }

      const left = 62, topH = 190, dotTop = topH + 40;
      const rowH = Math.min(16, (H - dotTop - 16) / Math.max(1, keys.length));
      const x = d3.scaleBand().domain(d3.range(shown.length)).range([left, W - 14]).padding(0.26);
      const y = d3.scaleLinear().domain([0, d3.max(shown, (c) => c.n)]).range([topH, 26]);

      layer.selectAll('line.base').data([0]).join('line').attr('class', 'base')
        .attr('x1', left - 8).attr('x2', W - 14).attr('y1', topH).attr('y2', topH)
        .attr('stroke', T.line);

      const col = layer.selectAll('g.col').data(shown, (c) => c.k.join('+'))
        .join((enter) => {
          const g = enter.append('g').attr('class', 'col').style('cursor', 'pointer');
          g.append('rect').attr('class', 'bar');
          g.append('text').attr('class', 'pinsub n').attr('text-anchor', 'middle');
          g.append('line').attr('class', 'spine');
          return g;
        });
      col.attr('transform', (c, i) => `translate(${x(i)},0)`);
      col.select('.bar').attr('x', 0).attr('width', x.bandwidth())
        .attr('y', (c) => y(c.n)).attr('height', (c) => topH - y(c.n))
        .attr('fill', (c) => c.k.length === 1 ? colour(c.k[0]) : T.ink);
      col.select('.n').attr('x', x.bandwidth() / 2).attr('y', (c) => y(c.n) - 5)
        .attr('fill', T.muted).text((c) => DEBRIS.fmt(c.n));
      col.select('.spine').attr('x1', x.bandwidth() / 2).attr('x2', x.bandwidth() / 2)
        .attr('y1', (c) => dotTop + d3.min(c.k.map((k) => keys.indexOf(k))) * rowH)
        .attr('y2', (c) => dotTop + d3.max(c.k.map((k) => keys.indexOf(k))) * rowH)
        .attr('stroke', T.ink).attr('stroke-width', 2);
      col.selectAll('circle').data((c) => keys.map((k, ri) => ({ on: c.k.includes(k), k, ri })))
        .join('circle')
        .attr('cx', x.bandwidth() / 2).attr('cy', (d) => dotTop + d.ri * rowH)
        .attr('r', Math.max(3, rowH / 2.8))
        .attr('fill', (d) => d.on ? T.ink : T.line);
      selectable(col, (e, c) => select(c.k[0], c.k.length > 1 ? [c.k[0], c.k[1]] : null),
        (c) => `${c.k.join(' and ')} and nothing else: ${DEBRIS.fmt(c.n)} papers`);

      layer.selectAll('text.rl').data(keys, (k) => k).join('text').attr('class', 'rl pinlabel')
        .attr('x', left - 14).attr('y', (k, i) => dotTop + i * rowH + 3)
        .attr('text-anchor', 'end').text((k) => shortOf(k));
      layer.selectAll('text.ax').data([0]).join('text').attr('class', 'ax pinsub')
        .attr('transform', `translate(${left - 44},${topH / 2}) rotate(-90)`)
        .attr('text-anchor', 'middle').attr('fill', T.muted).text('Papers');
      paint();
    }

    function paint() {
      const wanted = pair || (focus ? [focus] : null);
      layer.selectAll('g.col')
        .attr('opacity', (c) => !wanted || wanted.every((k) => c.k.includes(k)) ? 1 : 0.26);
      layer.selectAll('g.col').select('.bar')
        .attr('stroke', (c) => wanted && wanted.every((k) => c.k.includes(k)) ? T.ink : 'none')
        .attr('stroke-width', 2);
      layer.selectAll('text.rl')
        .attr('fill', (k) => wanted && wanted.includes(k) ? T.ink : T.muted)
        .attr('font-weight', (k) => wanted && wanted.includes(k) ? 700 : 600);
    }

    return { build, paint };
  })();

  /* ----------------------------------------------------------------- ladder */
  function ladder() {
    const data = (B.ladder || {})[ladderScope] || [];
    if (!data.length) { document.getElementById('ladder').innerHTML = '<p class="empty">No tagged papers yet.</p>'; return; }
    const rungLabels = B.rung_labels || {};
    // Rungs 1 to 5 in the Elora ramp; rung 6 in --pet, drawn even when empty.
    const rungColour = (r) => r === 6 ? T.pet
      : ['#C7D0E8', '#9FADD4', '#7589BE', '#4F67A8', '#2A3C78'][r - 1];
    const traces = [1, 2, 3, 4, 5, 6].map((r) => ({
      type: 'bar', orientation: 'h', name: rungLabels[r] || '',
      y: data.map((d) => d.label), x: data.map((d) => d.rungs[r - 1] || 0),
      marker: { color: rungColour(r), line: { color: '#fff', width: 1 } },
      hovertemplate: `%{y}<br>${DEBRIS.esc(rungLabels[r] || '')}<br>%{x} papers<extra></extra>`,
    }));
    DEBRIS.plot('ladder', traces, {
      barmode: 'stack', bargap: 0.28,
      margin: { l: 230, r: 20, t: 8, b: 44 },
      xaxis: { title: { text: 'Papers', font: { size: 11 } }, gridcolor: T.line },
      yaxis: { automargin: true, tickfont: { size: 11 } },
      legend: { orientation: 'h', y: -0.1, font: { size: 10 } },
    });
    document.getElementById('ladder-legend').innerHTML = [1, 2, 3, 4, 5, 6].map((r) =>
      `<span><i style="background:${rungColour(r)}"></i>${DEBRIS.esc(rungLabels[r] || '')}</span>`)
      .join('') + '<span style="color:#8A5A14">Reversible is the evidence an enzyme therapeutic can test.</span>';
    setLadder(ladderScope === 'pet' ? 'pet=1' : '');
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
    const rows = B.trend || [];
    if (!rows.length) return;
    const x = rows.map((r) => r.date);
    // PET and the four most studied polymers show by default; the rest are a legend click away.
    const named = ORDER.slice();
    const tagged = rows.some((r) => Object.keys(r.by || {}).length);
    const top = named.slice().sort((a, b) => ((rows[rows.length - 1].by || {})[b] || 0)
                                          - ((rows[rows.length - 1].by || {})[a] || 0)).slice(0, 4);
    const traces = [
      { type: 'scatter', mode: 'lines', name: 'All papers', x, y: rows.map((r) => r.n),
        line: { color: T.blue, width: 2.5, shape: 'spline' },
        fill: 'tozeroy', fillcolor: 'rgba(56,80,152,0.10)',
        hovertemplate: 'All papers, 12 months to %{x|%d %b %Y}: %{y:,}<extra></extra>' },
    ].concat(named.map((k) => ({
      type: 'scatter', mode: 'lines', name: shortOf(k), x,
      y: rows.map((r) => (r.by || {})[k] || 0),
      visible: top.includes(k) || k === 'PET' ? true : 'legendonly',
      line: { color: colour(k), width: 1.8, shape: 'spline' },
      hovertemplate: `${labelOf(k)}, 12 months to %{x|%d %b %Y}: %{y:,}<extra></extra>`,
    })));
    DEBRIS.plot('years', traces, { margin: { l: 50, r: 16, t: 8, b: 38 }, showlegend: true,
         annotations: tagged ? [] : [{ xref: 'paper', yref: 'paper', x: 0.01, y: 0.97,
           xanchor: 'left', showarrow: false, font: { size: 11, color: T.muted },
           text: 'Polymer lines fill in as the tagger reads the corpus' }],
         xaxis: { type: 'date', dtick: 'M24', tickformat: '%Y', gridcolor: 'rgba(0,0,0,0)',
                  range: [x[0], x[x.length - 1]] },
         yaxis: { title: { text: 'Papers per year', font: { size: 11 } } } });

    // The button follows the polymer lines on show; a point opens its twelve months.
    const el = document.getElementById('years');
    const shown = () => (el.data || []).slice(1)
      .map((t, i) => (t.visible === true || t.visible === undefined ? named[i] : null)).filter(Boolean);
    // Until a line is shown or hidden the button opens every paper; after that, the
    // polymers on show (any of them).
    let touched = false;
    const sync = () => {
      const keys = shown();
      setYears(touched && keys.length && keys.length < named.length ? 'polymers=' + keys.join(',') : '');
    };
    sync();
    if (el.on) {
      el.on('plotly_restyle', () => { touched = true; sync(); });
      el.on('plotly_click', (ev) => {
        const point = ev.points[0];
        const end = point.x.slice(0, 10);
        const start = new Date(end + 'T00:00:00Z');
        start.setUTCDate(start.getUTCDate() - 365);
        const qs = new URLSearchParams({ entered_from: start.toISOString().slice(0, 10), entered_to: end });
        if (point.curveNumber > 0) qs.set('polymer', named[point.curveNumber - 1]);
        window.location = '/papers?' + qs.toString();
      });
    }
  }

  DEBRIS.chips('.organ-chip', (value) => { organ = value; rebuildAll(); });
  DEBRIS.chips('.ladder-chip', (value) => { ladderScope = value; ladder(); });
  document.getElementById('pet-only').addEventListener('change', (e) => {
    petOnly = e.target.checked; rebuildAll();
  });

  rebuildAll();
  ladder();
  years();
})();
