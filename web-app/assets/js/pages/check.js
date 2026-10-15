import { $, $$, h, icon, refreshIcons, api, TYPES, LABELS, displayValue, statusChip, showError, ok, info, copy, ago, modal } from '../ui.js';
import { navigate, watch, isStaff } from '../main.js';
import { mountChat } from '../chat.js';

const RULE_TEXT = { '3.1': 'п. 3.1', '3.2': 'п. 3.2', '3.3': 'п. 3.3', '4.1': 'п. 4.1', '4.2': 'п. 4.2', '5.1': 'п. 5.1', '5.2': 'п. 5.2', '5.3': 'п. 5.3' };
const MARK_PLACES = { signature_present: /\(подпись\)|подпись[^\n]{0,40}_{3,}|_{3,}[^\n]{0,40}подпись/i, seal_present: /\bМ\.?\s?П\.?(?![а-яё])|место печати/i };
const ACTIONS = {
  signature_present: { study_certificate: 'Попросите уполномоченного сотрудника вуза подписать справку', academic_leave_application: 'Подпишите заявление', internship_certificate: 'Попросите руководителя практики подписать справку' },
  seal_present: { study_certificate: 'Попросите поставить печать вуза', internship_certificate: 'Попросите поставить печать организации' },
};
const ruleFor = (key, kind) => ({ study_certificate: { signature_present: '3.2', seal_present: '3.3' }, academic_leave_application: { signature_present: '4.2' },
  internship_certificate: { signature_present: '5.2', seal_present: '5.3' } }[kind]?.[key] || { study_certificate: '3.1', academic_leave_application: '4.1', internship_certificate: '5.1' }[kind]);

