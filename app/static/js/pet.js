/* 05 PET Watch: papers naming PET by tissue, mechanism and kind of evidence, the
   dose-response and reversibility reading list, and what is rising within PET. Every
   panel's pick drives its own Open in Papers link and the card's header button. */
(() => {
  const B = window.PET || {};
  const T = DEBRIS.T;
  const PET = T.pet;
  const PET_PALE = '#E9C99A';
  // On a phone the category labels get less room so the bars keep some.
  const narrow = () => window.matchMedia('(max-width:600px)').matches;
  const left = (wide) => (narrow() ? Math.min(wide, 118) : wide);
  const tick = () => ({ size: narrow() ? 9.5 : 11 });

  const setCard = DEBRIS.papersButton(document.getElementById('card-pet'));
  const panelSet = (name, qs, sel) => {
    const q = new URLSearchParams(qs);
    q.set('polymers', 'PET');
    DEBRIS.setOpen(document.querySelector(`[data-open="${name}"]`), q.toString(), sel);
    setCard(sel ? q.toString() : 'polymers=PET', true);
  };
  setCard('polymers=PET', true);
  ['tissues', 'mechanisms', 'evidence', 'rising'].forEach((n) =>
    DEBRIS.setOpen(document.querySelector(`[data-open="${n}"]`), 'polymers=PET', true));

  /* A horizontal bar panel whose bars each open a filter, toggled by a second click. */
  function bars(id, name, rows, param) {
    const el = document.getElementById(id);
    if (!rows.length) { el.innerHTML = '<p class="empty">No data yet.</p>'; return; }
    const r = rows.slice().reverse();
    let pick = null;
    const draw = () => {
      DEBRIS.plot(id, [{
        type: 'bar', orientation: 'h', x: r.map((d) => d.n), y: r.map((d) => d.label),
        marker: { color: r.map((d) => (!pick || d.key === pick ? PET : PET_PALE)) },
        hovertemplate: '%{y}: %{x:,} PET papers<extra></extra>',
      }], { margin: { l: left(170), r: 18, t: 8, b: 34 }, hovermode: 'closest',
        yaxis: { automargin: !narrow(), gridcolor: 'rgba(0,0,0,0)', tickfont: tick() },
        xaxis: { title: { text: 'Papers naming PET', font: { size: 11 } } } });
      if (el.removeAllListeners) el.removeAllListeners('plotly_click');
      el.on('plotly_click', (ev) => {
        const d = r[ev.points[0].pointNumber];
        pick = pick === d.key ? null : d.key;
        panelSet(name, pick ? `${param}=${encodeURIComponent(pick)}` : '', !!pick);
        draw();
      });
    };
    draw();
  }

  /* ---------------------------------------------------------- evidence + reading list */
  function evidence() {
    const LAB = B.rung_labels || {};
    const keys = ['1', '2', '3', '4', '5', '6'].reverse();
    const strong = new Set(['5', '6']);   // what an enzyme therapy can test against
    const el = document.getElementById('pet-evidence');
    let pick = null;
    const draw = () => {
      DEBRIS.plot('pet-evidence', [{
        type: 'bar', orientation: 'h', x: keys.map((k) => (B.rungs || {})[k] || 0),
        y: keys.map((k) => LAB[k] || k),
        marker: { color: keys.map((k) => (pick && k !== pick ? PET_PALE : strong.has(k) ? T.ink : PET)) },
        hovertemplate: '%{y}: %{x:,} PET papers<extra></extra>',
      }], { margin: { l: left(190), r: 18, t: 8, b: 30 }, hovermode: 'closest',
        yaxis: { automargin: !narrow(), gridcolor: 'rgba(0,0,0,0)', tickfont: tick() } });
      if (el.removeAllListeners) el.removeAllListeners('plotly_click');
      el.on('plotly_click', (ev) => {
        const k = keys[ev.points[0].pointNumber];
        pick = pick === k ? null : k;
        panelSet('evidence', pick ? `rungs=${pick}` : '', !!pick);
        draw();
      });
    };
    draw();
    const list = document.getElementById('pet-reading');
    list.innerHTML = (B.reading || []).map((p) => {
      const rev = p.rungs.includes(6);
      return `<li><span class="ev${rev ? ' rev' : ''}">${rev ? 'Reversible' : 'Dose-response'}</span>
        <span><a href="/papers?q=${p.pmid}" data-pmid="${p.pmid}">${DEBRIS.esc(p.title)}</a>
        <span class="src">${DEBRIS.esc(p.journal || '')} ${p.year || ''}</span></span></li>`;
    }).join('');
    list.addEventListener('click', (e) => {
      const a = e.target.closest('a[data-pmid]');
      if (!a) return;
      e.preventDefault();
      DEBRIS.openPaper(a.dataset.pmid);
    });
  }

  /* ---------------------------------------------------------- rising within PET */
  function rising() {
    const W = B.windows || {};
    const share = (n, d) => (d ? ((100 * n) / d).toFixed(1) : '0');
    document.getElementById('pet-rise-head').innerHTML =
      `PET papers, past 12 months: <b>${DEBRIS.fmt(W.pet_now)}</b> (${share(W.pet_now, W.corpus_now)}% of the corpus), `
      + `against ${DEBRIS.fmt(W.pet_before)} (${share(W.pet_before, W.corpus_before)}%) the year before`;
    const rows = (B.rising || []).slice().reverse();
    const el = document.getElementById('pet-rising');
    if (!rows.length) { el.innerHTML = '<p class="empty">No data yet.</p>'; return; }
    const y = rows.map((r) => (narrow() ? r.label
      : `${r.label} <span style="color:${T.muted}">${r.kind === 'tissue' ? 'tissue' : 'mechanism'}</span>`));
    let pick = null;   // {key, kind}
    const draw = () => {
      const on = (r) => !pick || (pick.key === r.key && pick.kind === r.kind);
      DEBRIS.plot('pet-rising', [
        ...rows.map((r, i) => ({ type: 'scatter', mode: 'lines', x: [r.before, r.now], y: [y[i], y[i]],
          line: { color: on(r) ? T.line : '#EEF0F5', width: 3 }, hoverinfo: 'skip' })),
        { type: 'scatter', mode: 'markers', name: 'Year before', x: rows.map((r) => r.before), y,
          marker: { size: 10, color: rows.map((r) => (on(r) ? '#C9CEDC' : '#EEF0F5')) },
          customdata: rows.map((r) => r.before), hovertemplate: '%{customdata} PET papers the year before<extra></extra>' },
        { type: 'scatter', mode: 'markers', name: 'Past 12 months', x: rows.map((r) => r.now), y,
          marker: { size: 12, color: rows.map((r) => (on(r) ? PET : PET_PALE)) },
          customdata: rows.map((r) => r.now), hovertemplate: '%{customdata} PET papers in the past 12 months<extra></extra>' },
      ], { margin: { l: left(210), r: 44, t: 8, b: 40 }, showlegend: false, hovermode: 'closest',
        yaxis: { automargin: !narrow(), gridcolor: 'rgba(0,0,0,0)', tickfont: tick() },
        xaxis: { rangemode: 'tozero', title: { text: narrow() ? 'PET papers: year before (grey), past 12 months' : 'PET papers, the year before (grey) and the past 12 months', font: { size: narrow() ? 10 : 11 } } },
        annotations: rows.map((r, i) => ({ x: r.now, y: y[i], xanchor: 'left', xshift: 10, showarrow: false,
          text: `×${((r.now || 0) / Math.max(1, r.before)).toFixed(1)}`, font: { size: 10, color: T.muted } })) });
      if (el.removeAllListeners) el.removeAllListeners('plotly_click');
      el.on('plotly_click', (ev) => {
        // The first traces are the connecting lines, one per row; then the two marker sets.
        const pt = ev.points[0];
        const r = rows[pt.curveNumber < rows.length ? pt.curveNumber : pt.pointNumber];
        if (!r) return;
        pick = pick && pick.key === r.key && pick.kind === r.kind ? null : { key: r.key, kind: r.kind };
        const qs = pick ? new URLSearchParams({ [r.kind === 'tissue' ? 'tissue' : 'pathway']: r.key,
          entered_from: W.now_from, entered_to: W.to }).toString() : '';
        panelSet('rising', qs, !!pick);
        draw();
      });
    };
    draw();
  }

  bars('pet-tissues', 'tissues', B.tissues || [], 'tissue');
  bars('pet-mechanisms', 'mechanisms', B.pathways || [], 'pathway');
  evidence();
  rising();
})();
