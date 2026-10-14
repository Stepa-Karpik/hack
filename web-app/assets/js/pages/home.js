import { h, icon, refreshIcons, api, TYPES, showError } from '../ui.js';
import { state, uploadFiles } from '../main.js';
import { documentRow } from './history.js';

const SAMPLES = [['study', 'study_certificate', 'Справка об обучении'], ['leave', 'academic_leave_application', 'Заявление на отпуск'],
  ['internship', 'internship_certificate', 'Справка о практике']];

export async function render(app) {
  const type = h('select', { class: 'select', 'aria-label': 'Тип документа' },
    ...Object.entries(TYPES).map(([v, l]) => h('option', { value: v }, l)));
  const input = h('input', { type: 'file', accept: '.pdf,.png,.jpg,.jpeg', multiple: true, hidden: true });
  const drop = h('label', { class: 'drop', tabindex: '0' },
    h('div', { class: 'ico' }, icon('file-up')),
    h('strong', {}, 'Перетащите документы или выберите файлы'),
    h('span', { class: 'muted' }, 'PDF, JPG или PNG · до 10 МБ · можно сразу несколько — обработаем в фоне'), input);
  const go = (files) => uploadFiles(files, type.value, { open: files.length === 1 });
  input.addEventListener('change', () => { go(input.files); input.value = ''; });
  drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
  for (const ev of ['dragenter', 'dragover']) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); });
  for (const ev of ['dragleave', 'drop']) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); });
  drop.addEventListener('drop', (e) => go(e.dataTransfer.files));

  const samples = h('div', { class: 'samples' }, 'Нет документа под рукой? Примеры:',
    ...SAMPLES.map(([file, kind, label]) => h('button', { class: 'btn sm', onclick: async () => {
      try {
        const blob = await (await fetch(`/assets/samples/${file}.png`)).blob();
        uploadFiles([new File([blob], `Пример — ${label}.png`, { type: 'image/png' })], kind, { open: true });
      } catch (e) { showError(e); }
    } }, label)));

  const recent = h('div', { class: 'card' });
  const name = state.user.name ? `, ${state.user.name}` : '';
  app.append(h('div', { class: 'page' },
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, `Проверка документов${name}`),
      h('p', { class: 'muted' }, 'Модель читает документ, находит поля, подпись и печать и проверяет комплектность по Положению.'))),
    h('div', { class: 'hero' }, drop, h('div', { class: 'upload-bar' }, h('span', { class: 'muted' }, 'Тип:'), type, h('div', { class: 'grow' }), samples)),
    h('div', { class: 'row', style: { margin: '36px 0 12px' } }, h('h2', { class: 'grow' }, 'Недавние'),
      h('a', { href: '/history', 'data-link': '', class: 'btn ghost sm' }, 'Вся история', icon('arrow-right'))),
    recent));

  async function load() {
    try {
      const { documents } = await api('/api/documents');
      recent.replaceChildren(documents.length ? h('div', { class: 'list' }, ...documents.slice(0, 6).map(documentRow))
        : h('div', { class: 'empty' }, icon('inbox'), h('div', {}, 'Здесь появятся ваши проверки')));
      refreshIcons();
    } catch (e) { showError(e); }
  }
  await load();
  const onPoll = () => load();
  window.addEventListener('documents-changed', onPoll);
  window.addEventListener('document-updated', onPoll);
  return () => { window.removeEventListener('documents-changed', onPoll); window.removeEventListener('document-updated', onPoll); };
}
