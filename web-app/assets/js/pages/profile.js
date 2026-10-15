import { h, icon, refreshIcons, api, showError, ok, info, copy, ago } from '../ui.js';
import { state, logout, renderTopbar, isStaff, ROLE_NAMES } from '../main.js';

export async function render(app, tab = '') {
  const admin = state.user.role === 'admin';
  const link = (t, iconName, label) => h('a', { href: '/profile' + (t ? '/' + t : ''), 'data-link': '', class: tab === t ? 'active' : '' }, icon(iconName), label);
  const nav = h('nav', { class: 'side-nav' },
    link('', 'user-round', 'Профиль'),
    link('marks', 'signature', isStaff() ? 'Подпись и печать' : 'Моя подпись'),
    link('security', 'lock-keyhole', 'Безопасность'),
    link('api', 'key-round', 'API-ключи'),
    admin ? link('users', 'users', 'Пользователи') : null,
    admin ? link('types', 'shapes', 'Типы документов') : null,
    h('button', { class: 'btn ghost', style: { justifyContent: 'flex-start', marginTop: '8px' }, onclick: logout }, icon('log-out'), 'Выйти'));
  const body = h('div', { class: 'card' });
  app.append(h('div', { class: 'page' }, h('div', { class: 'page-head' }, h('h1', {}, 'Настройки')), h('div', { class: 'settings' }, nav, body)));
  if (tab === 'security') security(body);
  else if (tab === 'api') await keys(body);
  else if (tab === 'users' && admin) await users(body);
  else if (tab === 'types' && admin) await (await import('./types.js')).render(body);
  else if (tab === 'marks') await marks(body);
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
  const nameInput = h('input', { class: 'input', value: u.name || '', placeholder: 'Иванов Иван Иванович' });
  const groupInput = h('input', { class: 'input', value: u.study_group || '', placeholder: 'ИВТ-21' });
  const saveProfile = h('button', { class: 'btn', onclick: async () => {
    try {
      state.user = (await api('/api/me', { method: 'PATCH', body: { name: nameInput.value, study_group: groupInput.value } })).user;
      renderTopbar(); ok('Профиль сохранён', isStaff() ? '' : 'ФИО сверяется с документами при проверке.');
    } catch (e) { showError(e); }
  } }, 'Сохранить');
  body.append(
    h('div', { class: 'section' }, h('h2', {}, 'Аккаунт'),
      h('div', { class: 'row', style: { marginTop: '14px', gap: '14px' } }, h('div', { class: 'avatar', style: { width: '44px', height: '44px', fontSize: '17px' } },
        (u.name || u.email)[0].toUpperCase()), h('div', {}, h('div', { style: { fontWeight: 600 } }, u.name || 'Без имени'),
        h('div', { class: 'muted' }, u.email), h('div', { class: 'subtle', style: { fontSize: '12px' } },
          (ROLE_NAMES[u.role] || '') + ' · с нами с ' + new Date(u.created * 1000).toLocaleDateString('ru-RU')))),
      h('div', { class: 'row', style: { marginTop: '16px', gap: '10px', flexWrap: 'wrap', alignItems: 'flex-end' } },
        h('div', { class: 'field-group', style: { flex: '2 1 240px' } }, h('label', { class: 'label' }, isStaff() ? 'Имя и фамилия' : 'ФИО — как в документах'), nameInput),
        isStaff() ? null : h('div', { class: 'field-group', style: { flex: '1 1 120px' } }, h('label', { class: 'label' }, 'Учебная группа'), groupInput),
        saveProfile)),
    !isStaff() ? null : h('div', { class: 'section' }, h('div', { class: 'section-head' },
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

async function users(body) {
  const list = h('div', { class: 'list' });
  const invites = h('div', { class: 'list' });
  const fresh = h('div');
  const note = h('input', { class: 'input', placeholder: 'Для кого, например «Деканат экономического факультета»', maxlength: 80, style: { maxWidth: '380px' } });
  async function load() {
    try {
      const r = await api('/api/admin/users');
      list.replaceChildren(...r.users.map((u) => {
        const select = h('select', { class: 'select', style: { width: 'auto', height: '32px' } },
          ...Object.entries(ROLE_NAMES).map(([k, label]) => h('option', { value: k, selected: k === u.role }, label)));
        select.addEventListener('change', async () => {
          try { await api('/api/admin/users/' + u.id, { method: 'PATCH', body: { role: select.value } }); ok('Роль изменена', `${u.email}: ${ROLE_NAMES[select.value]}`); }
          catch (e) { showError(e); select.value = u.role; }
        });
        return h('div', { class: 'item', style: { gridTemplateColumns: '32px minmax(0,1fr) auto' } }, icon(u.role === 'student' ? 'graduation-cap' : 'shield-check'),
          h('div', {}, h('div', { class: 'item-title' }, u.name || u.email), h('div', { class: 'item-meta' }, h('span', {}, u.email),
            h('span', {}, `документов: ${u.documents}`), h('span', {}, 'с ' + new Date(u.created * 1000).toLocaleDateString('ru-RU')))), select);
      }));
      invites.replaceChildren(...(r.invites.length ? r.invites.map((i) => {
        const status = i.used_email ? `использовано: ${i.used_email}` : i.revoked ? 'отозвано' : i.expires * 1000 < Date.now() ? 'истекло'
          : 'действует до ' + new Date(i.expires * 1000).toLocaleDateString('ru-RU');
        return h('div', { class: 'item', style: { gridTemplateColumns: '32px minmax(0,1fr) auto' } }, icon(i.used_email ? 'user-check' : 'link'),
          h('div', {}, h('div', { class: 'item-title' }, i.note || 'Приглашение сотрудника'), h('div', { class: 'item-meta' }, h('code', {}, i.prefix + '…'), h('span', {}, status))),
          !i.used_email && !i.revoked ? h('button', { class: 'btn ghost sm danger', onclick: async () => {
            try { await api('/api/admin/invites/' + i.prefix, { method: 'DELETE' }); info('Приглашение отозвано'); load(); } catch (e) { showError(e); }
          } }, 'Отозвать') : h('span'));
      }) : [h('div', { class: 'empty' }, icon('mail-plus'), h('div', {}, 'Приглашений пока нет'))]));
      refreshIcons();
    } catch (e) { showError(e); }
  }
  const create = h('button', { class: 'btn primary', onclick: async () => {
    try {
      const r = await api('/api/admin/invites', { method: 'POST', body: { note: note.value } });
      note.value = '';
      fresh.replaceChildren(h('div', { class: 'stack', style: { marginTop: '14px' } },
        h('div', { class: 'muted' }, 'Отправьте ссылку сотруднику. Она одноразовая и действует 7 дней: по ней сразу регистрируется аккаунт деканата.'),
        h('div', { class: 'row' }, h('div', { class: 'key-box grow' }, r.link), h('button', { class: 'btn', onclick: () => copy(r.link, 'Ссылка скопирована') }, icon('copy'), 'Копировать'))));
      ok('Приглашение создано'); load(); refreshIcons();
    } catch (e) { showError(e); }
  } }, icon('mail-plus'), 'Создать ссылку');
  body.append(h('div', { class: 'section' }, h('h2', {}, 'Пригласить сотрудника деканата'),
      h('p', { class: 'muted', style: { marginTop: '4px', maxWidth: '560px' } }, 'Студенты регистрируются сами. Сотрудники деканата — только по одноразовой ссылке от суперадмина.'),
      h('div', { class: 'row', style: { marginTop: '12px' } }, note, create), fresh),
    h('div', { class: 'section', style: { padding: '0' } }, invites),
    h('div', { class: 'section' }, h('h2', {}, 'Пользователи и роли')), h('div', { class: 'section', style: { padding: '0' } }, list));
  await load();
}

/* Signature / seal: drawn with the mouse or uploaded, white background removed, stored as a transparent PNG. */
async function marks(body) {
  const kinds = isStaff() ? [['signature', 'Подпись', 'Ставится в редакторе на документы, где нужна ваша подпись.'],
    ['seal', 'Печать деканата', 'Электронная печать: ставится сотрудником деканата в редакторе. Загрузите PNG или SVG.']]
    : [['signature', 'Моя подпись', 'Ставится в редакторе на ваши заявления. Только ваша собственная подпись.']];
  for (const [kind, title, hint] of kinds) {
    const preview = h('div', { class: 'mark-preview' });
    const canvas = h('canvas', { class: 'sign-pad', width: 600, height: 220 });
    const ctx = canvas.getContext('2d');
    let drawing = false, drawn = false;
    const pos = (e) => { const r = canvas.getBoundingClientRect(); return [(e.clientX - r.left) * canvas.width / r.width, (e.clientY - r.top) * canvas.height / r.height]; };
    canvas.addEventListener('pointerdown', (e) => { drawing = true; drawn = true; canvas.setPointerCapture(e.pointerId); ctx.beginPath(); ctx.moveTo(...pos(e)); });
    canvas.addEventListener('pointermove', (e) => { if (!drawing) return; ctx.lineWidth = 3.2; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#1a2a8c'; ctx.lineTo(...pos(e)); ctx.stroke(); });
    canvas.addEventListener('pointerup', () => { drawing = false; });
    const showCurrent = () => {
      const has = kind === 'seal' ? state.user.has_seal : state.user.has_signature;
      preview.replaceChildren(has ? h('img', { src: `/api/me/marks/${kind}?t=${Date.now()}`, alt: title }) : h('span', { class: 'subtle' }, 'Ещё не загружено'));
    };
    const save = async (blob) => {
      const form = new FormData(); form.append('file', blob, kind + '.png');
      try { state.user = (await api(`/api/me/marks/${kind}`, { method: 'POST', form })).user; showCurrent(); ok(title + ' сохранена'); }
      catch (e) { showError(e); }
    };
    const file = h('input', { type: 'file', accept: '.png,.jpg,.jpeg,.svg', hidden: true });
    file.addEventListener('change', async () => {
      const f = file.files[0]; if (!f) return;
      try { await save(await toTransparentPng(f)); } catch (e) { showError({ title: 'Не удалось прочитать картинку', detail: 'Подойдёт PNG, JPG или SVG.' }); }
      file.value = '';
    });
    body.append(h('div', { class: 'section' }, h('div', { class: 'section-head' }, h('div', {}, h('h2', {}, title), h('p', { class: 'muted', style: { marginTop: '4px', maxWidth: '520px' } }, hint)), preview),
      kind === 'signature' ? h('div', { style: { marginTop: '14px' } }, canvas, h('div', { class: 'row', style: { marginTop: '8px', gap: '8px' } },
        h('button', { class: 'btn ghost sm', onclick: () => { ctx.clearRect(0, 0, canvas.width, canvas.height); drawn = false; } }, icon('eraser'), 'Очистить'),
        h('button', { class: 'btn primary sm', onclick: async () => {
          if (!drawn) return showError({ title: 'Распишитесь в поле выше' });
          save(await trimmedBlob(canvas));
        } }, icon('check'), 'Сохранить нарисованную'),
        h('span', { class: 'subtle', style: { fontSize: '12.5px' } }, 'или'),
        h('button', { class: 'btn sm', onclick: () => file.click() }, icon('upload'), 'Загрузить картинку'), file))
        : h('div', { class: 'row', style: { marginTop: '12px', gap: '8px' } }, h('button', { class: 'btn', onclick: () => file.click() }, icon('upload'), 'Загрузить печать'), file),
      h('button', { class: 'btn ghost sm danger', style: { marginTop: '10px' }, onclick: async () => {
        try { state.user = (await api(`/api/me/marks/${kind}`, { method: 'DELETE' })).user; showCurrent(); info('Удалено'); } catch (e) { showError(e); }
      } }, icon('trash-2'), 'Удалить')));
    showCurrent();
  }
}

function trimmedBlob(canvas) {
  const ctx = canvas.getContext('2d');
  const { data, width, height } = ctx.getImageData(0, 0, canvas.width, canvas.height);
  let x0 = width, y0 = height, x1 = 0, y1 = 0;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) if (data[(y * width + x) * 4 + 3] > 0) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  const out = document.createElement('canvas');
  out.width = Math.max(1, x1 - x0 + 12); out.height = Math.max(1, y1 - y0 + 12);
  out.getContext('2d').drawImage(canvas, x0 - 6, y0 - 6, out.width, out.height, 0, 0, out.width, out.height);
  return new Promise((resolve) => out.toBlob(resolve, 'image/png'));
}

/* Photo or scan of a signature/seal on white paper -> ink on a transparent background. SVG is rasterised by the browser. */
async function toTransparentPng(file) {
  const url = URL.createObjectURL(file);
  const img = await new Promise((resolve, reject) => { const i = new Image(); i.onload = () => resolve(i); i.onerror = reject; i.src = url; });
  const scale = Math.min(1, 900 / Math.max(img.naturalWidth || 600, img.naturalHeight || 600));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round((img.naturalWidth || 600) * scale); canvas.height = Math.round((img.naturalHeight || 600) * scale);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  URL.revokeObjectURL(url);
  const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const d = pixels.data;
  for (let i = 0; i < d.length; i += 4) {
    const light = (d[i] + d[i + 1] + d[i + 2]) / 3;
    const alpha = Math.max(0, Math.min(255, (235 - light) * 3));  // white paper -> transparent, ink stays
    d[i + 3] = Math.min(d[i + 3], alpha);
  }
  ctx.putImageData(pixels, 0, 0);
  return trimmedBlob(canvas);
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
