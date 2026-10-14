import { h, icon, refreshIcons, api, showError, ok, info, copy, ago } from '../ui.js';
import { state, logout, renderTopbar } from '../main.js';

export async function render(app, tab = '') {
  const nav = h('nav', { class: 'side-nav' },
    h('a', { href: '/profile', 'data-link': '', class: tab ? '' : 'active' }, icon('user-round'), 'Профиль'),
    h('a', { href: '/profile/security', 'data-link': '', class: tab === 'security' ? 'active' : '' }, icon('lock-keyhole'), 'Безопасность'),
    h('a', { href: '/profile/api', 'data-link': '', class: tab === 'api' ? 'active' : '' }, icon('key-round'), 'API-ключи'),
    h('button', { class: 'btn ghost', style: { justifyContent: 'flex-start', marginTop: '8px' }, onclick: logout }, icon('log-out'), 'Выйти'));
  const body = h('div', { class: 'card' });
  app.append(h('div', { class: 'page' }, h('div', { class: 'page-head' }, h('h1', {}, 'Настройки')), h('div', { class: 'settings' }, nav, body)));
  if (tab === 'security') security(body);
  else if (tab === 'api') await keys(body);
  else profile(body);
  refreshIcons();
}

function profile(body) {
  const u = state.user;
  const sw = h('button', { class: 'switch', role: 'switch', 'aria-checked': String(u.auto_approve), 'aria-label': 'Авто-подтверждение открытых документов' });
  sw.addEventListener('click', async () => {
    const next = sw.getAttribute('aria-checked') !== 'true';
    sw.setAttribute('aria-checked', String(next));
    try {
      state.user = (await api('/api/me', { method: 'PATCH', body: { auto_approve: next } })).user;
      next ? ok('Авто-подтверждение включено', 'Документы, где найдены все сведения, будут одобряться при открытии.') : info('Авто-подтверждение выключено');
    } catch (e) { sw.setAttribute('aria-checked', String(!next)); showError(e); }
  });
  body.append(
    h('div', { class: 'section' }, h('h2', {}, 'Аккаунт'),
      h('div', { class: 'row', style: { marginTop: '14px', gap: '14px' } }, h('div', { class: 'avatar', style: { width: '44px', height: '44px', fontSize: '17px' } },
        (u.name || u.email)[0].toUpperCase()), h('div', {}, h('div', { style: { fontWeight: 600 } }, u.name || 'Без имени'),
        h('div', { class: 'muted' }, u.email), h('div', { class: 'subtle', style: { fontSize: '12px' } }, 'С нами с ' + new Date(u.created * 1000).toLocaleDateString('ru-RU'))))),
    h('div', { class: 'section' }, h('div', { class: 'section-head' },
      h('div', {}, h('h2', {}, 'Авто-подтверждение открытых документов'),
        h('p', { class: 'muted', style: { marginTop: '4px', maxWidth: '520px' } },
          'Если при открытии документа все обязательные сведения найдены (например, 10/10), он сразу помечается как одобренный. Документы с пропусками всегда требуют ручного решения.')),
      sw)),
    h('div', { class: 'section' }, h('div', { class: 'section-head' },
      h('div', {}, h('h2', {}, 'Системные уведомления'), h('p', { class: 'muted', style: { marginTop: '4px' } }, 'Сообщать о готовых документах, даже когда вкладка свёрнута.')),
      h('button', { class: 'btn', onclick: async () => {
        if (!('Notification' in window)) return showError({ title: 'Браузер не поддерживает уведомления' });
        const p = await Notification.requestPermission();
        p === 'granted' ? ok('Уведомления включены') : info('Уведомления не разрешены', 'Их можно включить в настройках браузера.');
      } }, icon('bell'), 'Включить'))));
}

