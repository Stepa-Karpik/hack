import { h, icon, refreshIcons, api, TYPES, ago, statusChip, showError, ok } from '../ui.js';

export function documentRow(d) {
  const done = d.status === 'done';
  const thumb = h('div', { class: 'thumb', style: done ? { backgroundImage: `url(${d.url.replace('/check/', '/api/documents/')}/preview)` } : {} },
    done ? null : icon(d.status === 'failed' ? 'file-x' : 'file-clock'));
  const pct = done && d.total ? Math.round((d.found / d.total) * 100) : 0;
  return h('a', { class: 'item', href: d.url, 'data-link': '' }, thumb,
    h('div', { style: { minWidth: 0 } }, h('div', { class: 'item-title' }, d.filename),
      h('div', { class: 'item-meta' }, h('span', {}, TYPES[d.document_type] || '—'), h('span', {}, ago(d.created)),
        done && d.verified_count ? h('span', {}, `проверено вручную: ${d.verified_count}`) : null)),
    done ? h('div', { class: 'progress' + (d.found === d.total ? ' full' : ''), title: `${d.found} из ${d.total}` }, h('span', { style: { width: pct + '%' } })) : h('span'),
    statusChip(d));
}

const FILTERS = [['all', 'Все'], ['work', 'В работе'], ['attention', 'Требуют внимания'], ['valid', 'Соответствуют'], ['approved', 'Одобрены']];
const matches = (d, f) => f === 'all' || (f === 'work' && ['queued', 'running'].includes(d.status))
  || (f === 'attention' && (d.status === 'failed' || (d.status === 'done' && !d.valid && !d.approved)))
  || (f === 'valid' && d.status === 'done' && d.valid) || (f === 'approved' && d.approved);

export async function render(app) {
  let filter = 'all', query = '', docs = [];
  const tabs = h('div', { class: 'tabs' });
  const search = h('input', { class: 'input', placeholder: 'Поиск по названию', style: { maxWidth: '260px', height: '34px' } });
  const list = h('div', { class: 'card' });
  const counter = h('span', { class: 'muted' });
  app.append(h('div', { class: 'page' },
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'История'), counter),
      h('button', { class: 'btn primary', onclick: () => document.getElementById('global-file').click() }, icon('upload'), 'Загрузить документы')),
    h('div', { class: 'row', style: { marginBottom: '14px', flexWrap: 'wrap', gap: '10px' } }, tabs, h('div', { class: 'grow' }), search), list));

  function draw() {
    tabs.replaceChildren(...FILTERS.map(([k, label]) => h('button', { class: k === filter ? 'active' : '', onclick: () => { filter = k; draw(); } },
      label, ' ', h('span', { class: 'subtle' }, String(docs.filter((d) => matches(d, k)).length)))));
    const shown = docs.filter((d) => matches(d, filter) && d.filename.toLowerCase().includes(query));
    counter.textContent = `${docs.length} ${docs.length % 10 === 1 && docs.length % 100 !== 11 ? 'документ' : [2, 3, 4].includes(docs.length % 10) && ![12, 13, 14].includes(docs.length % 100) ? 'документа' : 'документов'} · ${docs.filter((d) => d.approved).length} одобрено`;
    list.replaceChildren(shown.length ? h('div', { class: 'list' }, ...shown.map(documentRow))
      : h('div', { class: 'empty' }, icon('search-x'), h('div', {}, docs.length ? 'Ничего не найдено' : 'Пока нет документов')));
    refreshIcons();
  }
  search.addEventListener('input', () => { query = search.value.trim().toLowerCase(); draw(); });
  async function load() {
    try { docs = (await api('/api/documents')).documents; draw(); } catch (e) { showError(e); }
  }
  await load();
  const onPoll = (e) => { docs = e.detail; draw(); };
  const reload = () => load();
  window.addEventListener('documents-polled', onPoll);
  window.addEventListener('documents-changed', reload);
  return () => { window.removeEventListener('documents-polled', onPoll); window.removeEventListener('documents-changed', reload); };
}
