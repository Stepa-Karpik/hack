// Live camera: quality hints computed in the browser several times a second, and every ~2-3 s a frame goes to the
// same recognition engine — found fields are drawn over the video before the photo is taken.
import { h, icon, refreshIcons, api, showError, LABELS, displayValue } from '../ui.js';
import { uploadFiles } from '../main.js';

export async function render(app) {
  let stream = null, disposed = false, last = null, lastAt = 0, prevSmall = null, motion = 0, busy = false;
  const video = h('video', { class: 'cam-video', autoplay: true, playsinline: true, muted: true });
  const overlay = h('canvas', { class: 'cam-overlay' });
  const hints = h('div', { class: 'cam-hints' });
  const side = h('div', { class: 'cam-side card' });
  const shoot = h('button', { class: 'btn primary lg cam-shoot', disabled: true, onclick: capture }, icon('camera'), 'Снять и проверить');
  const fallback = h('input', { type: 'file', accept: 'image/*', capture: 'environment', hidden: true });
  fallback.addEventListener('change', () => { if (fallback.files[0]) uploadFiles([fallback.files[0]], 'auto', { open: true }); });
  app.append(h('div', { class: 'page wide' },
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Съёмка документа'),
      h('p', { class: 'muted' }, 'Наведите камеру на документ: сервис подскажет, если темно или смазано, и прямо на видео покажет найденные поля.')),
      h('a', { class: 'btn', href: '/', 'data-link': '' }, icon('x'), 'Закрыть')),
    h('div', { class: 'cam-layout' }, h('div', { class: 'cam-stage' }, video, overlay, hints, shoot), side), fallback));
  drawSide();
  refreshIcons();

  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('insecure');
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false });
    video.srcObject = stream;
    await video.play();
    shoot.disabled = false;
  } catch {
    side.replaceChildren(h('div', { class: 'empty' }, icon('camera-off'), h('h2', {}, 'Камера недоступна'),
      h('p', { class: 'muted' }, 'Разрешите доступ к камере в браузере (сайт должен открываться по https или с localhost) — или выберите фото.'),
      h('button', { class: 'btn', style: { marginTop: '12px' }, onclick: () => fallback.click() }, icon('image'), 'Выбрать фото')));
    refreshIcons();
    return () => {};
  }

  // ---- quality in the browser (every 250 ms): brightness, glare, sharpness, motion
  const small = document.createElement('canvas'); small.width = 160; small.height = 90;
  const sctx = small.getContext('2d', { willReadFrequently: true });
  let quality = { ok: false, issues: [] };
  function measure() {
    if (!video.videoWidth) return;
    sctx.drawImage(video, 0, 0, 160, 90);
    const d = sctx.getImageData(0, 0, 160, 90).data;
    const gray = new Float32Array(160 * 90);
    let sum = 0, glare = 0, paper = 0;
    for (let i = 0, j = 0; i < d.length; i += 4, j++) {
      const g = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]; gray[j] = g; sum += g;
      if (g > 250) glare++; else if (g > 150) paper++;
    }
    const mean = sum / gray.length;
    let lap = 0, lapSq = 0, n = 0;
    for (let y = 1; y < 89; y++) for (let x = 1; x < 159; x++) {
      const k = y * 160 + x;
      const v = 4 * gray[k] - gray[k - 1] - gray[k + 1] - gray[k - 160] - gray[k + 160];
      lap += v; lapSq += v * v; n++;
    }
    const sharp = lapSq / n - (lap / n) ** 2;
    if (prevSmall) { let diff = 0; for (let k = 0; k < gray.length; k++) diff += Math.abs(gray[k] - prevSmall[k]); motion = diff / gray.length; }
    prevSmall = gray;
    const issues = [];
    if (mean < 70) issues.push(['moon', 'Темно — добавьте света']);
    // a glare is a burnt-out spot on otherwise grey-white paper; an evenly white sheet (a screen, a scan) is not one
    if (glare / gray.length > 0.03 && paper > glare * 1.5) issues.push(['sun', 'Блик — наклоните лист или уберите вспышку']);
    if (sharp < 60) issues.push(['focus', 'Нерезко — поднесите ближе и дайте камере сфокусироваться']);
    if (motion > 9) issues.push(['move', 'Держите камеру неподвижно']);
    quality = { ok: !issues.length, issues };
    hints.replaceChildren(...(issues.length ? issues.map(([i, t]) => h('div', { class: 'cam-hint warn' }, icon(i), t))
      : [h('div', { class: 'cam-hint ok' }, icon('circle-check'), last?.document_type ? 'Документ в кадре — можно снимать' : 'Хорошее качество кадра')]));
    refreshIcons();
    drawOverlay();
  }
  const qTimer = setInterval(measure, 250);

  // ---- recognition of a frame every ~2-3 s (the next request starts when the previous one is answered)
  async function scanLoop() {
    while (!disposed) {
      if (!busy && video.videoWidth && motion < 9) {
        busy = true;
        try {
          const blob = await frameBlob(1280, 0.85);
          const form = new FormData(); form.append('frame', blob, 'frame.jpg');
          last = await api('/api/live/scan', { method: 'POST', form }); lastAt = Date.now();
          drawSide(); drawOverlay();
        } catch { /* keep the camera running */ }
        busy = false;
      }
      await new Promise((r) => setTimeout(r, 400));
    }
  }
  scanLoop();

  function frameBlob(maxSide, q) {
    const s = Math.min(1, maxSide / Math.max(video.videoWidth, video.videoHeight));
    const c = document.createElement('canvas'); c.width = Math.round(video.videoWidth * s); c.height = Math.round(video.videoHeight * s);
    c.getContext('2d').drawImage(video, 0, 0, c.width, c.height);
    return new Promise((resolve) => c.toBlob(resolve, 'image/jpeg', q));
  }

  function drawOverlay() {
    const box = video.getBoundingClientRect();
    overlay.width = box.width * devicePixelRatio; overlay.height = box.height * devicePixelRatio;
    const ctx = overlay.getContext('2d');
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    if (!last || motion > 9 || Date.now() - lastAt > 6000) return;  // stale boxes would point at the wrong place
    // the video is letterboxed (object-fit: contain): map frame coordinates into the visible picture
    const vr = video.videoWidth / video.videoHeight, br = box.width / box.height;
    const w = vr > br ? box.width : box.height * vr, hh = vr > br ? box.width / vr : box.height;
    const ox = (box.width - w) / 2, oy = (box.height - hh) / 2, k = devicePixelRatio;
    const P = ([x, y]) => [(ox + x * w) * k, (oy + y * hh) * k];
    const poly = (pts, stroke, fill, dash = []) => {
      ctx.beginPath(); pts.map(P).forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath();
      ctx.setLineDash(dash.map((v) => v * k)); ctx.lineWidth = 2 * k; ctx.strokeStyle = stroke; ctx.fillStyle = fill; ctx.fill(); ctx.stroke();
    };
    if (last.sheet) poly(last.sheet, '#7c6cff', 'rgba(124,108,255,0.06)', [10, 6]);
    ctx.font = `${12 * k}px Inter, system-ui, sans-serif`;
    for (const r of last.regions) {
      const missing = r.kind === 'missing';
      poly(r.quad, missing ? '#f2555a' : '#3ecf8e', missing ? 'rgba(242,85,90,0.12)' : 'rgba(62,207,142,0.12)', missing ? [6, 4] : []);
      const [x, y] = P(r.quad[0]);
      const label = missing ? `нужна ${r.field === 'seal_present' ? 'печать' : 'подпись'}` : (LABELS[r.field] || r.field);
      const tw = ctx.measureText(label).width + 10 * k;
      ctx.setLineDash([]); ctx.fillStyle = missing ? '#f2555a' : '#1f9d6a'; ctx.fillRect(x, y - 18 * k, tw, 16 * k);
      ctx.fillStyle = '#fff'; ctx.fillText(label, x + 5 * k, y - 6 * k);
    }
  }

  function drawSide() {
    const fields = last ? Object.entries(last.fields) : [];
    side.replaceChildren(...[
      h('div', { class: 'cam-type' }, h('div', { class: 'subtle', style: { fontSize: '12px' } }, 'Тип документа'),
        h('div', { style: { fontWeight: 620, fontSize: '16px' } }, last?.type_name || (last ? 'Не определён — поднесите заголовок в кадр' : 'Ищем документ…'))),
      h('div', { class: 'cam-fields' }, ...(fields.length ? fields.map(([k, v]) => h('div', { class: 'cam-field' },
        h('span', { class: 'subtle' }, LABELS[k] || k), h('b', {}, displayValue(v))))
        : [h('div', { class: 'subtle', style: { padding: '8px 0' } }, 'Поля появятся, когда документ попадёт в кадр.')])),
      last?.missing?.length ? h('div', { class: 'verdict warn', style: { margin: '10px 0 0' } }, h('div', { class: 'verdict-title' }, icon('circle-alert'),
        'Пока не видно: ' + last.missing.map((k) => (LABELS[k] || k).toLowerCase()).join(', '))) : null,
      last ? h('div', { class: 'subtle', style: { fontSize: '12px', marginTop: '10px' } }, `Кадр разобран за ${String(last.seconds?.toFixed(1)).replace('.', ',')} с`) : null].filter(Boolean));
    refreshIcons();
  }

  async function capture() {
    shoot.disabled = true;
    try {
      const blob = await frameBlob(4000, 0.93);
      const name = `Снимок ${new Date().toLocaleString('ru-RU').replace(/[/:]/g, '-')}.jpg`;
      cleanup();
      await uploadFiles([new File([blob], name, { type: 'image/jpeg' })], last?.document_type || 'auto', { open: true });
    } catch (e) { shoot.disabled = false; showError(e); }
  }

  function cleanup() {
    disposed = true; clearInterval(qTimer);
    stream?.getTracks().forEach((t) => t.stop());
  }
  return cleanup;
}
