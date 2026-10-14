import { h, icon, refreshIcons, api, LABELS, showError, copy } from './ui.js';

const KIND = { found: ['check', 'ok', 'Найдено в документе'], text: ['scan-text', 'ok', 'Из текста документа'], computed: ['calculator', 'info', 'Вычислено'],
  absent: ['circle-off', 'warn', 'Нет в документе'], rule: ['scale', 'accent', 'По Положению'], clarify: ['circle-help', 'warn', 'Нужно уточнение'],
  out_of_scope: ['ban', '', 'Вне документа'] };
const STARTERS = { study_certificate: ['Всё ли в порядке со справкой?', 'Сколько длится обучение?', 'Когда выдана справка?'],
  academic_leave_application: ['Чего не хватает в заявлении?', 'Сколько длится отпуск?', 'Нужна ли печать на заявлении?'],
  internship_certificate: ['Всё ли в порядке со справкой?', 'Кто руководитель практики?', 'Сколько длилась практика?'] };

export function mountChat(pane, doc, { onSource }) {
  let busy = false, current = doc;
  const status = h('span', { class: 'subtle', style: { fontSize: '12px' } }, 'ИИ-ассистент · локально');
  const log = h('div', { class: 'pane-body', role: 'log', 'aria-live': 'polite' });
  const input = h('textarea', { class: 'input', rows: 1, placeholder: 'Спросите что угодно о документе…', maxlength: 2000 });
  const send = h('button', { class: 'btn primary icon', type: 'submit', title: 'Отправить' }, icon('arrow-up'));
  const chips = h('div', { class: 'followups' });
  const form = h('form', {}, input, send);
  pane.append(h('div', { class: 'pane-head' }, h('div', { class: 'grow' }, h('h2', {}, 'Ассистент'), status),
    h('button', { class: 'btn ghost icon sm', title: 'Очистить диалог', onclick: clear }, icon('eraser'))),
    log, h('div', { class: 'composer' }, chips, form));

  api('/api/health').then((s) => { status.textContent = s.assistant ? `ИИ-ассистент · ${s.model}` : 'Режим правил: языковая модель сейчас недоступна'; }).catch(() => {});

  function scroll() { requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; }); }
  function bubble(text, who) {
    const b = h('div', { class: 'bubble' }, text);
    const m = h('div', { class: 'msg ' + who }, b);
    log.append(m); scroll();
    return { m, b };
  }
  function intro() {
    const a = current.analysis;
    const ok = a.validation.status === 'document_ok';
    bubble((ok ? `Документ прочитан, все обязательные сведения на месте (${current.found} из ${current.total}).`
      : `Документ прочитан: найдено ${current.found} из ${current.total}. Не хватает: ${a.validation.missing_fields.map((k) => LABELS[k]).join(', ')}.`)
      + ' Спросите про сроки, ФИО или что делать дальше — отвечаю только по документу и Положению.', 'bot intro');
  }
  function finish(m, reply) {
    const [ic, tone, label] = KIND[reply.kind] || KIND.found;
    m.querySelector('.bubble').textContent = reply.answer;
    m.querySelector('.bubble').classList.remove('caret');
    m.querySelector('.kind')?.remove();
    m.prepend(h('span', { class: 'chip kind ' + tone, style: { justifySelf: 'start' } }, icon(ic), reply.kind_label || label));
    const tools = h('div', { class: 'msg-tools' });
    for (const s of reply.sources || []) {
      const key = s.startsWith('field:') ? s.slice(6) : null;
      tools.append(key ? h('button', { class: 'src', onclick: () => onSource?.(key) }, LABELS[key] || key) : h('span', { class: 'src' }, 'п. ' + s.slice(5)));
    }
    tools.append(h('button', { class: 'src', title: 'Копировать ответ', onclick: () => copy(reply.answer) }, icon('copy')));
    const e = reply.engine || {};
    tools.append(h('span', { title: e.type === 'llm' ? `Локальная модель ${e.model}; ответ сверен с документом` : 'Ответ движка правил' },
      e.type === 'llm' ? `${(e.seconds ?? 0).toFixed(1)} с` : 'правила'));
    if (e.guard_withdrawn) tools.append(h('span', { class: 'chip warn' }, 'черновик скрыт: не подтвердился документом'));
    m.append(tools);
    setFollowups(reply.followups || []);
    refreshIcons(); scroll();
  }
  function setFollowups(list) {
    chips.replaceChildren(...list.slice(0, 3).map((q) => h('button', { type: 'button', onclick: () => ask(q) }, q)));
  }
  function load() {
    log.replaceChildren();
    intro();
    for (const t of current.chat || []) {
      bubble(t.question, 'user');
      const { m } = bubble('', 'bot');
      finish(m, t.reply || { answer: t.answer, kind: t.kind, sources: [] });
    }
    if (!(current.chat || []).length) setFollowups(STARTERS[current.analysis.document_type] || []);
  }

  async function ask(q) {
    q = (q || '').trim();
    if (!q || busy) return;
    busy = true; send.disabled = true; input.value = ''; autosize();
    bubble(q, 'user');
    const { m, b } = bubble('', 'bot');
    b.classList.add('caret');
    chips.replaceChildren();
    let text = '';
    try {
      const response = await api(`/api/documents/${current.slug}/chat`, { method: 'POST', body: { question: q }, raw: true });
      if (!response.ok) { let d = {}; try { d = await response.json(); } catch {} throw Object.assign(new Error(), { title: d.message || 'Ассистент не ответил', detail: '' }); }
      const reader = response.body.getReader(), dec = new TextDecoder();
      let buf = '', final = null;
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
          if (!line) continue;
          const ev = JSON.parse(line);
          if (ev.type === 'kind') { const [ic, tone, label] = KIND[ev.kind] || KIND.found; m.querySelector('.kind')?.remove(); m.prepend(h('span', { class: 'chip kind ' + tone, style: { justifySelf: 'start' } }, icon(ic), ev.label || label)); refreshIcons(); }
          else if (ev.type === 'delta') { text += ev.text; b.textContent = text; scroll(); }
          else if (ev.type === 'final') final = ev.reply;
        }
      }
      if (!final) throw Object.assign(new Error(), { title: 'Ответ прервался', detail: 'Попробуйте ещё раз.' });
      finish(m, final);
      current.chat = [...(current.chat || []), { question: q, reply: final }];
    } catch (e) { m.remove(); showError(e); }
    finally { busy = false; send.disabled = false; input.focus(); }
  }
  async function clear() {
    try { await api(`/api/documents/${current.slug}/chat`, { method: 'DELETE' }); current.chat = []; load(); } catch (e) { showError(e); }
  }
  function autosize() { input.style.height = 'auto'; input.style.height = Math.min(140, input.scrollHeight) + 'px'; }
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(input.value); } });
  form.addEventListener('submit', (e) => { e.preventDefault(); ask(input.value); });
  load();
  refreshIcons();
  return { ask, update: (d) => { const chat = current.chat; current = d; current.chat = chat; }, dispose() {} };
}
