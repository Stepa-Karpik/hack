import { h, icon, api, showError, ok, refreshIcons } from '../ui.js';
import { state, navigate, renderTopbar } from '../main.js';

function shell(title, subtitle, form, foot) {
  return h('div', { class: 'auth' }, h('div', { class: 'card' },
    h('div', { class: 'brand-mark', style: { width: '38px', height: '38px', borderRadius: '11px', marginBottom: '18px' } }, icon('file-check-2')),
    h('h1', {}, title), h('p', { class: 'muted' }, subtitle), form, h('div', { class: 'foot' }, foot)));
}

function field(label, attrs) {
  const id = 'f-' + attrs.name;
  return h('div', { class: 'field-group' }, h('label', { class: 'label', for: id }, label), h('input', { class: 'input', id, ...attrs }));
}

async function submit(form, url, payload) {
  const button = form.querySelector('button[type=submit]');
  button.disabled = true;
  try {
    const { user } = await api(url, { method: 'POST', body: payload });
    state.user = user;
    renderTopbar();
    const next = new URLSearchParams(location.search).get('next');
    navigate(next && next.startsWith('/') && !next.startsWith('//') ? next : '/', true);
    return true;
  } catch (e) { showError(e); return false; } finally { button.disabled = false; }
}

export function login(app) {
  const form = h('form', { novalidate: true },
    field('Почта', { name: 'email', type: 'email', autocomplete: 'email', required: true, autofocus: true, placeholder: 'name@university.ru' }),
    field('Пароль', { name: 'password', type: 'password', autocomplete: 'current-password', required: true }),
    h('button', { class: 'btn primary lg', type: 'submit' }, 'Войти'));
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    submit(form, '/api/auth/login', { email: form.email.value, password: form.password.value });
  });
  app.append(shell('Вход', 'Документы и история проверок хранятся в вашем аккаунте.', form,
    h('span', {}, 'Нет аккаунта? ', h('a', { href: '/register' + location.search, 'data-link': '' }, 'Зарегистрироваться'))));
}

export async function register(app) {
  const token = new URLSearchParams(location.search).get('invite');
  let invite = null;
  if (token) {
    try { invite = await api('/api/invites/' + encodeURIComponent(token)); }
    catch (e) { showError({ title: 'Приглашение недействительно', detail: 'Ссылка устарела или уже использована. Попросите новую у администратора.' }); }
  }
  const staff = !!invite;
  const group = field('Учебная группа', { name: 'study_group', autocomplete: 'off', placeholder: 'Например, ИВТ-21' });
  const form = h('form', { novalidate: true },
    staff ? h('div', { class: 'verdict info', style: { margin: '0 0 14px' } }, h('div', { class: 'verdict-title' }, icon('shield-check'),
      invite.role === 'admin' ? 'Приглашение администратора' : 'Приглашение для сотрудника деканата'),
      h('div', { class: 'muted', style: { fontSize: '13px' } }, invite.note || 'После регистрации вам будут видны заявки студентов.')) : null,
    field(staff ? 'Имя и фамилия' : 'ФИО — как в документах', { name: 'name', autocomplete: 'name', required: true,
      placeholder: staff ? 'Как к вам обращаться' : 'Иванов Иван Иванович' }),
    staff ? null : group,
    field('Почта', { name: 'email', type: 'email', autocomplete: 'email', required: true, placeholder: 'name@university.ru' }),
    field('Пароль', { name: 'password', type: 'password', autocomplete: 'new-password', required: true, placeholder: 'Не короче 8 символов' }),
    h('button', { class: 'btn primary lg', type: 'submit' }, 'Создать аккаунт'));
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = { name: form.name.value, email: form.email.value, password: form.password.value };
    if (staff) body.invite = token; else body.study_group = form.study_group.value;
    if (await submit(form, '/api/auth/register', body))
      ok('Аккаунт создан', staff ? 'Входящие заявки студентов — в разделе «Входящие».' : 'Загрузите документ — проверка займёт несколько секунд.');
  });
  app.append(shell(staff ? 'Регистрация сотрудника' : 'Регистрация',
    staff ? 'Деканат принимает и проверяет заявки студентов.' : 'ФИО нужно, чтобы сверять его с документами. Всё работает локально.', form,
    h('span', {}, 'Уже есть аккаунт? ', h('a', { href: '/login', 'data-link': '' }, 'Войти'))));
  refreshIcons();
}
