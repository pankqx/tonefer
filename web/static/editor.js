/* Photo editor for the Gallery: crop, turn, mirror, light, contrast and colour.
   The preview is drawn in the browser; the laptop then applies exactly the same steps to the
   full-size photo with Pillow, so the saved file keeps its full quality and its EXIF data. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const { toast } = window.T;
  const cv = $("edCanvas"), ctx = cv.getContext("2d"), frame = $("edFrame"), box = $("edCrop");
  const FULL = () => ({ x: 0, y: 0, w: 1, h: 1 });
  let img = null, item = null, done = null;
  let rot = 0, fh = false, fv = false, crop = FULL(), ratio = "free", drag = null, armed = 0;

  const turnedW = () => (rot % 2 ? img.naturalHeight : img.naturalWidth);
  const turnedH = () => (rot % 2 ? img.naturalWidth : img.naturalHeight);
  /** The chosen ratio as width/height in the 0..1 crop units (they are stretched by the photo's shape). */
  const unitRatio = () => (ratio === "free" ? null : ratio === "orig" ? 1 : Number(ratio) * turnedH() / turnedW());
  const isFull = () => crop.x < 1e-4 && crop.y < 1e-4 && crop.w > 0.9999 && crop.h > 0.9999;
  const val = (id) => Number($(id).value) / 100;

  function draw() {
    if (!img) return;
    const st = $("edStage"), W = turnedW(), H = turnedH();
    const scale = Math.min((st.clientWidth - 48) / W, (st.clientHeight - 48) / H, 1);
    const cw = Math.max(1, Math.round(W * scale)), ch = Math.max(1, Math.round(H * scale));
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    cv.width = Math.round(cw * dpr); cv.height = Math.round(ch * dpr);
    cv.style.width = cw + "px"; cv.style.height = ch + "px";
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.translate(cv.width / 2, cv.height / 2);
    ctx.scale(fh ? -1 : 1, fv ? -1 : 1);        // mirror after turning, like the laptop does
    ctx.rotate(rot * Math.PI / 2);
    const iw = (rot % 2 ? cv.height : cv.width), ih = (rot % 2 ? cv.width : cv.height);
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(img, -iw / 2, -ih / 2, iw, ih);
    filters();
    place();
  }
  function filters() {
    const b = val("edB"), c = val("edC"), s = val("edS");
    cv.style.filter = `brightness(${b}) contrast(${c}) saturate(${s})`;
    $("edBo").textContent = signed($("edB").value - 100);
    $("edCo").textContent = signed($("edC").value - 100);
    $("edSo").textContent = signed($("edS").value - 100);
  }
  const signed = (n) => (n > 0 ? "+" + n : String(n));
  function place() {
    Object.assign(box.style, { left: crop.x * 100 + "%", top: crop.y * 100 + "%", width: crop.w * 100 + "%", height: crop.h * 100 + "%" });
    const px = Math.round(crop.w * turnedW()), py = Math.round(crop.h * turnedH());
    $("edInfo").textContent = isFull() ? `${turnedW()} × ${turnedH()} · drag on the photo to crop` : `Crop ${px} × ${py}`;
  }

  // ---- crop by dragging ----
  const point = (e) => {
    const r = cv.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) };
  };
  function fromAnchor(a, p) {
    const rn = unitRatio(), dx = p.x - a.x, dy = p.y - a.y;
    let w = Math.abs(dx), h = Math.abs(dy);
    if (rn) { if (w / Math.max(h, 1e-6) > rn) w = h * rn; else h = w / rn; }
    const maxW = dx >= 0 ? 1 - a.x : a.x, maxH = dy >= 0 ? 1 - a.y : a.y;
    if (w > maxW) { w = maxW; if (rn) h = w / rn; }
    if (h > maxH) { h = maxH; if (rn) w = h * rn; }
    return { x: dx >= 0 ? a.x : a.x - w, y: dy >= 0 ? a.y : a.y - h, w, h };
  }
  frame.addEventListener("pointerdown", (e) => {
    if (!img || e.button !== 0) return;
    e.preventDefault();
    frame.setPointerCapture(e.pointerId);
    const p = point(e), hnd = e.target.dataset && e.target.dataset.h;
    const before = { ...crop };
    if (hnd) {
      const a = { x: hnd.includes("w") ? crop.x + crop.w : crop.x, y: hnd.includes("n") ? crop.y + crop.h : crop.y };
      drag = { mode: "size", a, before };
    } else if (e.target === box && !isFull()) {
      drag = { mode: "move", from: p, before };
    } else {
      drag = { mode: "size", a: p, before, fresh: true };
    }
    frame.classList.add("cropping");
  });
  frame.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const p = point(e);
    if (drag.mode === "move") {
      const b = drag.before;
      crop = { ...b, x: Math.min(1 - b.w, Math.max(0, b.x + p.x - drag.from.x)), y: Math.min(1 - b.h, Math.max(0, b.y + p.y - drag.from.y)) };
    } else {
      crop = fromAnchor(drag.a, p);
    }
    place();
  });
  const endDrag = () => {
    if (!drag) return;
    if (crop.w < 0.02 || crop.h < 0.02) crop = drag.fresh ? (isFullRect(drag.before) ? FULL() : drag.before) : drag.before;
    drag = null;
    frame.classList.remove("cropping");
    place();
  };
  const isFullRect = (c) => c.x < 1e-4 && c.y < 1e-4 && c.w > 0.9999 && c.h > 0.9999;
  frame.addEventListener("pointerup", endDrag);
  frame.addEventListener("pointercancel", endDrag);

  // ---- ratio, turn, mirror ----
  function fitRatio() {
    const rn = unitRatio();
    if (!rn) return;
    let w = 1, h = 1 / rn;
    if (h > 1) { h = 1; w = rn; }
    crop = { x: (1 - w) / 2, y: (1 - h) / 2, w, h };
  }
  $("edRatios").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    ratio = b.dataset.r;
    $("edRatios").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    if (ratio === "free") crop = FULL(); else fitRatio();
    place();
  });
  function turn(dir) {   // the crop turns with the photo
    const c = crop;
    crop = dir > 0 ? { x: 1 - c.y - c.h, y: c.x, w: c.h, h: c.w } : { x: c.y, y: 1 - c.x - c.w, w: c.h, h: c.w };
    // A mirrored photo turns the other way round internally, so the screen turns the way you clicked.
    const step = fh !== fv ? -dir : dir;
    rot = (rot + (step > 0 ? 1 : 3)) % 4;
    if (ratio !== "free" && ratio !== "orig") {   // a 4:3 crop turned is a 3:4 crop
      const inv = { "1.3333": "0.75", "0.75": "1.3333", "1.7778": "0.5625", "0.5625": "1.7778", "1": "1" }[ratio];
      ratio = inv || "free";
      $("edRatios").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.r === ratio)));
    }
    draw();
  }
  $("edRotR").onclick = () => turn(1);
  $("edRotL").onclick = () => turn(-1);
  $("edFlipH").onclick = () => { fh = !fh; crop = { ...crop, x: 1 - crop.x - crop.w }; draw(); };
  $("edFlipV").onclick = () => { fv = !fv; crop = { ...crop, y: 1 - crop.y - crop.h }; draw(); };
  ["edB", "edC", "edS"].forEach((id) => {
    $(id).addEventListener("input", filters);
    $(id).addEventListener("dblclick", () => { $(id).value = 100; filters(); });
  });

  // ---- open, save, close ----
  function reset() {
    rot = 0; fh = fv = false; crop = FULL(); ratio = "free";
    $("edRatios").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.r === "free")));
    ["edB", "edC", "edS"].forEach((id) => { $(id).value = 100; });
    disarm();
    draw();
  }
  function close() { $("ed").hidden = true; img = null; item = null; disarm(); }
  function disarm() { clearTimeout(armed); armed = 0; $("edReplace").textContent = "Replace original"; }
  const changed = () => rot || fh || fv || !isFull() || ["edB", "edC", "edS"].some((id) => Number($(id).value) !== 100);

  async function save(mode) {
    if (!changed()) return toast("Nothing changed yet");
    if (mode === "replace" && !armed) {
      $("edReplace").textContent = "Click again to replace";
      armed = setTimeout(disarm, 3500);
      return;
    }
    disarm();
    $("edBusy").hidden = false;
    ["edCopy", "edReplace", "edCancel", "edReset"].forEach((id) => { $(id).disabled = true; });
    const ops = { rotate: rot * 90, flipH: fh, flipV: fv, crop: isFull() ? null : crop, brightness: val("edB"), contrast: val("edC"), saturation: val("edS") };
    try {
      const r = await fetch("/desk/api/gallery/edit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: item.id, ops, mode }) });
      const d = await r.json().catch(() => ({ error: `the laptop answered ${r.status}` }));
      if (!r.ok || d.error) throw new Error(d.error || "Couldn't save");
      toast(mode === "copy" ? "Saved as a copy next to the original" : "Saved. The original is in the Trash.");
      const cb = done;
      close();
      if (cb) cb(d.id);
    } catch (err) {
      toast(err.message);
    } finally {
      $("edBusy").hidden = true;
      ["edCopy", "edReplace", "edCancel", "edReset"].forEach((id) => { $(id).disabled = false; });
    }
  }
  $("edCopy").onclick = () => save("copy");
  $("edReplace").onclick = () => save("replace");
  $("edCancel").onclick = close;
  $("edReset").onclick = reset;
  window.addEventListener("keydown", (e) => {
    if ($("ed").hidden) return;
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save("copy"); }
  });
  window.addEventListener("resize", () => { if (!$("ed").hidden) draw(); });

  window.PhotoEditor = {
    open(it, url, onSaved) {
      item = it; done = onSaved;
      $("edName").textContent = it.name;
      $("edInfo").textContent = "Loading…";
      $("ed").hidden = false;
      const im = new Image();
      im.decoding = "async";
      im.onload = () => { if (item !== it) return; img = im; reset(); };
      im.onerror = () => { toast("Couldn't open this photo"); close(); };
      im.src = url;
    },
    get open_() { return !$("ed").hidden; },
  };
})();
