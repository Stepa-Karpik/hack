// Document editor: place one's own signature (or the deanery seal), add text, white-out — with a ghost preview under the cursor.
// Saving creates a new version of the same application; the history keeps the original and marks the edit.
import { h, icon, refreshIcons, api, showError, ok, info } from '../ui.js';
import { state, navigate, isStaff } from '../main.js';

const loadImage = (src) => new Promise((resolve, reject) => { const i = new Image(); i.onload = () => resolve(i); i.onerror = reject; i.src = src; });

export async function render(app, slug) {
  let doc;
  try { doc = await api(`/api/documents/${slug}`); } catch (e) { showError(e); return navigate('/history', true); }
  if (!doc.can?.edit) { info('Редактор недоступен', 'Документ можно изменить в черновике или после возврата из деканата.'); return navigate('/check/' + slug, true); }
  const staff = isStaff() && !!doc.owner;
  const page = await loadImage(`/api/documents/${slug}/page.png?v=${doc.version}`);
  const W = page.naturalWidth, H = page.naturalHeight;
  const stamps = {};
  if (state.user.has_signature) stamps.signature = await loadImage(`/api/me/marks/signature?t=${Date.now()}`);
  if (isStaff() && state.user.has_seal) stamps.seal = await loadImage(`/api/me/marks/seal?t=${Date.now()}`);

  const ops = [];
  let tool = stamps.signature ? 'signature' : 'text', scale = 1, drag = null, hover = null;
  const canvas = h('canvas', { class: 'editor-canvas', width: W, height: H });
  const ghost = h('canvas', { class: 'editor-ghost', width: W, height: H });
  const ctx = canvas.getContext('2d'), gctx = ghost.getContext('2d');
  const textInput = h('input', { class: 'input', placeholder: 'Текст, например «по семейным обстоятельствам»', style: { height: '32px', maxWidth: '300px' } });
  const size = h('input', { type: 'range', min: '40', max: '220', value: '100', style: { width: '120px' } });

  const stampSize = (kind) => {
    const img = stamps[kind];
    const base = (kind === 'seal' ? 0.2 : 0.2) * W * size.value / 100;
    return [base, base * img.naturalHeight / img.naturalWidth];
  };
  function drawOp(c, op, alpha = 1) {
    c.save(); c.globalAlpha = alpha;
    if (op.type === 'image') {
      c.globalCompositeOperation = 'multiply';  // ink over paper, like a real pen or stamp
      c.drawImage(stamps[op.kind], op.x, op.y, op.w, op.h);
    } else if (op.type === 'text') {
      c.fillStyle = '#111'; c.font = `${op.size}px "Times New Roman", serif`; c.textBaseline = 'alphabetic'; c.fillText(op.text, op.x, op.y);
    } else if (op.type === 'rect') {
      c.fillStyle = '#fff'; c.fillRect(op.x, op.y, op.w, op.h);
    }
    c.restore();
  }
  function redraw() {
    ctx.clearRect(0, 0, W, H); ctx.drawImage(page, 0, 0, W, H);
    for (const op of ops) drawOp(ctx, op);
    undoBtn.disabled = !ops.length; saveBtn.disabled = !ops.length;
  }
  function pendingOp(x, y) {
    if (tool === 'signature' || tool === 'seal') {
      if (!stamps[tool]) return null;
      const [w, hgt] = stampSize(tool);
      return { type: 'image', kind: tool, x: x - w / 2, y: y - hgt / 2, w, h: hgt };
    }
    if (tool === 'text') {
      const text = textInput.value.trim();
      return text ? { type: 'text', text, x, y, size: Math.round(0.018 * W * size.value / 100) } : null;
    }
    if (tool === 'rect' && drag) return { type: 'rect', x: Math.min(drag.x, x), y: Math.min(drag.y, y), w: Math.abs(x - drag.x), h: Math.abs(y - drag.y) };
    return null;
  }
  function drawGhost() {
    gctx.clearRect(0, 0, W, H);
    if (!hover) return;
    const op = pendingOp(hover.x, hover.y);
    if (op) {
      drawOp(gctx, op, op.type === 'rect' ? 0.9 : 0.55);  // the ghost: where it will land
      gctx.save(); gctx.strokeStyle = '#7c6cff'; gctx.lineWidth = Math.max(2, W / 600); gctx.setLineDash([10, 8]);
      if (op.type === 'image' || op.type === 'rect') gctx.strokeRect(op.x, op.y, op.w, op.h);
      gctx.restore();
    }
  }
  const at = (e) => { const r = ghost.getBoundingClientRect(); return { x: (e.clientX - r.left) * W / r.width, y: (e.clientY - r.top) * H / r.height }; };
  ghost.addEventListener('pointermove', (e) => { hover = at(e); drawGhost(); });
  ghost.addEventListener('pointerleave', () => { hover = null; if (!drag) drawGhost(); });
  ghost.addEventListener('pointerdown', (e) => {
    const p = at(e);
    if (tool === 'rect') { drag = p; ghost.setPointerCapture(e.pointerId); return; }
    const op = pendingOp(p.x, p.y);
    if (!op) return showError({ title: tool === 'text' ? 'Введите текст' : 'Нечего ставить', detail: tool === 'text' ? 'Напишите текст в поле на панели.' : '' });
    ops.push({ ...op, label: tool === 'signature' ? 'подпись' : tool === 'seal' ? 'печать деканата' : `текст «${op.text}»` });
    redraw();
  });
  ghost.addEventListener('pointerup', (e) => {
    if (tool !== 'rect' || !drag) return;
    const op = pendingOp(at(e).x, at(e).y); drag = null;
    if (op && op.w > 4 && op.h > 4) { ops.push({ ...op, label: 'закрашена область' }); redraw(); }
    drawGhost();
  });

  const toolBtn = (key, iconName, label, disabled = false, title = '') => {
    const b = h('button', { class: 'btn sm' + (tool === key ? ' primary' : ''), disabled, title, onclick: () => { tool = key; drawToolbar(); drawGhost(); } }, icon(iconName), label);
    return b;
  };
  const undoBtn = h('button', { class: 'btn sm', onclick: () => { ops.pop(); redraw(); } }, icon('undo-2'), 'Отменить');
  const saveBtn = h('button', { class: 'btn primary', onclick: save }, icon('save'), 'Сохранить новую версию');
  const toolbar = h('div', { class: 'editor-toolbar' });
  function drawToolbar() {
    toolbar.replaceChildren(...[
      toolBtn('signature', 'signature', 'Моя подпись', !stamps.signature, stamps.signature ? '' : 'Сначала нарисуйте или загрузите подпись в профиле'),
      isStaff() ? toolBtn('seal', 'stamp', 'Печать деканата', !stamps.seal, stamps.seal ? '' : 'Загрузите печать в профиле') : null,
      toolBtn('text', 'type', 'Текст'), toolBtn('rect', 'eraser', 'Закрасить'),
      tool === 'text' ? textInput : null,
      h('label', { class: 'row', style: { gap: '6px', fontSize: '12.5px', color: 'var(--text-2)' } }, 'Размер', size),
      h('div', { class: 'grow' }), undoBtn].filter(Boolean));
    refreshIcons();
  }
  size.addEventListener('input', drawGhost);
  textInput.addEventListener('input', drawGhost);

  async function save() {
    saveBtn.disabled = true;
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
    const form = new FormData();
    form.append('file', blob, 'edited.png');
    form.append('source', 'editor');
    form.append('ops', ops.map((o) => o.label).join('; '));
    try {
      await api(`/api/documents/${slug}/replace`, { method: 'POST', form });
      ok('Сохранено как новая версия', staff ? 'Документ проверяется заново.' : 'Документ проверяется заново — затем отправьте его в деканат.');
      navigate('/check/' + slug);
    } catch (e) { saveBtn.disabled = false; showError(e); }
  }

  drawToolbar(); redraw();
  const missingSign = !stamps.signature ? h('div', { class: 'verdict info', style: { margin: '0 0 12px' } }, h('div', { class: 'verdict-title' }, icon('signature'), 'Подписи ещё нет'),
    h('div', { class: 'muted', style: { fontSize: '13px' } }, 'Нарисуйте свою подпись в профиле — потом её можно ставить на документы в один клик. ',
      h('a', { href: '/profile/marks', 'data-link': '' }, 'Перейти в профиль'))) : null;
  app.append(h('div', { class: 'page wide' },
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Редактор документа'),
      h('p', { class: 'muted' }, staff ? 'Поставьте электронную печать или подпись деканата. Изменение сохранится как новая версия заявки.'
        : 'Ставьте только свою подпись. Изменение сохранится как новая версия: деканат увидит, что документ правился в редакторе, и сможет открыть оригинал.')),
      h('div', { class: 'row', style: { gap: '8px' } }, h('a', { class: 'btn', href: '/check/' + slug, 'data-link': '' }, 'Отмена'), saveBtn)),
    missingSign, toolbar,
    h('div', { class: 'editor-stage' }, h('div', { class: 'editor-sheet', style: { aspectRatio: `${W} / ${H}` } }, canvas, ghost))));
  refreshIcons();
}
