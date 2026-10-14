import { h, icon, api, showError, ok } from '../ui.js';
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

export function register(app) {
  const form = h('form', { novalidate: true },
    field('Имя', { name: 'name', autocomplete: 'name', placeholder: 'Как к вам обращаться' }),
    field('Почта', { name: 'email', type: 'email', autocomplete: 'email', required: true, placeholder: 'name@university.ru' }),
    field('Пароль', { name: 'password', type: 'password', autocomplete: 'new-password', required: true, placeholder: 'Не короче 8 символов' }),
    h('button', { class: 'btn primary lg', type: 'submit' }, 'Создать аккаунт'));
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (await submit(form, '/api/auth/register', { name: form.name.value, email: form.email.value, password: form.password.value }))
      ok('Аккаунт создан', 'Загрузите первый документ — проверка займёт несколько секунд.');
  });
  app.append(shell('Регистрация', 'Всё работает локально: документы не уходят во внешние сервисы.', form,
    h('span', {}, 'Уже есть аккаунт? ', h('a', { href: '/login' + location.search, 'data-link': '' }, 'Войти'))));
}
