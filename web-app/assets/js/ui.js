// Shared UI helpers: elements, icons, toasts (Notyf), API client, formatting.
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
}
export const icon = (name, cls = '') => h('i', { 'data-lucide': name, class: cls });
export const refreshIcons = () => window.lucide?.createIcons({ attrs: { 'stroke-width': 1.9 } });

const notyf = new window.Notyf({ duration: 4500, position: { x: 'right', y: 'bottom' }, dismissible: false, ripple: false,
  types: [{ type: 'success', background: 'transparent' }, { type: 'error', background: 'transparent', duration: 6500 },
    { type: 'info', background: 'transparent', icon: false }, { type: 'warn', background: 'transparent', icon: false }] });
const toastIcons = { success: 'circle-check', error: 'circle-x', info: 'info', warn: 'triangle-alert' };
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export function toast(kind, title, text = '', link = null) {
  const extra = link ? ` <a href="${esc(link.href)}" data-link>${esc(link.label)}</a>` : '';
  const message = `<div class="toast ${kind}"><i data-lucide="${toastIcons[kind]}" class="ti"></i><div><b>${esc(title)}</b>${text || extra ? `<span>${esc(text)}${extra}</span>` : ''}</div></div>`;
  notyf.open({ type: kind, message });
  refreshIcons();
}
export const ok = (t, s, l) => toast('success', t, s, l);
export const fail = (t, s) => toast('error', t, s);
export const info = (t, s, l) => toast('info', t, s, l);

const httpMessages = {
  0: ['Нет связи с сервером', 'Проверьте, что приложение запущено, и повторите.'],
  401: ['Нужно войти', 'Сессия истекла — войдите снова.'],
  403: ['Действие запрещено', ''],
  404: ['Не найдено', 'Документ удалён или ссылка неверна.'],
  409: ['Ещё не готово', 'Дождитесь окончания распознавания.'],
  413: ['Файл слишком большой', 'Максимум — 10 МБ.'],
  429: ['Слишком много запросов', 'Подождите немного.'],
  500: ['Ошибка на сервере', 'Попробуйте ещё раз через минуту.'],
};
export class ApiError extends Error {
  constructor(status, title, detail, code) { super(title); this.status = status; this.title = title; this.detail = detail; this.code = code; }
}
export async function api(path, { method = 'GET', body, form, raw } = {}) {
  let response;
  try {
    response = await fetch(path, { method, credentials: 'same-origin', cache: 'no-store',
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined) });
  } catch { const [t, d] = httpMessages[0]; throw new ApiError(0, t, d); }
  if (raw) return response;
  let data = null;
  try { data = await response.json(); } catch { /* empty */ }
  if (!response.ok) {
    const [t, d] = httpMessages[response.status] || httpMessages[500];
    throw new ApiError(response.status, data?.message || t, data?.message ? '' : d, data?.error);
  }
  return data;
}
export const showError = (e) => fail(e.title || 'Что-то пошло не так', e.detail || '');

export const TYPES = { auto: 'Определить автоматически', study_certificate: 'Справка об обучении',
  academic_leave_application: 'Заявление на академический отпуск', internship_certificate: 'Справка о практике' };
export const LABELS = { student_name: 'ФИО студента', university: 'Вуз', program: 'Направление подготовки', study_form: 'Форма обучения',
  study_start: 'Начало обучения', study_end: 'Окончание обучения', document_number: 'Номер справки', issue_date: 'Дата выдачи',
  signature_present: 'Подпись', seal_present: 'Печать', group: 'Учебная группа', course: 'Курс', leave_reason: 'Причина отпуска',
  leave_start: 'Начало отпуска', leave_end: 'Окончание отпуска', application_date: 'Дата заявления', organization: 'Организация',
  internship_start: 'Начало практики', internship_end: 'Окончание практики', supervisor_name: 'Руководитель практики', grade: 'Оценка' };
const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
export function displayValue(v) {
  if (v === true) return 'Обнаружена';
  if (v === false) return 'Не обнаружена';
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(v));
  return m ? `${+m[3]} ${MONTHS[+m[2] - 1]} ${m[1]}` : String(v);
}
export function ago(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return 'только что';
  if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
  if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
  return new Date(ts * 1000).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: s > 300 * 86400 ? 'numeric' : undefined });
}
export function statusChip(d) {
  if (d.status === 'queued') return h('span', { class: 'chip info' }, icon('clock'), d.queue_position > 1 ? `В очереди · ${d.queue_position}` : 'В очереди');
  if (d.status === 'running') return h('span', { class: 'chip info' }, icon('loader-circle', 'spin'), 'Распознаётся');
  if (d.status === 'failed') return h('span', { class: 'chip bad' }, icon('circle-x'), 'Ошибка');
  if (d.approved) return h('span', { class: 'chip ok' }, icon('badge-check'), d.approved_by === 'auto' ? 'Одобрен автоматически' : 'Одобрен');
  if (d.valid) return h('span', { class: 'chip ok' }, icon('check'), 'Соответствует');
  return h('span', { class: 'chip warn' }, `${d.found}/${d.total}`);
}
export function copy(text, label = 'Скопировано') {
  navigator.clipboard?.writeText(text).then(() => ok(label), () => fail('Не удалось скопировать'));
}
