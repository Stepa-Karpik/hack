// App shell: router, session, top bar, background uploads with completion notifications.
import { $, $$, h, icon, refreshIcons, api, ok, fail, info, showError } from './ui.js';

export const state = { user: null, watching: new Map(), cleanup: null };

const routes = [
  [/^\/$/, () => import('./pages/home.js'), true],
  [/^\/login$/, () => import('./pages/auth.js').then((m) => ({ render: m.login })), false],
  [/^\/register$/, () => import('./pages/auth.js').then((m) => ({ render: m.register })), false],
  [/^\/check\/([0-9a-z-]+)$/, () => import('./pages/check.js'), true],
  [/^\/history$/, () => import('./pages/history.js'), true],
  [/^\/profile(?:\/(security|api))?$/, () => import('./pages/profile.js'), true],
  [/^\/docs(?:\/([a-z-]+))?$/, () => import('./pages/docs.js'), false],
];

export function navigate(path, replace = false) {
  if (replace) history.replaceState({}, '', path); else history.pushState({}, '', path);
  render();
}

async function render() {
  const path = location.pathname.replace(/\/+$/, '') || '/';
  state.cleanup?.(); state.cleanup = null;
  const app = $('#app');
  for (const [pattern, load, needsAuth] of routes) {
    const m = pattern.exec(path);
    if (!m) continue;
    if (needsAuth && !state.user) return navigate('/login?next=' + encodeURIComponent(location.pathname), true);
    if ((path === '/login' || path === '/register') && state.user) return navigate('/', true);
    let mod;
    try { mod = await load(); } catch (e) {
      console.error(e);
      app.replaceChildren(h('div', { class: 'page' }, h('div', { class: 'empty' }, icon('triangle-alert'), h('h1', {}, 'Не удалось открыть страницу'),
        h('p', { class: 'muted' }, 'Обновите страницу. Если ошибка повторится — перезапустите приложение.'))));
      refreshIcons();
      return;
    }
    app.replaceChildren();
    $$('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.nav === '/' ? path === '/' : path.startsWith(a.dataset.nav)));
    state.cleanup = (await mod.render(app, ...m.slice(1))) || null;
    refreshIcons();
    window.scrollTo(0, 0);
    return;
  }
  app.replaceChildren(h('div', { class: 'page' }, h('div', { class: 'empty' }, icon('map-pinned'), h('h1', {}, 'Страница не найдена'),
    h('p', { class: 'muted' }, 'Проверьте адрес или вернитесь '), h('a', { href: '/', 'data-link': '', class: 'btn', style: { marginTop: '12px' } }, 'На главную'))));
  refreshIcons();
}

export function renderTopbar() {
  const right = $('#topbar-right');
  right.replaceChildren();
  $('#nav').hidden = !state.user;
  const theme = h('button', { class: 'btn ghost icon', title: 'Тема', onclick: () => {
    const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    document.documentElement.dataset.theme = next; try { localStorage.setItem('dk-theme', next); } catch {}
  } }, icon('sun-moon'));
  if (!state.user) {
    right.append(theme, h('a', { class: 'btn ghost', href: '/login', 'data-link': '' }, 'Войти'),
      h('a', { class: 'btn primary', href: '/register', 'data-link': '' }, 'Регистрация'));
  } else {
    const menu = h('div', { class: 'menu' });
    const initials = (state.user.name || state.user.email).trim()[0]?.toUpperCase() || '?';
    menu.append(h('button', { class: 'avatar', title: state.user.email, onclick: (e) => { e.stopPropagation(); menu.classList.toggle('open'); } }, initials),
      h('div', { class: 'menu-panel' },
        h('div', { class: 'subtle', style: { padding: '6px 10px', fontSize: '12.5px' } }, state.user.email),
        h('a', { href: '/profile', 'data-link': '' }, icon('user-round'), 'Профиль'),
        h('a', { href: '/profile/api', 'data-link': '' }, icon('key-round'), 'API-ключи'),
        h('a', { href: '/history', 'data-link': '' }, icon('history'), 'История'),
        h('button', { onclick: logout }, icon('log-out'), 'Выйти')));
    right.append(h('button', { class: 'btn primary sm', onclick: () => $('#global-file').click() }, icon('upload'), 'Загрузить'), theme, menu);
  }
  refreshIcons();
}

export async function logout() {
  try { await api('/api/auth/logout', { method: 'POST' }); } catch {}
  state.user = null; renderTopbar(); navigate('/login'); info('Вы вышли из аккаунта');
}

export async function uploadFiles(files, type = 'auto', { open = false } = {}) {
  const list = [...files];
  if (!list.length) return [];
  const form = new FormData();
  form.append('document_type', type);
  for (const f of list) form.append('files', f, f.name);
  try {
    const res = await api('/api/documents', { method: 'POST', form });
    for (const r of res.rejected || []) fail(`«${r.filename}» не загружен`, r.message);
    for (const d of res.documents) watch(d.slug, d.filename);
    if (res.documents.length === 1 && open) navigate('/check/' + res.documents[0].slug);
    else if (res.documents.length) info(res.documents.length > 1 ? `Загружено документов: ${res.documents.length}` : 'Документ загружен',
      'Обрабатываем в фоне — сообщим, когда будет готово.');
    window.dispatchEvent(new CustomEvent('documents-changed'));
    return res.documents;
  } catch (e) { showError(e); return []; }
}

export function watch(slug, filename) { state.watching.set(slug, filename); }

async function poll() {
  if (state.user && state.watching.size) {
    try {
      const { documents } = await api('/api/documents');
      for (const d of documents) {
        if (!state.watching.has(d.slug) || !['done', 'failed'].includes(d.status)) continue;
        state.watching.delete(d.slug);
        window.dispatchEvent(new CustomEvent('document-updated', { detail: d }));
        const here = location.pathname === '/check/' + d.slug;
        if (d.status === 'failed') fail(`«${d.filename}» не распознан`, d.error?.includes('PDF') ? 'Многостраничный PDF пока не поддерживается.' : 'Попробуйте другой файл.');
        else if (!here) ok(`«${d.filename}» готов`, d.valid ? 'Все обязательные сведения найдены.' : `Найдено ${d.found} из ${d.total}.`,
          { href: '/check/' + d.slug, label: 'Открыть' });
        if (document.hidden && Notification?.permission === 'granted') new Notification('Документ распознан', { body: d.filename });
      }
      window.dispatchEvent(new CustomEvent('documents-polled', { detail: documents }));
    } catch {}
  }
  setTimeout(poll, 1500);
}

document.addEventListener('click', (e) => {
  const a = e.target.closest('a[data-link]');
  if (a && !e.metaKey && !e.ctrlKey && a.origin === location.origin) { e.preventDefault(); navigate(a.pathname + a.search); }
  $$('.menu.open').forEach((m) => { if (!m.contains(e.target)) m.classList.remove('open'); });
});
window.addEventListener('popstate', render);
$('#global-file').addEventListener('change', (e) => { uploadFiles(e.target.files, 'auto', { open: e.target.files.length === 1 }); e.target.value = ''; });
window.addEventListener('dragover', (e) => { if (state.user) e.preventDefault(); });
window.addEventListener('drop', (e) => {
  if (!state.user || e.target.closest('.drop')) return;
  e.preventDefault(); uploadFiles(e.dataTransfer.files, 'auto', { open: e.dataTransfer.files.length === 1 });
});

(async () => {
  try { state.user = (await api('/api/me')).user; } catch { state.user = null; }
  renderTopbar();
  if (state.user) {
    try { const { documents } = await api('/api/documents'); for (const d of documents) if (['queued', 'running'].includes(d.status)) watch(d.slug, d.filename); } catch {}
  }
  await render();
  poll();
})();