function security(body) {
  const form = h('form', { class: 'stack', style: { maxWidth: '380px', marginTop: '14px' } },
    h('div', { class: 'field-group' }, h('label', { class: 'label', for: 'cur' }, 'Текущий пароль'), h('input', { class: 'input', id: 'cur', name: 'current', type: 'password', autocomplete: 'current-password' })),
    h('div', { class: 'field-group' }, h('label', { class: 'label', for: 'new' }, 'Новый пароль'), h('input', { class: 'input', id: 'new', name: 'next', type: 'password', autocomplete: 'new-password', placeholder: 'Не короче 8 символов' })),
    h('div', { class: 'field-group' }, h('label', { class: 'label', for: 'rep' }, 'Повторите новый пароль'), h('input', { class: 'input', id: 'rep', name: 'repeat', type: 'password', autocomplete: 'new-password' })),
    h('div', {}, h('button', { class: 'btn primary', type: 'submit' }, 'Сменить пароль')));
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (form.next.value !== form.repeat.value) return showError({ title: 'Пароли не совпадают', detail: 'Введите новый пароль одинаково в обоих полях.' });
    try { await api('/api/auth/password', { method: 'POST', body: { current: form.current.value, new: form.next.value } }); form.reset(); ok('Пароль изменён', 'Другие сеансы завершены.'); }
    catch (err) { showError(err); }
  });
  body.append(h('div', { class: 'section' }, h('h2', {}, 'Смена пароля'), h('p', { class: 'muted', style: { marginTop: '4px' } }, 'После смены все остальные сеансы будут завершены.'), form),
    h('div', { class: 'section' }, h('div', { class: 'section-head' }, h('div', {}, h('h2', {}, 'Выход'), h('p', { class: 'muted', style: { marginTop: '4px' } }, 'Завершить текущий сеанс на этом устройстве.')),
      h('button', { class: 'btn danger', onclick: logout }, icon('log-out'), 'Выйти из аккаунта'))));
}

async function keys(body) {
  const list = h('div', { class: 'list' });
  const fresh = h('div');
  const name = h('input', { class: 'input', placeholder: 'Название, например «CRM деканата»', maxlength: 60, style: { maxWidth: '320px' } });
  const create = h('button', { class: 'btn primary', onclick: async () => {
    try {
      const k = await api('/api/keys', { method: 'POST', body: { name: name.value } });
      name.value = '';
      fresh.replaceChildren(h('div', { class: 'stack', style: { marginTop: '14px' } },
        h('div', { class: 'muted' }, 'Скопируйте ключ сейчас — после закрытия страницы он больше не будет показан.'),
        h('div', { class: 'row' }, h('div', { class: 'key-box grow' }, k.key), h('button', { class: 'btn', onclick: () => copy(k.key, 'Ключ скопирован') }, icon('copy'), 'Копировать'))));
      ok('Ключ создан', 'Он даёт доступ к документам вашего аккаунта.');
      await load(); refreshIcons();
    } catch (e) { showError(e); }
  } }, icon('plus'), 'Создать ключ');
  body.append(h('div', { class: 'section' }, h('div', { class: 'section-head' },
    h('div', {}, h('h2', {}, 'API-ключи'), h('p', { class: 'muted', style: { marginTop: '4px', maxWidth: '520px' } },
      'Сторонние сервисы могут загружать документы и получать результат проверки по ключу.')),
    h('a', { class: 'btn', href: '/docs/api', 'data-link': '' }, icon('book-open'), 'Просмотреть документацию')),
    h('div', { class: 'row', style: { marginTop: '16px' } }, name, create), fresh),
    h('div', { class: 'section', style: { padding: '0' } }, list));
  async function load() {
    try {
      const { keys } = await api('/api/keys');
      list.replaceChildren(...(keys.length ? keys.map((k) => h('div', { class: 'item', style: { gridTemplateColumns: '32px minmax(0,1fr) auto' } },
        icon('key-round'), h('div', {}, h('div', { class: 'item-title' }, k.name), h('div', { class: 'item-meta' }, h('code', {}, k.prefix + '…'),
          h('span', {}, 'создан ' + ago(k.created)), h('span', {}, k.last_used ? 'использован ' + ago(k.last_used) : 'ещё не использовался'))),
        h('button', { class: 'btn ghost sm danger', onclick: async () => {
          if (!confirm(`Отозвать ключ «${k.name}»? Интеграции с ним перестанут работать.`)) return;
          try { await api('/api/keys/' + k.id, { method: 'DELETE' }); ok('Ключ отозван'); load(); } catch (e) { showError(e); }
        } }, 'Отозвать'))) : [h('div', { class: 'empty' }, icon('key-round'), h('div', {}, 'Ключей пока нет'))]));
      refreshIcons();
    } catch (e) { showError(e); }
  }
  await load();
}
