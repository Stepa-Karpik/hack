// Live camera. In the browser, ten times a second: brightness, glare, sharpness and the shift of the picture against the
// frame that was last recognised (so the field boxes follow a shaking hand). Every ~2-3 s the sharpest recent frame goes to
// the recognition engine; the photo itself is taken at the full sensor resolution.
import { h, icon, refreshIcons, api, showError, LABELS, displayValue } from '../ui.js';
import { uploadFiles } from '../main.js';

const GW = 64, GH = 48;          // grey thumbnail for motion / shift estimation
const SHIFT = 8;                 // search radius of the shift, thumbnail pixels
const LIVE_SIDE = 1920;          // frames sent for live recognition

export async function render(app) {
  let stream = null, track = null, disposed = false, last = null, lastAt = 0, busy = false;
  let prev = null, motion = 0, movingSince = 0, best = null, scanGray = null, shift = { x: 0, y: 0, ok: true };
  const video = h('video', { class: 'cam-video', autoplay: true, playsinline: true, muted: true });
  const overlay = h('canvas', { class: 'cam-overlay' });
  const hints = h('div', { class: 'cam-hints' });
  const side = h('div', { class: 'cam-side card' });
  const shoot = h('button', { class: 'btn primary lg', disabled: true, onclick: capture }, icon('camera'), 'Снять и проверить');
  const native = h('input', { type: 'file', accept: 'image/*', capture: 'environment', hidden: true });
  native.addEventListener('change', () => { if (native.files[0]) { cleanup(); uploadFiles([native.files[0]], last?.document_type || 'auto', { open: true }); } });
  const nativeBtn = h('button', { class: 'btn lg cam-native', onclick: () => native.click(), title: 'Откроет приложение камеры: фото в полном разрешении' },
    icon('smartphone'), 'Фото камерой телефона');
  app.append(h('div', { class: 'page wide' },
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Съёмка документа'),
      h('p', { class: 'muted' }, 'Наведите камеру на лист: поля подсветятся прямо на видео. Держите лист целиком в кадре, при ровном свете.')),
      h('a', { class: 'btn', href: '/', 'data-link': '' }, icon('x'), 'Закрыть')),
    h('div', { class: 'cam-layout' },
      h('div', { class: 'cam-stage' }, video, overlay, hints, h('div', { class: 'cam-actions' }, shoot, nativeBtn)), side), native));
  drawSide();
  refreshIcons();

  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('insecure');
    // the largest picture the camera gives: text on an A4 sheet needs ~1500+ px across the page
    stream = await navigator.mediaDevices.getUserMedia({ audio: false,
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 3840 }, height: { ideal: 2160 } } });
    track = stream.getVideoTracks()[0];
    try { await track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch { /* not every camera */ }
    video.muted = true;  // the property, not only the attribute: autoplay policies check it
    video.srcObject = stream;
    try { await video.play(); } catch { /* autoplay blocked until a tap: the stream still plays on interaction */ }
    video.addEventListener('click', () => video.play().catch(() => {}));
    shoot.disabled = false;
  } catch {
    side.replaceChildren(h('div', { class: 'empty' }, icon('camera-off'), h('h2', {}, 'Камера недоступна'),
      h('p', { class: 'muted' }, 'Разрешите доступ к камере в браузере (сайт должен открываться по https) — или сфотографируйте документ приложением камеры.'),
      h('button', { class: 'btn primary', style: { marginTop: '12px' }, onclick: () => native.click() }, icon('smartphone'), 'Фото камерой телефона')));
    refreshIcons();
    return () => {};
  }

  // ---- 10 times a second, in the browser
  const small = document.createElement('canvas'); small.width = GW; small.height = GH;
  const sctx = small.getContext('2d', { willReadFrequently: true });
  const big = document.createElement('canvas'); big.width = 192; big.height = 144;
  const bctx = big.getContext('2d', { willReadFrequently: true });

  function grey(ctx, w, hgt) {
    const d = ctx.getImageData(0, 0, w, hgt).data, g = new Float32Array(w * hgt);
    for (let i = 0, j = 0; i < d.length; i += 4, j++) g[j] = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
    return g;
  }

  // shift (dx, dy) of the current thumbnail against the reference: minimum mean absolute difference over a small window
  function estimateShift(ref, cur) {
    let bestErr = Infinity, bx = 0, by = 0;
    for (let dy = -SHIFT; dy <= SHIFT; dy++) for (let dx = -SHIFT; dx <= SHIFT; dx++) {
      let err = 0, n = 0;
      for (let y = SHIFT; y < GH - SHIFT; y += 2) for (let x = SHIFT; x < GW - SHIFT; x += 2) {
        err += Math.abs(cur[(y + dy) * GW + x + dx] - ref[y * GW + x]); n++;
      }
      err /= n;
      if (err < bestErr) { bestErr = err; bx = dx; by = dy; }
    }
    return { x: bx / GW, y: by / GH, ok: bestErr < 18 };  // a large residual: another scene, the boxes are hidden
  }

  let measuring = false;
  async function measure() {
    if (!video.videoWidth || disposed || measuring) return;
    measuring = true;
    try { await measureFrame(); } finally { measuring = false; }
  }

  async function measureFrame() {
    sctx.drawImage(video, 0, 0, GW, GH);
    const g = grey(sctx, GW, GH);
    bctx.drawImage(video, 0, 0, 192, 144);
    const gb = grey(bctx, 192, 144);
    let sum = 0, glare = 0, paper = 0;
    for (const v of gb) { sum += v; if (v > 250) glare++; else if (v > 150) paper++; }
    const mean = sum / gb.length;
    let lap = 0, lapSq = 0, n = 0;
    for (let y = 1; y < 143; y++) for (let x = 1; x < 191; x++) {
      const k = y * 192 + x, v = 4 * gb[k] - gb[k - 1] - gb[k + 1] - gb[k - 192] - gb[k + 192];
      lap += v; lapSq += v * v; n++;
    }
    const sharp = lapSq / n - (lap / n) ** 2;
    if (prev) {  // smoothed frame-to-frame change: hand tremor stays low, a sweep of the camera is high
      let diff = 0; for (let k = 0; k < g.length; k++) diff += Math.abs(g[k] - prev[k]);
      motion = 0.7 * motion + 0.3 * diff / g.length;
    }
    prev = g;
    movingSince = motion > 14 ? (movingSince || Date.now()) : 0;
    if (scanGray) shift = estimateShift(scanGray, g);
    // the sharpest frame of the last second is the one recognised next
    if (!best || sharp > best.sharp || Date.now() - best.at > 1000) {
      try {
        const bitmap = await createImageBitmap(video);
        best?.bitmap.close?.();
        best = { bitmap, sharp, at: Date.now(), gray: g };
      } catch { /* the frame is not ready */ }
    }

    const issues = [];
    if (mean < 70) issues.push(['moon', 'Темно — добавьте света']);
    // a glare is a burnt-out spot on otherwise grey-white paper; an evenly white sheet is not one
    if (glare / gb.length > 0.03 && paper > glare * 1.5) issues.push(['sun', 'Блик — наклоните лист или уберите вспышку']);
    if (sharp < 40 && !movingSince) issues.push(['focus', 'Нерезко — дайте камере сфокусироваться']);
    if (movingSince && Date.now() - movingSince > 1200) issues.push(['move', 'Камера движется — задержите её на секунду']);
    const fresh = last && Date.now() - lastAt < 8000;
    if (fresh && last.sheet_share != null && last.sheet_share < 0.4) issues.push(['zoom-in', 'Поднесите ближе — лист должен занимать почти весь кадр']);
    if (fresh && last.readable === false) issues.push(['scan-eye', 'Текст читается плохо — ближе, ровнее и без бликов']);
    hints.replaceChildren(...(issues.length ? issues.map(([i, t]) => h('div', { class: 'cam-hint warn' }, icon(i), t))
      : [h('div', { class: 'cam-hint ok' }, icon('circle-check'), fresh && last.document_type ? 'Документ в кадре — можно снимать' : 'Хорошее качество кадра')]));
    refreshIcons();
    drawOverlay();
  }
  const qTimer = setInterval(measure, 100);

  // ---- recognition of the sharpest recent frame, one request at a time
  async function scanLoop() {
    while (!disposed) {
      if (!busy && best) {
        busy = true;
        const frame = best;
        try {
          const blob = await toBlob(frame.bitmap, LIVE_SIDE, 0.9);
          const form = new FormData(); form.append('frame', blob, 'frame.jpg');
          const result = await api('/api/live/scan', { method: 'POST', form });
          if (!disposed) { last = result; lastAt = Date.now(); scanGray = frame.gray; shift = { x: 0, y: 0, ok: true }; drawSide(); drawOverlay(); }
        } catch { /* keep the camera running */ }
        busy = false;
      }
      await new Promise((r) => setTimeout(r, 300));
    }
  }
  scanLoop();

  function toBlob(source, maxSide, q) {
    const w = source.width || source.videoWidth, hgt = source.height || source.videoHeight;
    const s = Math.min(1, maxSide / Math.max(w, hgt));
    const c = document.createElement('canvas'); c.width = Math.round(w * s); c.height = Math.round(hgt * s);
    c.getContext('2d').drawImage(source, 0, 0, c.width, c.height);
    return new Promise((resolve) => c.toBlob(resolve, 'image/jpeg', q));
  }

  function drawOverlay() {
    const box = video.getBoundingClientRect();
    overlay.width = box.width * devicePixelRatio; overlay.height = box.height * devicePixelRatio;
    const ctx = overlay.getContext('2d');
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    if (!last || !shift.ok || Date.now() - lastAt > 8000) return;
    // the video is letterboxed (object-fit: contain): frame coordinates -> the visible picture, moved with the camera
    const vr = video.videoWidth / video.videoHeight, br = box.width / box.height;
    const w = vr > br ? box.width : box.height * vr, hh = vr > br ? box.width / vr : box.height;
    const ox = (box.width - w) / 2, oy = (box.height - hh) / 2, k = devicePixelRatio;
    const P = ([x, y]) => [(ox + (x + shift.x) * w) * k, (oy + (y + shift.y) * hh) * k];
    const age = (Date.now() - lastAt) / 8000;
    ctx.globalAlpha = Math.max(0.35, 1 - age * age);
    const poly = (pts, stroke, fill, dash = []) => {
      ctx.beginPath(); pts.map(P).forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath();
      ctx.setLineDash(dash.map((v) => v * k)); ctx.lineWidth = 2 * k; ctx.strokeStyle = stroke; ctx.fillStyle = fill; ctx.fill(); ctx.stroke();
    };
    if (last.sheet) poly(last.sheet, '#7c6cff', 'rgba(124,108,255,0.06)', [10, 6]);
    for (const r of last.regions) {
      const missing = r.kind === 'missing';
      poly(r.quad, missing ? '#f2555a' : '#3ecf8e', missing ? 'rgba(242,85,90,0.12)' : 'rgba(62,207,142,0.14)', missing ? [6, 4] : []);
      // the label sits to the right of the box (form lines are dense; above it would cover the previous line), sized to
      // the line; on a small preview (a phone) only the boxes are drawn and the values are listed under the video
      const [rx, ry] = P(r.quad[1]), [, by] = P(r.quad[2]);
      const line = (by - ry) / k;
      if (line < 10 && !missing) continue;
      const size = Math.max(10, Math.min(13, line * 0.9));
      ctx.font = `600 ${size * k}px Inter, system-ui, sans-serif`;
      const label = missing ? `нужна ${r.field === 'seal_present' ? 'печать' : 'подпись'}` : (LABELS[r.field] || r.field);
      const tw = ctx.measureText(label).width + 10 * k, lh = (size + 5) * k;
      const lx = Math.min(rx + 6 * k, overlay.width - tw - 4 * k), ly = (ry + by) / 2 - lh / 2;
      ctx.setLineDash([]); ctx.fillStyle = missing ? '#f2555a' : '#1f9d6a';
      ctx.beginPath(); ctx.roundRect ? ctx.roundRect(lx, ly, tw, lh, 4 * k) : ctx.rect(lx, ly, tw, lh); ctx.fill();
      ctx.fillStyle = '#fff'; ctx.textBaseline = 'middle'; ctx.fillText(label, lx + 5 * k, ly + lh / 2 + 0.5 * k);
    }
    ctx.globalAlpha = 1;
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
      h('div', { class: 'subtle', style: { fontSize: '12px', marginTop: '10px', lineHeight: 1.5 } },
        (last ? `Кадр разобран за ${String(last.seconds?.toFixed(1)).replace('.', ',')} с. ` : '')
        + 'Снимок для проверки делается в полном разрешении камеры, а не из видео.')].filter(Boolean));
    refreshIcons();
  }

  // full-resolution photo: ImageCapture (sensor still, e.g. 4000x3000) where available, else the largest video frame
  async function photo() {
    if (window.ImageCapture && track) {
      try {
        const capture = new ImageCapture(track);
        let settings = {};
        try {
          const caps = await capture.getPhotoCapabilities();
          settings = { imageWidth: caps.imageWidth?.max, imageHeight: caps.imageHeight?.max };
        } catch { /* defaults */ }
        const blob = await capture.takePhoto(settings);
        if (blob && blob.size > 50000) return blob;
      } catch { /* fall back to the video frame */ }
    }
    return toBlob(video, 8000, 0.95);
  }

  async function capture() {
    shoot.disabled = true;
    try {
      const blob = await photo();
      const name = `Снимок ${new Date().toLocaleString('ru-RU').replace(/[/:]/g, '-')}.jpg`;
      cleanup();
      await uploadFiles([new File([blob], name, { type: 'image/jpeg' })], last?.document_type || 'auto', { open: true });
    } catch (e) { shoot.disabled = false; showError(e); }
  }

  function cleanup() {
    if (disposed) return;
    disposed = true; clearInterval(qTimer);
    best?.bitmap.close?.();
    stream?.getTracks().forEach((t) => t.stop());
  }
  return cleanup;
}
