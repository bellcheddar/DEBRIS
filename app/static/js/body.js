/* 02 Body: the clickable body map and its side panel. */
(() => {
  const B = window.BODY || {};
  const nodes = B.nodes || [];
  const svgNodes = document.getElementById('nodes');
  if (!svgNodes) return;
  let petOnly = false;
  let selected = null;

  const maxCount = Math.max(1, B.max_count || 1);
  const radius = (n) => n === 0 ? 7 : 11 + 22 * Math.sqrt(n / maxCount);

  function petDensityColour(node) {
    if (!node.count) return DEBRIS.T.other;
    const share = node.pet_count / node.count;
    // One hue, five steps: light Elora tint through to full PET amber.
    const ramp = ['#E3E8F4', '#EBD9BE', '#E0C089', '#D5A357', DEBRIS.T.pet];
    return ramp[Math.min(4, Math.floor(share * 5))];
  }

  function draw() {
    svgNodes.innerHTML = nodes.map((n) => {
      const r = radius(n.count);
      const fill = petOnly ? petDensityColour(n) : (n.key === selected ? DEBRIS.T.pet : DEBRIS.T.blue);
      const ring = n.novel
        ? `<circle class="ring" cx="${n.x}" cy="${n.y}" r="${r + 7}" style="--r0:${r + 7}px"></circle>` : '';
      const labelRight = n.x > 180;
      return `${ring}
        <circle class="node" cx="${n.x}" cy="${n.y}" r="${r}" fill="${fill}"
          data-key="${n.key}" tabindex="0" role="button"
          aria-pressed="${n.key === selected}"
          aria-label="${DEBRIS.esc(n.label)}: ${n.count} papers, ${n.pet_count} naming PET"></circle>
        <text class="nodelabel" x="${labelRight ? n.x + r + 9 : n.x - r - 9}" y="${n.y - 1}"
          text-anchor="${labelRight ? 'start' : 'end'}">${DEBRIS.esc(n.label)}</text>
        <text class="count" x="${labelRight ? n.x + r + 9 : n.x - r - 9}" y="${n.y + 13}"
          text-anchor="${labelRight ? 'start' : 'end'}">${DEBRIS.fmt(n.count)}${n.pet_count ? ' · ' + n.pet_count + ' PET' : ''}</text>`;
    }).join('');
    svgNodes.querySelectorAll('.node').forEach((el) => {
      const pick = () => select(el.dataset.key);
      el.addEventListener('click', pick);
      el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); }
      });
    });
  }

  function select(key) {
    selected = key;
    const node = nodes.find((n) => n.key === key);
    draw();
    if (!node) return;
    document.getElementById('panel-title').textContent = node.label;
    const share = node.count ? Math.round((node.pet_count / node.count) * 100) : 0;
    document.getElementById('panel-sub').innerHTML =
      `<span class="mono">${DEBRIS.fmt(node.count)}</span> verified papers · ` +
      `<span class="mono" style="color:var(--pet)">${share}%</span> name PET`;
    const polymers = (node.polymers || []).slice(0, 8).map((p) =>
      `<span class="tag ${DEBRIS.polymerTagClass(p.key)}">${DEBRIS.esc(p.key)} ${p.n}</span>`).join(' ');
    const pathways = (node.pathways || []).map((p) =>
      `<a class="tag" href="/papers?pathway=${encodeURIComponent(p.key)}&organs=${encodeURIComponent((node.organs || []).join(','))}">${DEBRIS.esc(p.label)} ${p.n}</a>`).join(' ');
    const papers = (node.papers || []).map((p) => `
      <article class="paper" style="padding:11px 12px">
        <div class="meta"><span class="mono">${DEBRIS.esc(p.journal || '')} ${p.year || ''}</span>
          ${p.max_rung ? `<span class="tag rung">Rung ${p.max_rung}</span>` : ''}</div>
        <h3 style="font-size:13px">${DEBRIS.esc(p.title || '')}</h3>
        ${p.summary ? `<p class="summary" style="font-size:12px">${DEBRIS.esc(p.summary)}</p>` : ''}
        <div class="meta"><button class="chip" type="button" data-pmid="${p.pmid}">Detail</button></div>
      </article>`).join('');
    document.getElementById('panel-body').innerHTML = `
      <h3 style="font-size:9.5px;letter-spacing:0.3em;text-transform:uppercase;color:var(--el-muted);margin:14px 0 7px">Polymers</h3>
      <div class="tags" style="display:flex;flex-wrap:wrap;gap:6px">${polymers || '<span class="empty">none tagged</span>'}</div>
      <h3 style="font-size:9.5px;letter-spacing:0.3em;text-transform:uppercase;color:var(--el-muted);margin:16px 0 7px">Top pathways</h3>
      <div class="tags" style="display:flex;flex-wrap:wrap;gap:6px">${pathways || '<span class="empty">none tagged</span>'}</div>
      <h3 style="font-size:9.5px;letter-spacing:0.3em;text-transform:uppercase;color:var(--el-muted);margin:16px 0 7px">Strongest papers</h3>
      <div style="display:grid;gap:10px">${papers || '<span class="empty">none yet</span>'}</div>
      <p style="margin-top:14px"><a class="btn ghost" href="/papers?organs=${encodeURIComponent((node.organs || []).join(','))}">See all ${DEBRIS.fmt(node.count)} papers</a></p>`;
    document.querySelectorAll('#panel-body [data-pmid]').forEach((btn) =>
      btn.addEventListener('click', () => DEBRIS.openPaper(btn.dataset.pmid)));
  }

  document.getElementById('pet-only').addEventListener('change', (e) => {
    petOnly = e.target.checked; draw();
  });
  draw();
})();
