// Document type constructor (admin): a new type is described by its title phrases, labelled fields and required marks.
// No training: the CPU engine finds the printed labels in the recognised text and takes the value next to them.
import { h, icon, refreshIcons, api, showError, ok, info, TYPES, LABELS, modal } from '../ui.js';

const KIND_HINT = { text: 'любой текст после подписи', name: 'Фамилия Имя Отчество', date: '12.03.2026 или 12 марта 2026', number: '№ 15-07/226' };

export async function render(body) {
  const list = h('div', { class: 'list' });
  let kinds = { text: 'Текст', name: 'ФИО', date: 'Дата', number: 'Номер' };

  async function load(data) {
    try {
      const r = data || await api('/api/types');
      kinds = r.field_kinds || kinds;
      for (const t of r.types) { TYPES[t.key] = t.title; for (const f of t.fields) LABELS[f.key] = LABELS[f.key] || f.label; }
      list.replaceChildren(...r.types.map((t) => h('div', { class: 'item', style: { gridTemplateColumns: '32px minmax(0,1fr) auto' } },
        icon(t.builtin ? 'file-check-2' : 'file-plus-2'),
        h('div', {}, h('div', { class: 'item-title' }, t.title, t.builtin ? h('span', { class: 'chip', style: { marginLeft: '8px' } }, 'встроенный') : null),
          h('div', { class: 'item-meta' }, h('span', {}, t.fields.map((f) => f.label).join(' · ')))),
        t.builtin ? h('span') : h('div', { class: 'row', style: { gap: '6px' } },
          h('button', { class: 'btn sm', onclick: () => editor(t.config) }, icon('pencil'), 'Изменить'),
          h('button', { class: 'btn ghost sm danger', onclick: () => remove(t) }, 'Удалить')))));
      refreshIcons();
    } catch (e) { showError(e); }
  }

  async function remove(t) {
    const dlg = modal({ title: `Удалить тип «${t.title}»?`,
      body: [h('p', { class: 'muted' }, 'Уже загруженные документы этого типа останутся в истории, но новые перестанут распознаваться как этот тип.')],
      actions: [h('button', { class: 'btn', onclick: () => dlg.close() }, 'Отмена'),
        h('button', { class: 'btn danger', onclick: async () => {
          try { const r = await api('/api/admin/types/' + t.key, { method: 'DELETE' }); delete TYPES[t.key]; dlg.close(); info('Тип удалён'); load(r); }
          catch (e) { showError(e); }
        } }, 'Удалить')] });
  }

  function editor(config = null) {
    const c = config || { title: '', keywords: [], fields: [{ label: '', variants: [], kind: 'text', required: true }], signature: true, seal: false, rule: '', rule_text: '' };
    const title = h('input', { class: 'input', value: c.title, placeholder: 'Например, «Справка о составе семьи»', maxlength: 120 });
    const keywords = h('input', { class: 'input', value: c.keywords.join('; '), placeholder: 'справка о составе семьи; состав семьи' });
    const rule = h('input', { class: 'input', value: c.rule || '', placeholder: '7.1', style: { maxWidth: '90px' } });
    const ruleText = h('input', { class: 'input', value: c.rule_text || '', placeholder: 'Текст пункта Положения (необязательно)' });
    const sign = h('input', { type: 'checkbox', checked: c.signature });
    const seal = h('input', { type: 'checkbox', checked: c.seal });
    const rows = h('div', { class: 'type-fields' });

    function fieldRow(f) {
      const label = h('input', { class: 'input', value: f.label, placeholder: 'Название поля, например «Номер справки»' });
      const variants = h('input', { class: 'input', value: (f.variants || []).filter((v) => v !== f.label).join('; '),
        placeholder: 'Как подписано в документе: номер; №' });
      const kind = h('select', { class: 'select' }, ...Object.entries(kinds).map(([k, l]) => h('option', { value: k, selected: k === f.kind }, l)));
      const required = h('input', { type: 'checkbox', checked: f.required !== false });
      const hint = h('div', { class: 'subtle', style: { fontSize: '12px' } }, 'Пример значения: ' + KIND_HINT[f.kind || 'text']);
      kind.addEventListener('change', () => { hint.textContent = 'Пример значения: ' + KIND_HINT[kind.value]; });
      const row = h('div', { class: 'type-field' },
        h('div', { class: 'type-field-main' }, label, variants, hint),
        h('div', { class: 'type-field-side' }, kind, h('label', { class: 'row', style: { gap: '6px', fontSize: '13px' } }, required, 'обязательно'),
          h('button', { class: 'btn ghost sm danger', title: 'Убрать поле', onclick: () => { row.remove(); } }, icon('trash-2'))));
      row.read = () => ({ label: label.value.trim(), kind: kind.value, required: required.checked,
        variants: [label.value, ...variants.value.split(';')].map((v) => v.trim()).filter(Boolean) });
      return row;
    }
    for (const f of c.fields) rows.append(fieldRow(f));
    const add = h('button', { class: 'btn sm', onclick: () => { rows.append(fieldRow({ label: '', kind: 'text', required: true })); refreshIcons(); } }, icon('plus'), 'Добавить поле');

    const save = h('button', { class: 'btn primary', onclick: async () => {
      const payload = { title: title.value, keywords: keywords.value.split(';').map((k) => k.trim()).filter(Boolean),
        fields: [...rows.children].map((r) => r.read()).filter((f) => f.label), signature: sign.checked, seal: seal.checked,
        rule: rule.value, rule_text: ruleText.value };
      save.disabled = true;
      try {
        const r = await api(config ? '/api/admin/types/' + config.key : '/api/admin/types', { method: config ? 'PUT' : 'POST', body: payload });
        dlg.close(); ok(config ? 'Тип обновлён' : 'Тип добавлен', 'Его можно выбрать при загрузке, а при автоопределении он узнаётся по заголовку.'); load(r);
      } catch (e) { save.disabled = false; showError(e); }
    } }, icon('save'), 'Сохранить');

    const labelled = (text, el, hint) => h('label', { class: 'field-group' }, h('span', { class: 'label' }, text), el, hint ? h('span', { class: 'subtle', style: { fontSize: '12px' } }, hint) : null);
    const dlg = modal({ title: config ? 'Тип документа' : 'Новый тип документа', wide: true,
      body: [h('div', { class: 'stack' },
        labelled('Название', title),
        labelled('Фразы из заголовка', keywords, 'Через «;». По ним документ узнаётся при автоопределении — берите слова, которые напечатаны в шапке.'),
        h('div', { class: 'section-title', style: { fontWeight: 600, marginTop: '6px' } }, 'Поля'),
        h('p', { class: 'muted', style: { fontSize: '13px', margin: 0 } }, 'Сервис ищет подпись поля в тексте и берёт значение справа от неё или строкой ниже. Добавьте варианты, если подпись бывает разной.'),
        rows, h('div', {}, add),
        h('div', { class: 'section-title', style: { fontWeight: 600, marginTop: '6px' } }, 'Отметки'),
        h('div', { class: 'row', style: { gap: '18px' } }, h('label', { class: 'row', style: { gap: '6px' } }, sign, 'Нужна подпись'),
          h('label', { class: 'row', style: { gap: '6px' } }, seal, 'Нужна печать')),
        h('div', { class: 'row', style: { gap: '10px', alignItems: 'flex-end' } }, labelled('Пункт Положения', rule), h('div', { class: 'grow' }, labelled('Текст пункта', ruleText))))],
      actions: [h('button', { class: 'btn', onclick: () => dlg.close() }, 'Отмена'), save] });
    refreshIcons();
  }

  body.append(h('div', { class: 'section' }, h('div', { class: 'row', style: { justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px' } },
      h('div', {}, h('h2', {}, 'Типы документов'),
        h('p', { class: 'muted', style: { marginTop: '4px', maxWidth: '560px' } },
          'Добавьте новый вид документа без обучения модели: укажите фразы из заголовка, поля с их подписями и обязательные отметки. ' +
          'Распознавание, проверка комплектности, рамки на странице и вопросы к документу заработают сразу.')),
      h('button', { class: 'btn primary', onclick: () => editor() }, icon('plus'), 'Новый тип'))),
    h('div', { class: 'section', style: { padding: '0' } }, list));
  await load();
}