export async function render(app, slug) {
  let doc = null, regionsOn = true, view = 'page', pollTimer = null, active = null, chat = null, chatPane = null, disposed = false, resizeObserver = null;
  const root = h('div', { class: 'page wide' });
  app.append(root);

  async function load(open = false) {
    try { doc = await api(`/api/documents/${slug}${open ? '?open=1' : ''}`); }
    catch (e) { if (e.status === 404) { root.replaceChildren(notFound()); refreshIcons(); return; } showError(e); return; }
    if (doc.status === 'done') draw(); else drawProcessing();
  }

  function notFound() {
    return h('div', { class: 'empty', style: { paddingTop: '80px' } }, icon('file-question'), h('h1', {}, 'Документ не найден'),
      h('p', { class: 'muted' }, 'Он был удалён или ссылка неверна.'), h('a', { href: '/history', 'data-link': '', class: 'btn', style: { marginTop: '14px' } }, 'К истории'));
  }

  function drawProcessing() {
    const started = doc.created;
    const timer = h('span', { class: 'muted' });
    const speedNote = h('p', { class: 'muted' }, 'Обычно это занимает 5–10 секунд. Можно уйти со страницы — мы сообщим, когда всё будет готово.');
    api('/api/health').then((s) => {
      if (s.reader === 'server-cpu' || s.reader === 'cpu-fast') speedNote.textContent = 'Распознаём на процессоре — обычно 5–10 секунд. Можно уйти со страницы — мы сообщим, когда всё будет готово.';
    }).catch(() => {});
    const tick = () => { timer.textContent = `${Math.max(0, Math.round(Date.now() / 1000 - started))} с`; };
    tick();
    root.replaceChildren(h('div', { class: 'workspace chat-closed' },
      h('section', { class: 'pane viewer-pane' }, h('div', { class: 'pane-head' }, h('h2', { class: 'grow' }, doc.filename), statusChip(doc)),
        h('div', { class: 'viewer' }, doc.status === 'failed'
          ? h('div', { class: 'empty' }, icon('file-x'), h('h2', {}, 'Не удалось распознать документ'),
            h('p', { class: 'muted' }, doc.error?.includes('PDF') ? 'Многостраничный PDF пока не поддерживается — загрузите одну страницу.' : 'Попробуйте загрузить другой файл или снимок получше.'))
          : h('div', { class: 'empty' }, icon('loader-circle', 'spin'), h('h2', {}, doc.status === 'queued' ? 'В очереди' : 'Распознаём документ'),
            speedNote, timer))),
      h('section', { class: 'pane' }, h('div', { class: 'pane-head' }, h('h2', {}, 'Сведения')),
        h('div', { class: 'stack', style: { padding: '16px' } }, ...Array.from({ length: 8 }, () => h('div', { class: 'skel', style: { height: '38px' } }))))));
    refreshIcons();
    if (doc.status !== 'failed') {
      watch(doc.slug, doc.filename);
      clearInterval(pollTimer);
      pollTimer = setInterval(async () => {
        tick();
        try {
          const next = await api(`/api/documents/${slug}`);
          if (next.status !== doc.status || next.status === 'done') { doc = next; clearInterval(pollTimer); load(true); }
        } catch {}
      }, 1000);
    }
  }

  function draw() {
    const a = doc.analysis;
    const kind = a.document_type;
    const regions = doc.regions?.regions || [];
    const typeSelect = h('select', { class: 'select', style: { width: 'auto', height: '30px', fontSize: '13px' }, title: 'Тип документа' },
      ...Object.entries(TYPES).filter(([k]) => k !== 'auto').map(([k, l]) => h('option', { value: k, selected: k === kind }, l)));
    typeSelect.addEventListener('change', async () => {
      try { doc = await api(`/api/documents/${slug}/type`, { method: 'POST', body: { document_type: typeSelect.value } }); draw(); ok('Тип изменён', 'Поля пересчитаны по тому же распознанному тексту.'); }
      catch (e) { showError(e); }
    });

    // ---- viewer
    const frame = h('div', { class: 'page-frame' + (regionsOn ? ' regions-on' : '') });
    const img = h('img', { alt: doc.filename, draggable: 'false' });
    frame.append(img);
    for (const r of regions) {
      const [x0, y0, x1, y1] = r.bbox;
      const missingPlace = r.kind === 'missing';
      const box = h('button', { class: 'region' + (r.field.endsWith('_present') ? ' mark' : '') + (missingPlace ? ' missing' : ''),
        title: missingPlace ? `Здесь должна быть ${r.field === 'seal_present' ? 'печать' : 'подпись'}` : (LABELS[r.field] || r.field), 'data-field': r.field,
        style: { left: x0 * 100 + '%', top: y0 * 100 + '%', width: (x1 - x0) * 100 + '%', height: (y1 - y0) * 100 + '%' } });
      box.addEventListener('mouseenter', () => focus(r.field, false));
      box.addEventListener('click', () => focus(r.field, true));
      frame.append(box);
    }
    const textView = h('div', { class: 'pane-body', hidden: view !== 'text' }, h('pre', { class: 'ocr-text' }, a.ocr_text || 'Текст не распознан.'));
    const viewer = h('div', { class: 'viewer', hidden: view !== 'page' }, frame);
    // Fit the whole page into the visible area (no scrolling); overlays use the frame's box.
    const fit = () => {
      if (!img.naturalWidth || !viewer.clientWidth) return;
      const ratio = img.naturalWidth / img.naturalHeight;
      const maxW = viewer.clientWidth - 28, maxH = viewer.clientHeight - 28;
      const width = Math.max(50, Math.min(maxW, maxH * ratio));
      frame.style.width = width + 'px'; frame.style.height = width / ratio + 'px';
    };
    img.addEventListener('load', fit);
    img.src = doc.preview_url;
    if (img.complete) requestAnimationFrame(fit);
    resizeObserver?.disconnect();
    resizeObserver = new ResizeObserver(fit);
    resizeObserver.observe(viewer);
    const regionState = doc.regions?.status || 'pending';
    const regionsBtn = h('button', { class: 'btn sm' + (regionsOn ? '' : ' ghost'), disabled: regionState !== 'done' || !regions.length,
      title: regionState === 'pending' ? 'Разметка строится…' : regions.length ? 'Показать области полей' : 'Области не найдены',
      onclick: () => { regionsOn = !regionsOn; frame.classList.toggle('regions-on', regionsOn); regionsBtn.classList.toggle('ghost', !regionsOn); } },
      regionState === 'pending' ? icon('loader-circle', 'spin') : icon('scan-text'), regionState === 'pending' ? 'Разметка…' : 'Разметка');
    const viewTabs = h('div', { class: 'tabs' },
      h('button', { class: view === 'page' ? 'active' : '', onclick: () => { view = 'page'; draw(); } }, 'Документ'),
      h('button', { class: view === 'text' ? 'active' : '', onclick: () => { view = 'text'; draw(); } }, 'Текст'));
    const can = doc.can || {};
    const staff = isStaff();
    const foreign = !!doc.owner;  // staff looking at a student's application
    const state = doc.state || 'draft';
    const menu = h('div', { class: 'menu' });
    const menuItem = (iconName, label, onclick, cls = '') => h('button', { class: cls, onclick: () => { menu.classList.remove('open'); onclick(); } }, icon(iconName), label);
    menu.append(h('button', { class: 'btn ghost icon sm', title: 'Действия', onclick: (e) => { e.stopPropagation(); menu.classList.toggle('open'); } }, icon('ellipsis')),
      h('div', { class: 'menu-panel' },
        menuItem('history', 'История заявки', openHistory),
        can.edit ? menuItem('pen-tool', staff && foreign ? 'Поставить печать или подпись' : 'Открыть в редакторе', () => navigate(`/check/${slug}/edit`)) : null,
        can.replace ? menuItem('file-up', 'Заменить файл', pickReplacement) : null,
        menuItem('file-text', 'Протокол проверки (PDF)', () => window.open(`/api/documents/${slug}/protocol.pdf`, '_blank')),
        menuItem('external-link', 'Открыть оригинал', () => window.open(doc.file_url, '_blank')),
        menuItem('link', 'Копировать ссылку', () => copy(location.href, 'Ссылка скопирована')),
        can.close ? menuItem('archive-x', 'Закрыть заявку', openClose, 'danger') : null,
        can.delete ? menuItem('trash-2', 'Удалить', remove, 'danger') : null));
    const viewerPane = h('section', { class: 'pane viewer-pane' },
      h('div', { class: 'pane-head' }, h('div', { class: 'grow', style: { minWidth: 0 } },
        h('div', { class: 'item-title', title: doc.filename }, doc.filename),
        h('div', { class: 'subtle', style: { fontSize: '12px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } },
          (doc.owner ? `${doc.owner.name || doc.owner.email} · ` : '') + (doc.version > 1 ? `версия ${doc.version} · ` : '')
          + `${String(a.model.seconds.toFixed(1)).replace('.', ',')} с · ${ago(doc.created)}`)),
        viewTabs, regionsBtn, menu),
      viewer, textView);

    // ---- fields
    const missing = a.validation.missing_fields;
    const okDoc = a.validation.status === 'document_ok';
    const verdict = h('div', { class: 'verdict ' + (okDoc ? 'ok' : 'warn') },
      h('div', { class: 'verdict-title' }, icon(okDoc ? 'circle-check' : 'circle-alert'),
        okDoc ? 'Все обязательные сведения найдены' : `Не хватает: ${missing.map((k) => LABELS[k]).join(', ')}`),
      okDoc ? h('div', { class: 'muted', style: { fontSize: '13px' } }, 'Это предварительная проверка. Окончательное решение принимает сотрудник деканата (п. 1.3).')
        : h('ul', {}, ...missing.map((k) => h('li', {}, action(k, kind, a), ' ', h('span', { class: 'subtle' }, RULE_TEXT[ruleFor(k, kind)] || '')))));
    if (!a.type_matches) verdict.append(h('div', { class: 'muted', style: { fontSize: '12.5px' } },
      a.detected_type ? `Модель видит заголовок «${TYPES[a.detected_type]}». Проверьте тип документа.` : 'Заголовок документа не распознан — поля могут быть не найдены. Выберите тип вручную.'));
    const nameWarn = doc.name_check?.status === 'mismatch' ? h('div', { class: 'verdict warn' },
      h('div', { class: 'verdict-title' }, icon('user-x'), foreign ? 'ФИО в документе не совпадает с профилем студента' : 'ФИО в документе не совпадает с вашим профилем'),
      h('div', { class: 'muted', style: { fontSize: '13px' } }, `В документе: «${doc.name_check.document}». В профиле: «${doc.name_check.profile}».`)) : null;

    const rows = Object.entries(a.fields).map(([key, value]) => fieldRow(key, value, a, kind));
    const total = rows.length;
    const verifiedCount = Object.keys(a.fields).filter((k) => doc.verified[k]).length;
    const foot = [];
    if (can.submit) foot.push(h('button', { class: 'btn primary', onclick: openSubmit }, icon('send'), state === 'returned' ? 'Отправить снова' : 'Отправить в деканат'));
    if (can.decide) {
      if (state === 'approved' || state === 'returned') foot.push(h('button', { class: 'btn', onclick: () => decide(null) }, icon('rotate-ccw'), 'Отменить решение'));
      else foot.push(h('button', { class: 'btn', onclick: openReturn }, icon('undo-2'), 'Вернуть'),
        h('button', { class: 'btn primary', onclick: () => decide('approved') }, icon('check-check'), 'Одобрить'));
    }
    const fieldsPane = h('section', { class: 'pane' },
      h('div', { class: 'pane-head' }, h('h2', { class: 'grow' }, 'Сведения'), typeSelect,
        h('span', { class: 'chip' + (a.validation.status === 'document_ok' ? ' ok' : ' warn') }, `${doc.found}/${doc.total}`)),
      h('div', { class: 'pane-body' }, stateBanner(state, foreign), nameWarn, verdict, h('div', { class: 'fields' }, ...rows),
        h('p', { class: 'subtle', style: { padding: '4px 16px 14px', fontSize: '12px' } },
          staff ? 'Значения прочитаны автоматически. «Проверьте» — там, где распознавание не уверено. Галочкой отмечайте сверенные с оригиналом поля.'
            : 'Значения прочитаны автоматически. «Проверьте» — там, где распознавание не уверено: сверьте с оригиналом.')),
      h('div', { class: 'pane-foot' }, h('span', { class: 'muted grow', style: { fontSize: '12.5px' } },
          staff && foreign ? `Сверено вручную: ${verifiedCount} из ${total}` + (doc.attempts > 1 ? ` · попытка ${doc.attempts}` : '') : doc.state_name),
        ...foot));

    if (!chatPane) {  // the chat keeps its state across redraws of the other panes
      chatPane = h('section', { class: 'pane chat' });
      chat = mountChat(chatPane, doc, { onSource: (key) => focus(key, true) });
    } else chat.update?.(doc);
    const ws = h('div', { class: 'workspace' }, viewerPane, fieldsPane, chatPane);
    root.replaceChildren(ws);
    refreshIcons();
    if (active) focus(active, false);
  }

  function action(key, kind, a) {
    if (ACTIONS[key]) {
      const ask = ACTIONS[key][kind] || 'Добавьте отметку';
      if (MARK_PLACES[key]?.test(a.ocr_text || '')) return `Сверьте с оригиналом: место для отметки есть, но модель её не нашла. Если её нет — ${ask[0].toLowerCase() + ask.slice(1)}.`;
      return ask + '.';
    }
    return `Заполните поле «${LABELS[key]}» или убедитесь, что оно хорошо видно на снимке.`;
  }

  function fieldRow(key, value, a, kind) {
    const missing = value === 'не найдено' || value === false;
    const mark = key.endsWith('_present');
    const verified = !!doc.verified[key];
    const chips = [];
    const conf = a.confidence?.[key];
    if (!missing && !mark && a.review?.[key]) chips.push(h('span', { class: 'chip warn', title: conf != null ? `Уверенность модели: ${Math.round(conf * 100)}%` : 'Значение прочитано неоднозначно' }, 'Проверьте'));
    if (mark && value === false && MARK_PLACES[key]?.test(a.ocr_text || '')) chips.push(h('span', { class: 'chip warn', title: 'Место для отметки есть, но модель её не нашла' }, 'Проверьте вручную'));
    if (mark && value === true && conf != null && conf < 0.8) chips.push(h('span', { class: 'chip warn', title: `Уверенность: ${Math.round(conf * 100)}%` }, 'Проверьте'));
    const tick = h('button', { class: 'vbtn' + (verified ? ' on' : ''), title: verified ? 'Сверено — снять отметку' : 'Отметить как сверенное с оригиналом',
      'aria-pressed': String(verified), onclick: async (e) => {
        e.stopPropagation();
        try { const r = await api(`/api/documents/${slug}/verify`, { method: 'POST', body: { field: key, verified: !verified } }); doc.verified = r.verified; draw(); }
        catch (err) { showError(err); }
      } }, icon(verified ? 'circle-check' : 'circle'));
    const ask = h('button', { class: 'vbtn', title: 'Спросить ассистента', onclick: (e) => {
      e.stopPropagation();
      chat?.ask(missing ? `Почему не найдено поле «${LABELS[key]}» и что делать?` : `Расскажи про поле «${LABELS[key]}»: что там указано?`);
    } }, icon('message-circle'));
    const row = h('div', { class: 'frow' + (missing ? ' missing' : '') + (verified ? ' verified' : ''), 'data-field': key },
      h('div', { style: { minWidth: 0 } }, h('div', { class: 'k' }, LABELS[key] || key),
        h('div', { class: 'row', style: { flexWrap: 'wrap', gap: '6px' } }, h('span', { class: 'v' }, missing && !mark ? 'не найдено' : displayValue(value)), ...chips)),
      h('div', { class: 'tools' }, ask, isStaff() && doc.owner ? tick : null));
    row.addEventListener('mouseenter', () => focus(key, false));
    row.addEventListener('click', () => focus(key, true));
    return row;
  }

  function focus(key, scroll) {
    active = key;
    $$('.frow', root).forEach((r) => r.classList.toggle('active', r.dataset.field === key));
    $$('.region', root).forEach((r) => r.classList.toggle('active', r.dataset.field === key));
    if (scroll) {
      $(`.frow[data-field="${key}"]`, root)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      if (view !== 'page') { view = 'page'; draw(); focus(key, false); }
    }
  }

  function stateBanner(state, foreign) {
    const when = (t) => t ? new Date(t * 1000).toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' }) : '';
    const block = (cls, iconName, title, ...lines) => h('div', { class: 'verdict ' + cls },
      h('div', { class: 'verdict-title' }, icon(iconName), title), ...lines.filter(Boolean).map((l) => typeof l === 'string' ? h('div', { class: 'muted', style: { fontSize: '13px' } }, l) : l));
    const quote = (text, author) => text ? h('blockquote', { class: 'quote' }, text, author ? h('div', { class: 'subtle', style: { fontSize: '12px', marginTop: '4px' } }, author) : null) : null;
    if (foreign) {
      const who = `${doc.owner.name || 'Студент'}${doc.owner.group ? ' · ' + doc.owner.group : ''} · ${doc.owner.email}`;
      const head = block(state === 'approved' ? 'ok' : state === 'returned' ? 'warn' : state === 'closed' ? 'bad' : 'info',
        { submitted: 'inbox', review: 'eye', approved: 'badge-check', returned: 'undo-2', closed: 'archive-x' }[state] || 'inbox',
        doc.state_name, who, doc.submitted_at ? `Отправлено ${when(doc.submitted_at)}${doc.attempts > 1 ? ` · попытка ${doc.attempts}` : ''}` : '',
        quote(doc.student_comment, 'комментарий студента'), state !== 'review' && state !== 'submitted' ? quote(doc.decision_comment, 'комментарий деканата') : null);
      return head;
    }
    if (state === 'draft') return block('info', 'file-pen', 'Черновик — его видите только вы',
      'Проверьте сведения. Если что-то не так — замените файл или поправьте его в редакторе (меню «⋯»), затем отправьте в деканат.');
    if (state === 'submitted') return block('info', 'send', `Отправлено в деканат ${when(doc.submitted_at)}`, 'Сотрудник деканата скоро возьмёт заявку на рассмотрение.');
    if (state === 'review') return block('info', 'eye', 'На рассмотрении в деканате', 'Решение появится здесь — мы пришлём уведомление.');
    if (state === 'approved') return block('ok', 'badge-check', 'Одобрено деканатом', quote(doc.decision_comment));
    if (state === 'returned') return block('warn', 'undo-2', 'Возвращено на доработку', quote(doc.decision_comment, 'комментарий деканата'),
      'Исправьте документ — замените файл или поправьте его в редакторе — и отправьте снова.');
    if (state === 'closed') return block('bad', 'archive-x', 'Заявка закрыта деканатом', quote(doc.decision_comment));
    return null;
  }

  function openSubmit() {
    const comment = h('textarea', { class: 'input', rows: 3, placeholder: 'Комментарий для деканата (необязательно)', style: { height: 'auto', padding: '10px 12px' } });
    const warn = doc.submit_warning;
    const m = modal({
      title: warn ? 'Документ проверен, но есть замечания' : 'Отправить в деканат?',
      body: [warn ? h('div', { class: 'verdict warn', style: { margin: '0 0 14px' } }, h('div', { class: 'verdict-title' }, icon('triangle-alert'), 'Скорее всего, заявление вернут'),
          h('div', { style: { fontSize: '13.5px', lineHeight: '1.55' } }, warn))
        : h('p', { class: 'muted', style: { marginBottom: '14px' } }, 'Все обязательные сведения найдены. Документ увидит сотрудник деканата и примет решение.'), comment],
      actions: [h('button', { class: 'btn', onclick: () => m.close() }, warn ? 'Исправить документ' : 'Отмена'),
        h('button', { class: 'btn primary', onclick: async (e) => {
          e.target.disabled = true;
          try {
            doc = await api(`/api/documents/${slug}/submit`, { method: 'POST', body: { comment: comment.value } });
            m.close(); draw(); ok('Отправлено в деканат', 'Решение появится в истории заявки.');
          } catch (err) { e.target.disabled = false; showError(err); }
        } }, icon('send'), warn ? 'Всё равно отправить' : 'Отправить')],
    });
  }

  function openReturn() {
    const missing = doc.analysis.validation.missing_fields;
    const comment = h('textarea', { class: 'input', rows: 4, style: { height: 'auto', padding: '10px 12px' } });
    comment.value = missing.length ? `Не хватает: ${missing.map((k) => LABELS[k].toLowerCase()).join(', ')}. Исправьте документ и отправьте снова.` : '';
    const m = modal({ title: 'Вернуть на доработку', body: [h('p', { class: 'muted', style: { marginBottom: '10px' } }, 'Студент увидит этот комментарий в своей заявке.'), comment],
      actions: [h('button', { class: 'btn', onclick: () => m.close() }, 'Отмена'),
        h('button', { class: 'btn primary', onclick: () => { if (!comment.value.trim()) return showError({ title: 'Напишите комментарий', detail: 'Объясните студенту, что исправить.' }); m.close(); decide('returned', comment.value.trim()); } }, icon('undo-2'), 'Вернуть')] });
    comment.focus();
  }

  function openClose() {
    const comment = h('textarea', { class: 'input', rows: 3, style: { height: 'auto', padding: '10px 12px' }, placeholder: 'Причина, например: превышено число попыток' });
    const m = modal({ title: 'Закрыть заявку?', body: [h('p', { class: 'muted', style: { marginBottom: '10px' } },
        `Студент больше не сможет отправлять документы по этой заявке.${doc.attempts ? ` Попыток отправки: ${doc.attempts}.` : ''}`), comment],
      actions: [h('button', { class: 'btn', onclick: () => m.close() }, 'Отмена'),
        h('button', { class: 'btn danger', onclick: async () => {
          try { doc = await api(`/api/documents/${slug}/close`, { method: 'POST', body: { comment: comment.value } }); m.close(); draw(); info('Заявка закрыта'); }
          catch (e) { showError(e); }
        } }, icon('archive-x'), 'Закрыть заявку')] });
  }

  async function openHistory() {
    let data;
    try { data = await api(`/api/documents/${slug}/history`); } catch (e) { return showError(e); }
    const ICONS = { uploaded: 'upload', processed: 'scan-text', submitted: 'send', review: 'eye', approved: 'badge-check', auto_approved: 'badge-check',
      returned: 'undo-2', reset: 'rotate-ccw', replaced: 'file-up', edited: 'pen-tool', closed: 'archive-x', type_changed: 'shapes' };
    const items = data.events.map((e) => {
      const d = e.detail || {};
      const extra = [d.comment && `«${d.comment}»`, d.filename && e.kind !== 'uploaded' ? d.filename : null, d.found && `найдено ${d.found}`,
        d.version && e.kind !== 'uploaded' ? `версия ${d.version}` : null, d.ops].filter(Boolean).join(' · ');
      return h('li', { class: 'tl-item ' + e.kind }, h('span', { class: 'tl-dot' }, icon(ICONS[e.kind] || 'circle')),
        h('div', {}, h('div', { style: { fontWeight: 560 } }, e.title,
            h('span', { class: 'subtle', style: { fontWeight: 400, marginLeft: '8px', fontSize: '12.5px' } }, new Date(e.at * 1000).toLocaleString('ru-RU'))),
          h('div', { class: 'muted', style: { fontSize: '12.5px' } }, (e.who ? `${e.who}${e.role === 'student' ? ' (студент)' : e.role ? ' (деканат)' : ''}` : 'система') + (extra ? ' · ' + extra : ''))));
    });
    const versions = data.versions.length ? h('div', { style: { marginTop: '14px' } }, h('div', { class: 'label' }, 'Прежние версии файла'),
      ...data.versions.map((v) => h('a', { class: 'btn ghost sm', href: `/api/documents/${slug}/versions/${v.n}/file`, target: '_blank' }, icon('file-clock'),
        `Версия ${v.n}: ${v.filename}${v.total ? ` · ${v.found}/${v.total}` : ''}`))) : null;
    const m = modal({ title: 'История заявки', wide: true, body: [h('ul', { class: 'timeline' }, ...items), versions],
      actions: [h('button', { class: 'btn', onclick: () => m.close() }, 'Закрыть')] });
  }

  function pickReplacement() {
    const input = h('input', { type: 'file', accept: '.pdf,.png,.jpg,.jpeg', hidden: true });
    input.addEventListener('change', async () => {
      if (!input.files[0]) return;
      const form = new FormData();
      form.append('file', input.files[0], input.files[0].name);
      try { doc = await api(`/api/documents/${slug}/replace`, { method: 'POST', form }); info('Файл заменён', 'Проверяем новую версию — это займёт несколько секунд.'); load(); }
      catch (e) { showError(e); }
    });
    document.body.append(input); input.click(); setTimeout(() => input.remove(), 60000);
  }

  async function decide(decision, comment = null) {
    try {
      doc = await api(`/api/documents/${slug}/approve`, { method: 'POST', body: { decision, comment } });
      draw();
      decision === 'approved' ? ok('Документ одобрен', 'Студент увидит решение в своей заявке.')
        : decision === 'returned' ? info('Документ возвращён', 'Студент увидит ваш комментарий.') : info('Решение отменено');
    } catch (e) { showError(e); }
  }

  async function remove() {
    if (!confirm(`Удалить «${doc.filename}»? Это действие нельзя отменить.`)) return;
    try { await api(`/api/documents/${slug}`, { method: 'DELETE' }); ok('Документ удалён'); navigate('/history'); } catch (e) { showError(e); }
  }

  const onUpdated = (e) => { if (e.detail.slug === slug && doc?.status !== 'done') load(true); };
  window.addEventListener('document-updated', onUpdated);
  const regionsPoll = setInterval(async () => {
    if (disposed || !doc || doc.status !== 'done' || doc.regions?.status !== 'pending') return;
    try { const next = await api(`/api/documents/${slug}`); if (next.regions?.status !== 'pending') { doc.regions = next.regions; if (!$('.composer textarea:focus', root)) draw(); } } catch {}
  }, 2000);
  await load(true);
  return () => { disposed = true; resizeObserver?.disconnect(); clearInterval(pollTimer); clearInterval(regionsPoll); window.removeEventListener('document-updated', onUpdated); chat?.dispose?.(); };
}
