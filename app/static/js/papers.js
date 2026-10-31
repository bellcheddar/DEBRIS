/* 04 Papers: the Tabulator table over /api/papers, the filter row and the CSV export.
   Table pattern lifted from CODSWALLOP (see REUSE.md). */
(() => {
  const params = new URLSearchParams(window.location.search);
  const controls = {
    q: document.getElementById('search'),
    polymer: document.getElementById('polymer'),
    organ: document.getElementById('organ'),
    rung: document.getElementById('rung'),
  };

  // A click-through from the Atlas, Body or Pathways tab arrives as a query string.
  ['polymer', 'organ', 'rung', 'q'].forEach((k) => {
    if (params.get(k) && controls[k]) controls[k].value = params.get(k);
  });
  ['novel', 'new'].forEach((k) => {
    if (params.get(k) === '1' && controls[k]) controls[k].checked = true;
  });

  // Filters another tab can send that have no control of their own here.
  const LINKED = ['pet', 'novel', 'new', 'disease', 'pathway', 'polymers', 'not_polymers', 'organs',
                  'rungs', 'tissue', 'model_type', 'entered_from', 'entered_to',
                  'polymer_notin', 'pathway_notin', 'disease_notin'];
  DEBRIS.papersButton(document.getElementById('card-newweek'), 'Show in the table')('new=1');

  const filters = () => {
    const f = {};
    Object.entries(controls).forEach(([key, el]) => {
      if (!el) return;
      const value = el.type === 'checkbox' ? (el.checked ? '1' : '') : el.value.trim();
      if (value) f[key] = value;
    });
    LINKED.forEach((k) => { if (params.get(k)) f[k] = params.get(k); });
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
    // The server's count of every paper the current filters match, shown beside the
    // download buttons so the export size is never a surprise.
    ajaxResponse: (url, params, response) => {
      const el = document.getElementById('tablecount');
      if (el) el.textContent = `${DEBRIS.fmt(response.last_row || 0)} papers`;
      return response;
    },
    pagination: true,
    paginationMode: 'remote',
    paginationSize: 50,
    sortMode: 'remote',
    // Columns share the width rather than fixing it, so the table never scrolls sideways;
    // on a narrow screen the lowest-priority columns fold into a row you can open.
    layout: 'fitColumns',
    responsiveLayout: 'collapse',
    placeholder: 'No papers match these filters.',
    height: '640px',
    columns: [
      { formatter: 'responsiveCollapse', width: 30, minWidth: 30, hozAlign: 'center',
        resizable: false, headerSort: false, responsive: 0 },
      { title: 'Title', field: 'title', minWidth: 150, widthGrow: 3, responsive: 0, formatter: (cell) => {
          const row = cell.getRow().getData();
          const title = DEBRIS.esc(cell.getValue() || '');
          return row.retracted ? `<span class="retracted">${title}</span>` : title;
        } },
      { title: 'Year', field: 'year', minWidth: 56, widthGrow: 0.5, cssClass: 'mono', hozAlign: 'right', responsive: 1 },
      { title: 'Polymers', field: 'polymers', minWidth: 110, widthGrow: 1.2, responsive: 2,
        formatter: (cell) => tagList(cell, 'poly') },
      { title: 'Evidence', field: 'rungs', minWidth: 130, widthGrow: 1.4, responsive: 3,
        formatter: (cell) => (cell.getValue() || [])
          .map((r) => `<span class="tag rung">${DEBRIS.esc(DEBRIS.evidence(r))}</span>`).join(' ') },
      { title: 'Model', field: 'model_type', minWidth: 100, widthGrow: 1, responsive: 4 },
      { title: 'Organs', field: 'organ_systems', minWidth: 110, widthGrow: 1.2, responsive: 5,
        formatter: (cell) => tagList(cell) },
      { title: 'Conf', field: 'confidence', minWidth: 56, widthGrow: 0.5, cssClass: 'mono', hozAlign: 'right', responsive: 6,
        formatter: (cell) => cell.getValue() === null || cell.getValue() === undefined
          ? '' : Number(cell.getValue()).toFixed(2) },
      { title: 'Journal', field: 'journal', minWidth: 100, widthGrow: 1, responsive: 7 },
      { title: 'PMID', field: 'pmid', minWidth: 80, widthGrow: 0.6, cssClass: 'mono', headerSort: true, responsive: 8 },
    ],
  });

  table.on('rowClick', (_e, row) => DEBRIS.openPaper(row.getData().pmid));
  // Re-measure once each page arrives, so narrow screens fold the low-priority columns.
  table.on('dataProcessed', () => setTimeout(() => table.redraw(true), 0));

  /* Tabulator 6.3 nests role="rowgroup" inside role="rowgroup", which leaves the
     header without an owned row and the inner group without a grid parent. Marking
     the wrapper presentational lets the real header row be owned by the grid. */
  const fixHeaderRoles = () => document.querySelectorAll('.tabulator-header-contents')
    .forEach((el) => el.setAttribute('role', 'presentation'));
  table.on('tableBuilt', fixHeaderRoles);
  table.on('renderComplete', fixHeaderRoles);

  const download = () => {
    const qs = new URLSearchParams(filters()).toString();
    document.getElementById('download').href = '/download/debris_latest.csv' + (qs ? '?' + qs : '');
  };
  const refresh = () => { table.setData('/api/papers'); download(); };
  Object.values(controls).forEach((el) => {
    if (!el) return;
    el.addEventListener(el.tagName === 'INPUT' && el.type === 'search' ? 'input' : 'change',
      debounce(refresh, 220));
  });
  document.getElementById('export').addEventListener('click',
    () => table.download('csv', 'debris_page.csv'));
  document.querySelectorAll('.paper [data-pmid]').forEach((btn) =>
    btn.addEventListener('click', () => DEBRIS.openPaper(btn.dataset.pmid)));
  // The table loads its own first page once built; asking earlier is what threw.
  download();

  function debounce(fn, ms) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  }
})();
