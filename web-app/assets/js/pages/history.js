import { h, icon, refreshIcons, api, TYPES, ago, statusChip, showError } from '../ui.js';
import { isStaff } from '../main.js';

export function documentRow(d) {
  const done = d.status === 'done';
  const thumb = h('div', { class: 'thumb', style: done ? { backgroundImage: `url(/api/documents/${d.slug}/preview?v=${d.version || 1})` } : {} },
    done ? null : icon(d.status === 'failed' ? 'file-x' : 'file-clock'));
  const pct = done && d.total ? Math.round((d.found / d.total) * 100) : 0;
  return h('a', { class: 'item', href: d.url, 'data-link': '' }, thumb,
    h('div', { style: { minWidth: 0 } }, h('div', { class: 'item-title' }, d.owner ? (d.owner.name || d.owner.email) : d.filename),
      h('div', { class: 'item-meta' }, d.owner ? h('span', {}, d.filename) : null, d.owner?.group ? h('span', {}, d.owner.group) : null,
        h('span', {}, TYPES[d.document_type] || '—'), h('span', {}, ago(d.submitted_at || d.created)),
        d.attempts > 1 ? h('span', {}, `попытка ${d.attempts}`) : null, d.version > 1 ? h('span', {}, `версия ${d.version}`) : null)),
    done ? h('div', { class: 'progress' + (d.found === d.total ? ' full' : ''), title: `${d.found} из ${d.total}` }, h('span', { style: { width: pct + '%' } })) : h('span'),
    statusChip(d));
}

const STUDENT_FILTERS = [['all', 'Все'], ['draft', 'Черновики'], ['sent', 'В деканате'], ['returned', 'Возвращены'], ['approved', 'Одобрены'], ['closed', 'Закрыты']];
const STAFF_FILTERS = [['new', 'Новые'], ['review', 'На рассмотрении'], ['returned', 'Возвращены'], ['approved', 'Одобрены'], ['closed', 'Закрыты'], ['all', 'Все']];
const matches = (d, f) => f === 'all' || (f === 'draft' && (d.state || 'draft') === 'draft')
  || (f === 'sent' && ['submitted', 'review'].includes(d.state)) || (f === 'new' && d.state === 'submitted')
  || (f === 'review' && d.state === 'review') || d.state === f;

export async function render(app) {
  const staff = isStaff();
  let filter = staff ? 'new' : 'all', query = '', kind = '', group = '', docs = [];
  const tabs = h('div', { class: 'tabs' });
  const search = h('input', { class: 'input', placeholder: staff ? 'Студент, почта или файл' : 'Поиск по названию', style: { maxWidth: '240px', height: '34px' } });
  const list = h('div', { class: 'card' });
  const counter = h('span', { class: 'muted' });
  const stats = h('div', { class: 'stat-row' });
  const typeSelect = h('select', { class: 'select' });
  const groupSelect = h('select', { class: 'select' });
  const exportBtn = h('a', { class: 'btn', href: '/api/staff/export.xlsx', title: 'Выгрузка с учётом фильтров' }, icon('sheet'), 'Excel');
  app.append(h('div', { class: 'page' },
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, staff ? 'Входящие деканата' : 'Мои заявки'), counter),
      staff ? exportBtn : h('button', { class: 'btn primary', onclick: () => document.getElementById('global-file').click() }, icon('upload'), 'Загрузить документы')),
    staff ? stats : null,
    h('div', { class: 'row', style: { marginBottom: '14px', flexWrap: 'wrap', gap: '10px' } }, tabs, h('div', { class: 'grow' }),
      staff ? h('div', { class: 'filters' }, typeSelect, groupSelect) : null, search), list));

  function draw() {
    const filters = staff ? STAFF_FILTERS : STUDENT_FILTERS;
    tabs.replaceChildren(...filters.map(([k, label]) => h('button', { class: k === filter ? 'active' : '', onclick: () => { filter = k; draw(); } },
      label, ' ', h('span', { class: 'subtle' }, String(docs.filter((d) => matches(d, k)).length)))));
    if (staff) {
      const count = (f) => docs.filter((d) => matches(d, f)).length;
      stats.replaceChildren(
        h('div', { class: 'stat' }, h('b', {}, String(count('new'))), h('span', {}, 'новых заявок')),
        h('div', { class: 'stat' }, h('b', {}, String(count('review'))), h('span', {}, 'на рассмотрении')),
        h('div', { class: 'stat' }, h('b', {}, String(docs.filter((d) => ['submitted', 'review'].includes(d.state) && d.valid).length)), h('span', {}, 'полных, ждут решения')),
        h('div', { class: 'stat' }, h('b', {}, String(count('approved'))), h('span', {}, 'одобрено')),
        h('div', { class: 'stat' }, h('b', {}, String(count('returned'))), h('span', {}, 'возвращено')));
      const groups = [...new Set(docs.map((d) => d.owner?.group).filter(Boolean))].sort();
      groupSelect.replaceChildren(h('option', { value: '' }, 'Все группы'), ...groups.map((g) => h('option', { value: g, selected: g === group }, g)));
      typeSelect.replaceChildren(h('option', { value: '' }, 'Все типы'),
        ...Object.entries(TYPES).filter(([k]) => k !== 'auto').map(([k, l]) => h('option', { value: k, selected: k === kind }, l)));
      const params = new URLSearchParams({ ...(kind && { type: kind }), ...(group && { group }) });
      exportBtn.href = '/api/staff/export.xlsx' + (params.toString() ? '?' + params : '');
    }
    const shown = docs.filter((d) => matches(d, filter) && (!kind || d.document_type === kind) && (!group || d.owner?.group === group)
      && (d.filename + ' ' + (d.owner?.name || '') + ' ' + (d.owner?.email || '')).toLowerCase().includes(query));
    const n = docs.length;
    counter.textContent = staff ? `${n} ${n % 10 === 1 && n % 100 !== 11 ? 'заявка' : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? 'заявки' : 'заявок'} от студентов`
      : `${n} ${n % 10 === 1 && n % 100 !== 11 ? 'документ' : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? 'документа' : 'документов'}`;
    list.replaceChildren(shown.length ? h('div', { class: 'list' }, ...shown.map(documentRow))
      : h('div', { class: 'empty' }, icon(staff ? 'inbox' : 'search-x'), h('div', {}, docs.length ? 'Ничего не найдено'
        : staff ? 'Пока никто не отправил заявку' : 'Пока нет документов')));
    refreshIcons();
  }
  typeSelect.addEventListener('change', () => { kind = typeSelect.value; draw(); });
  groupSelect.addEventListener('change', () => { group = groupSelect.value; draw(); });
  search.addEventListener('input', () => { query = search.value.trim().toLowerCase(); draw(); });
  async function load() {
    try { docs = (await api('/api/documents')).documents; draw(); } catch (e) { showError(e); }
  }
  await load();
  const onPoll = (e) => { if (!staff) { docs = e.detail; draw(); } };
  const reload = () => load();
  const timer = staff ? setInterval(load, 15000) : null;  // the inbox refreshes itself
  window.addEventListener('documents-polled', onPoll);
  window.addEventListener('documents-changed', reload);
  return () => { clearInterval(timer); window.removeEventListener('documents-polled', onPoll); window.removeEventListener('documents-changed', reload); };
}
