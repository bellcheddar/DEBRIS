/* 02 Body: the anatomical figure, the ranked rail and the polymer profile cards.

   One selection runs the tab. Choosing a tissue in any panel lights its organ on the
   figure, raises its pin, marks its rail row, brings its card forward and fills the
   detail card beneath. The roster comes from config/vocab.toml: every site's anchor,
   its organ systems, its region and which organ drawing belongs to it. Adding a tissue
   is an entry in that file and nothing here changes. */
(() => {
  const B = window.BODY || {};
  const nodes = (B.nodes || []).map((n) => ({ ...n }));
  const svgRoot = document.getElementById('bodymap');
  if (!svgRoot || !nodes.length) return;

  const T = DEBRIS.T;
  const SHORT = B.polymer_short || {};
  const LABELS = B.polymer_labels || {};
  const shortOf = (k) => SHORT[k] || k;
  const labelOf = (k) => LABELS[k] || k;

  // The anatomy is drawn on its own 360 x 720 space. One transform places it on the
  // 760 x 960 stage (a half-width panel), and the pins use the same numbers, so the
  // drawing and the pins cannot drift apart however the figure is scaled or moved.
  const STAGE_H = 960;
  const FIG_S = 1.3, FIG_X = 380 - 180 * 1.3, FIG_Y = -12;
  // The label columns sit just clear of the arms (x 74 to 286 in the drawing).
  const LEFT_COL = 236, RIGHT_COL = 524;
  const place = (x, y) => [FIG_X + x * FIG_S, FIG_Y + y * FIG_S];
  const MID = FIG_X + 180 * FIG_S;
  const maxCount = Math.max(1, B.max_count || 1);
  const rScale = d3.scaleSqrt().domain([0, maxCount]).range([0, 17]);
  const petRamp = d3.scaleLinear().domain([0, 0.55])
    .range([T.soft, T.pet]).clamp(true);

  let selected = null;
  const setBody = DEBRIS.papersButton(document.getElementById('card-body'));
  let petMode = false;
  let railMode = 'count';
  let cardMode = 'count';

  d3.select('#figart').attr('transform', `translate(${FIG_X},${FIG_Y}) scale(${FIG_S})`);

  nodes.forEach((n) => {
    [n.hx, n.hy] = place(n.x, n.y);           // the anatomical home
    n.px = n.hx; n.py = n.hy;                 // where the pin is now
    n.petShare = n.count ? n.pet_count / n.count : 0;
  });

  const radius = (n) => n.count ? Math.max(5, rScale(n.count)) : 4;
  const pinColour = (n) => petMode ? petRamp(n.petShare) : T.blue;

  /* ------------------------------------------------------------------ selection */
  function select(key) {
    selected = key === selected ? null : key;
    paintAll();
    detail();
  }

  function query(node) {
    const qs = new URLSearchParams();
    qs.set('organs', (node.organs || []).join(','));
    return qs.toString();
  }

  function selbar() {
    const el = document.getElementById('selbar');
    const node = nodes.find((n) => n.key === selected);
    if (!node) {
      el.innerHTML = '<span class="idle">Select a tissue in any panel. The organ lights up on '
        + 'the figure, and the selection becomes a filter you can open in the Papers tab.</span>';
      return;
    }
    el.innerHTML =
      `<span class="what"><i style="background:${pinColour(node)}"></i>${DEBRIS.esc(node.label)}</span>`
      + `<span class="howmany">${DEBRIS.fmt(node.count)} papers · `
      + `${Math.round(node.petShare * 100)}% name PET`
      + `${node.max_rung ? ' · ' + DEBRIS.esc(DEBRIS.evidence(node.max_rung).toLowerCase()) : ''}</span>`
      + '<span class="spacer"></span>'
      + `<a class="btn ghost" href="/papers?${query(node)}">Open in Papers</a>`
      + '<button class="chip" type="button" id="clearsel">Clear</button>';
    document.getElementById('clearsel').onclick = () => { selected = null; paintAll(); detail(); };
    DEBRIS.setOpen(el.querySelector('.btn'), query(node), true);
  }

  function selectable(sel, onPick, nameOf) {
    sel.attr('role', 'button').attr('tabindex', 0).attr('aria-label', nameOf)
      .on('click', onPick)
      .on('keydown', function (event, d) {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onPick.call(this, event, d); }
      });
  }

  function paintAll() {
    { const node = nodes.find((n) => n.key === selected); setBody(node ? query(node) : '', !!node); }
    figure.paint(); rail.paint(); cards.paint(); selbar();
    ['panel-figure', 'panel-rail', 'panel-cards'].forEach((id) =>
      document.getElementById(id).classList.toggle('lit', !!selected));
  }

  /* -------------------------------------------------------------- panel 1: figure */
  const figure = (() => {
    const leaders = d3.select('#leaders');
    const pins = d3.select('#pins');
    const labels = d3.select('#pinlabels');
    const art = d3.select('#bodymap').select('.figure');

    /* Push labels apart until none of them overlap, then hold them inside the stage.
       With a dozen sites in one abdomen this is the whole reason the panel works. */
    function relax(list, gap, lo, hi) {
      list.sort((a, b) => a.ly - b.ly);
      for (let pass = 0; pass < 140; pass++) {
        for (let i = 1; i < list.length; i++) {
          const d = list[i].ly - list[i - 1].ly;
          if (d < gap) { const push = (gap - d) / 2; list[i - 1].ly -= push; list[i].ly += push; }
        }
        if (list.length) {
          list[0].ly = Math.max(lo, list[0].ly);
          list[list.length - 1].ly = Math.min(hi, list[list.length - 1].ly);
        }
      }
    }

    function draw() {
      nodes.forEach((n) => { n.ly = n.py; n.side = n.px < MID ? 'left' : 'right'; });
      const left = nodes.filter((n) => n.side === 'left');
      const right = nodes.filter((n) => n.side === 'right');
      relax(left, 52, 32, STAGE_H - 24);
      relax(right, 52, 32, STAGE_H - 24);

      leaders.selectAll('path').data(nodes, (d) => d.key).join('path')
        .attr('class', 'leaderline')
        .attr('d', (d) => {
          const ex = d.side === 'left' ? LEFT_COL : RIGHT_COL;
          const bend = d.side === 'left' ? ex + 30 : ex - 30;
          return `M${d.px},${d.py} L${bend},${d.ly} L${ex},${d.ly}`;
        });

      const pin = pins.selectAll('g').data(nodes, (d) => d.key).join((enter) => {
        const g = enter.append('g').attr('class', 'pin').style('cursor', 'grab');
        g.append('circle').attr('class', 'halo').attr('fill', 'url(#pinglow)');
        g.append('circle').attr('class', 'core');
        return g;
      });
      pin.attr('transform', (d) => `translate(${d.px},${d.py})`);
      pin.select('.halo').attr('r', (d) => radius(d) + 13);
      pin.select('.core').attr('r', radius);
      selectable(pin, (e, d) => select(d.key),
        (d) => `${d.label}: ${DEBRIS.fmt(d.count)} papers, ${Math.round(d.petShare * 100)} per cent naming PET`);
      pin.call(d3.drag()
        .on('drag', (e, d) => {
          d.px = Math.max(FIG_X - 30, Math.min(FIG_X + 360 * FIG_S + 30, e.x));
          d.py = Math.max(22, Math.min(STAGE_H - 20, e.y));
          draw();
        }));

      const lab = labels.selectAll('g').data(nodes, (d) => d.key).join((enter) => {
        const g = enter.append('g').style('cursor', 'pointer');
        g.append('text').attr('class', 'pinlabel');
        g.append('text').attr('class', 'pinsub').attr('dy', '1.3em');
        g.append('line').attr('class', 'leaderline');
        return g;
      });
      lab.attr('transform', (d) => `translate(${d.side === 'left' ? LEFT_COL : RIGHT_COL},${d.ly})`);
      lab.select('.pinlabel')
        .attr('text-anchor', (d) => d.side === 'left' ? 'end' : 'start')
        .attr('dy', '-0.3em').text((d) => d.label);
      lab.select('.pinsub')
        .attr('text-anchor', (d) => d.side === 'left' ? 'end' : 'start')
        .text((d) => d.count
          ? `${DEBRIS.fmt(d.count)} papers · ${Math.round(d.petShare * 100)}% PET`
          : 'no papers yet');
      lab.select('line')
        .attr('x1', (d) => d.side === 'left' ? -112 : 0)
        .attr('x2', (d) => d.side === 'left' ? 0 : 112)
        .attr('y1', 6).attr('y2', 6);
      selectable(lab, (e, d) => select(d.key),
        (d) => `${d.label}: ${DEBRIS.fmt(d.count)} papers`);
      paint();
    }

    function paint() {
      const node = nodes.find((n) => n.key === selected);
      art.classed('hasfocus', !!node);
      art.selectAll('.organ').classed('on', function () {
        return !!node && this.getAttribute('data-art') === node.art;
      });
      pins.selectAll('g.pin')
        .classed('on', (d) => d.key === selected)
        .classed('pulse', (d) => d.key === selected)
        .attr('opacity', (d) => !selected || d.key === selected ? 1 : 0.42);
      pins.selectAll('g.pin').select('.halo')
        .style('color', (d) => pinColour(d));
      pins.selectAll('g.pin').select('.core').attr('fill', (d) => pinColour(d));
      // Bring the chosen pin out from under its neighbours.
      pins.selectAll('g.pin').filter((d) => d.key === selected).raise();
      labels.selectAll('g')
        .attr('opacity', (d) => !selected || d.key === selected ? 1 : 0.4);
      labels.selectAll('g').select('.pinlabel')
        .attr('fill', (d) => d.key === selected ? T.ink : T.fg);
      leaders.selectAll('path').classed('on', (d) => d.key === selected);
    }

    function reset() { nodes.forEach((n) => { n.px = n.hx; n.py = n.hy; }); draw(); }

    return { draw, paint, reset };
  })();

  /* ---------------------------------------------------------------- panel 2: rail */
  const rail = (() => {
    const W = 620, H = 560;
    const root = d3.select('#rail');
    // Room for the longest label in the roster: "Reproductive and placental" needs it.
    const layer = root.append('g').attr('transform', 'translate(182,16)');
    const RW = W - 182 - 58;

    const value = (n) => railMode === 'count' ? n.count
      : railMode === 'pet' ? n.petShare : (n.max_rung || 0);
    const shown = (n) => railMode === 'count' ? DEBRIS.fmt(n.count)
      : railMode === 'pet' ? Math.round(n.petShare * 100) + '%' : (DEBRIS.evidence(n.max_rung) || '—');

    function build() {
      const data = [...nodes].sort((a, b) => value(b) - value(a));
      const max = d3.max(data, value) || 1;
      const x = d3.scaleLinear().domain([0, max]).range([0, RW]);
      const rowH = Math.min(38, (H - 32) / data.length);

      const row = layer.selectAll('g').data(data, (d) => d.key).join((enter) => {
        const g = enter.append('g').style('cursor', 'pointer');
        g.append('rect').attr('class', 'track');
        g.append('rect').attr('class', 'val');
        g.append('text').attr('class', 'pinlabel name').attr('text-anchor', 'end');
        g.append('text').attr('class', 'pinsub num');
        return g;
      });
      row.attr('transform', (d, i) => `translate(0,${i * rowH})`);
      row.select('.track').attr('x', 0).attr('y', 3).attr('width', RW)
        .attr('height', Math.max(9, rowH - 13)).attr('fill', T.tint);
      row.select('.val').attr('x', 0).attr('y', 3).attr('height', Math.max(9, rowH - 13))
        .attr('width', (d) => Math.max(0, x(value(d))));
      row.select('.name').attr('x', -12).attr('y', rowH / 2 + 1).attr('dy', '0.1em')
        .text((d) => d.label);
      row.select('.num').attr('y', rowH / 2 + 1).attr('dy', '0.1em').attr('fill', T.muted)
        .attr('x', (d) => Math.max(0, x(value(d))) + 8).text(shown);
      selectable(row, (e, d) => select(d.key),
        (d) => `${d.label}: ${shown(d)}`);
      paint();
    }

    function paint() {
      layer.selectAll('g').select('.val')
        .attr('fill', (d) => railMode === 'pet' ? T.pet : T.ink)
        .attr('fill-opacity', (d) => !selected || d.key === selected ? 0.9 : 0.3);
      layer.selectAll('g').select('.name')
        .attr('fill', (d) => d.key === selected ? T.ink : T.fg)
        .attr('font-weight', (d) => d.key === selected ? 700 : 600);
    }

    return { build, paint };
  })();

  /* --------------------------------------------------------------- panel 3: cards */
  const cards = (() => {
    const W = 620, H = 560;
    const root = d3.select('#cards');
    const layer = root.append('g').attr('transform', 'translate(10,12)');
    const COLS = 3, CW = 200;
    // Row height follows the roster: 13 tissues need five rows, 18 will need six, and a
    // card that does not fit is a tissue the reader never sees.
    const CH = Math.min(108, (H - 20) / Math.ceil(nodes.length / COLS));
    const REGIONS = B.regions || [];

    function build() {
      const data = [...nodes].sort((a, b) => cardMode === 'count'
        ? b.count - a.count
        : REGIONS.indexOf(a.region) - REGIONS.indexOf(b.region) || b.count - a.count);

      const card = layer.selectAll('g.card').data(data, (d) => d.key).join((enter) => {
        const g = enter.append('g').attr('class', 'card').style('cursor', 'pointer');
        g.append('rect').attr('class', 'frame');
        g.append('text').attr('class', 'pinlabel nm');
        g.append('text').attr('class', 'pinsub ct');
        g.append('text').attr('class', 'pinsub rg');
        g.append('g').attr('class', 'bands');
        return g;
      });
      card.attr('transform', (d, i) => `translate(${(i % COLS) * CW},${Math.floor(i / COLS) * CH})`);
      card.select('.frame').attr('x', 0).attr('y', 0).attr('width', CW - 12)
        .attr('height', CH - 12).attr('fill', T.card);
      card.select('.nm').attr('x', 10).attr('y', 20)
        .text((d) => d.label.length > 20 ? d.label.slice(0, 19) + '…' : d.label);
      card.select('.ct').attr('x', 10).attr('y', 35).attr('fill', T.muted)
        .text((d) => d.count ? `${DEBRIS.fmt(d.count)} papers` : 'no papers yet');
      card.select('.rg').attr('x', 10).attr('y', CH - 22).attr('fill', T.muted)
        .text((d) => d.mix.length ? `${d.region} · mostly ${shortOf(d.mix[0].k)}` : d.region);

      card.select('.bands').selectAll('rect').data((d) => {
        let acc = 0;
        return (d.mix || []).slice(0, 6).map((m) => {
          const seg = { k: m.k, x: acc, w: m.share * (CW - 32) };
          acc += seg.w;
          return seg;
        });
      }).join('rect')
        .attr('x', (s) => 10 + s.x).attr('y', 44).attr('height', 20)
        .attr('width', (s) => Math.max(1, s.w - 1))
        .attr('fill', (s) => DEBRIS.colourFor(s.k));
      card.select('.bands').selectAll('rect').selectAll('title').data((s) => [s])
        .join('title').text((s) => labelOf(s.k));
      selectable(card, (e, d) => select(d.key),
        (d) => `${d.label}: ${DEBRIS.fmt(d.count)} papers`
          + (d.mix.length ? `, mostly ${labelOf(d.mix[0].k)}` : ''));
      paint();
    }

    function paint() {
      layer.selectAll('g.card').select('.frame')
        .attr('stroke', (d) => d.key === selected ? T.ink : T.line)
        .attr('stroke-width', (d) => d.key === selected ? 2.5 : 1);
      layer.selectAll('g.card')
        .attr('opacity', (d) => !selected || d.key === selected ? 1 : 0.46);
      // The chosen card sits over its neighbours' borders rather than under them.
      layer.selectAll('g.card').filter((d) => d.key === selected).raise();
    }

    return { build, paint };
  })();

  /* ---------------------------------------------------------------- detail card */
  function detail() {
    const node = nodes.find((n) => n.key === selected);
    const title = document.getElementById('panel-title');
    const sub = document.getElementById('panel-sub');
    const body = document.getElementById('panel-body');
    if (!node) {
      title.textContent = 'Select a tissue';
      sub.textContent = 'Pick a pin, a rail row or a card for the polymers reported there, '
        + 'the pathways most often co-tagged and the papers with the most direct evidence.';
      body.innerHTML = '';
      return;
    }
    title.textContent = node.label;
    const share = node.count ? Math.round((node.pet_count / node.count) * 100) : 0;
    sub.innerHTML = `<span class="mono">${DEBRIS.fmt(node.count)}</span> verified papers · `
      + `<span class="mono" style="color:var(--pet)">${share}%</span> name PET`
      + (node.max_rung ? ` · evidence reaches <b>${DEBRIS.esc(DEBRIS.evidence(node.max_rung).toLowerCase())}</b>` : '');

    const heading = (text) => `<h3 style="font-size:9.5px;letter-spacing:0.3em;`
      + `text-transform:uppercase;color:var(--el-muted);margin:16px 0 7px">${text}</h3>`;
    const polymers = (node.polymers || []).slice(0, 10).map((p) =>
      `<a class="tag" href="/papers?polymer=${encodeURIComponent(p.key)}&organs=`
      + `${encodeURIComponent((node.organs || []).join(','))}"`
      + ` style="border-left:3px solid ${DEBRIS.colourFor(p.key)}">`
      + `${DEBRIS.esc(shortOf(p.key))} ${p.n}</a>`).join(' ');
    const pathways = (node.pathways || []).map((p) =>
      `<a class="tag" href="/papers?pathway=${encodeURIComponent(p.key)}&organs=`
      + `${encodeURIComponent((node.organs || []).join(','))}">${DEBRIS.esc(p.label)} ${p.n}</a>`).join(' ');
    const papers = (node.papers || []).map((p) => `
      <article class="paper" style="padding:11px 12px">
        <div class="meta"><span class="mono">${DEBRIS.esc(p.journal || '')} ${p.year || ''}</span>
          ${p.max_rung ? `<span class="tag rung">${DEBRIS.esc(DEBRIS.evidence(p.max_rung))}</span>` : ''}</div>
        <h3 style="font-size:13px">${DEBRIS.esc(p.title || '')}</h3>
        ${p.summary ? `<p class="summary" style="font-size:12px">${DEBRIS.esc(p.summary)}</p>` : ''}
        <div class="meta"><button class="chip" type="button" data-pmid="${p.pmid}">Detail</button></div>
      </article>`).join('');
    body.innerHTML = heading('Polymers reported here')
      + `<div class="tags" style="display:flex;flex-wrap:wrap;gap:6px">${polymers || '<span class="empty">none tagged</span>'}</div>`
      + heading('Top pathways')
      + `<div class="tags" style="display:flex;flex-wrap:wrap;gap:6px">${pathways || '<span class="empty">none tagged</span>'}</div>`
      + heading('Strongest papers')
      + `<div style="display:grid;gap:10px">${papers || '<span class="empty">none yet</span>'}</div>`
      + `<p style="margin-top:14px"><a class="btn ghost" href="/papers?${query(node)}">`
      + `See all ${DEBRIS.fmt(node.count)} papers</a></p>`;
    body.querySelectorAll('[data-pmid]').forEach((btn) =>
      btn.addEventListener('click', () => DEBRIS.openPaper(btn.dataset.pmid)));
    const all = body.querySelector('p .btn');
    if (all) { all.dataset.label = 'Open in Papers'; DEBRIS.setOpen(all, query(node), true); }
  }

  document.getElementById('reset-pins').addEventListener('click', () => figure.reset());
  DEBRIS.chips('.rail-chip', (value) => { railMode = value; rail.build(); });
  DEBRIS.chips('.card-chip', (value) => { cardMode = value; cards.build(); });

  figure.draw();
  rail.build();
  cards.build();
  paintAll();
  detail();
})();
