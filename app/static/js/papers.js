/* 04 Papers: the Tabulator table over /api/papers, the filter row and the CSV export.
   Table pattern lifted from CODSWALLOP (see REUSE.md). */
(() => {
  const params = new URLSearchParams(window.location.search);
  const controls = {
    q: document.getElementById('search'),
    polymer: document.getElementById('polymer'),
    organ: document.getElementById('organ'),
    rung: document.getElementById('rung'),
    pet: document.getElementById('pet'),
    review: document.getElementById('review'),
    unverified: document.getElementById('unverified'),
  };

  // A click-through from the Atlas, Body or Pathways tab arrives as a query string.
  ['polymer', 'organ', 'rung', 'q'].forEach((k) => {
    if (params.get(k) && controls[k]) controls[k].value = params.get(k);
  });
  ['pet', 'review', 'unverified', 'novel', 'new'].forEach((k) => {
    if (params.get(k) === '1' && controls[k]) controls[k].checked = true;
  });

  const filters = () => {
    const f = {};
    Object.entries(controls).forEach(([key, el]) => {
      if (!el) return;
      const value = el.type === 'checkbox' ? (el.checked ? '1' : '') : el.value.trim();
      if (value) f[key] = value;
    });
    ['novel', 'new', 'disease', 'pathway'].forEach((k) => {
      if (params.get(k)) f[k] = params.get(k);
    });
    return f;
  };

  const tagList = (cell, cls) => (cell.getValue() || [])
    .map((v) => `<span class="tag ${cls === 'poly' ? DEBRIS.polymerTagClass(v) : (cls || '')}">${DEBRIS.esc(v)}</span>`)
    .join(' ');

  const table = new Tabulator('#papers-table', {
    ajaxURL: '/api/papers',
    ajaxParams: filters,
    ajaxURLGenerator: (url, cfg, p) => {
      const qs = new URLSearchParams(Object.assign({}, filters(), {
        page: p.page || 1, size: p.size || 50,
        sort: (p.sort && p.sort[0] && p.sort[0].field) || 'year',
        dir: (p.sort && p.sort[0] && p.sort[0].dir) || 'desc',
      }));
      return url + '?' + qs.toString();
    },
    pagination: true,
    paginationMode: 'remote',
    paginationSize: 50,
    sortMode: 'remote',
    layout: 'fitColumns',
    placeholder: 'No papers match these filters.',
    height: '640px',
    columns: [
      { title: 'PMID', field: 'pmid', width: 92, cssClass: 'mono', headerSort: true },
      { title: 'Year', field: 'year', width: 68, cssClass: 'mono', hozAlign: 'right' },
      { title: 'Title', field: 'title', minWidth: 260, formatter: (cell) => {
          const row = cell.getRow().getData();
          const title = DEBRIS.esc(cell.getValue() || '');
          return row.retracted ? `<span class="retracted">${title}</span>` : title;
        } },
      { title: 'Journal', field: 'journal', width: 150 },
      { title: 'Polymers', field: 'polymers', headerSort: false, width: 170,
        formatter: (cell) => tagList(cell, 'poly') },
      { title: 'Organs', field: 'organ_systems', headerSort: false, width: 160,
        formatter: (cell) => tagList(cell) },
      { title: 'Rungs', field: 'rungs', headerSort: false, width: 110,
        formatter: (cell) => tagList(cell, 'rung') },
      { title: 'Model', field: 'model_type', width: 120 },
      { title: 'Conf', field: 'confidence', width: 70, cssClass: 'mono', hozAlign: 'right',
        formatter: (cell) => cell.getValue() === null || cell.getValue() === undefined
          ? '' : Number(cell.getValue()).toFixed(2) },
    ],
  });

  table.on('rowClick', (_e, row) => DEBRIS.openPaper(row.getData().pmid));

  const refresh = () => {
    table.setData('/api/papers');
    const qs = new URLSearchParams(filters()).toString();
    document.getElementById('download').href = '/download/debris_latest.csv' + (qs ? '?' + qs : '');
  };
  Object.values(controls).forEach((el) => {
    if (!el) return;
    el.addEventListener(el.tagName === 'INPUT' && el.type === 'search' ? 'input' : 'change',
      debounce(refresh, 220));
  });
  document.getElementById('export').addEventListener('click',
    () => table.download('csv', 'debris_page.csv'));
  document.querySelectorAll('.paper [data-pmid]').forEach((btn) =>
    btn.addEventListener('click', () => DEBRIS.openPaper(btn.dataset.pmid)));
  refresh();

  function debounce(fn, ms) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  }
})();
