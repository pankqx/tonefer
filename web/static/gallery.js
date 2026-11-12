/* Gallery for the laptop view: timeline grid, instant viewer, Trash, folders. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const { toast, size, ICONS } = window.T;
  const PAGE = 1200, BATCH = 240;

  let kind = "media", q = "", items = [], total = 0, drawn = 0, loading = false, loaded = false;
  let selecting = false, lastPicked = -1, stamp = 0, home = "";
  const short = (dir) => (home && dir.startsWith(home) ? "~" + dir.slice(home.length) : dir);
  const picked = new Set();

  const api = (path, body) => fetch(path, body === undefined ? undefined
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const thumb = (it) => `/desk/thumb/${it.id}?t=${it.t}`;
  const media = (it) => `/desk/media/${it.id}?t=${it.t}`;

  // ---------- dates ----------
  const dayKey = (t) => { const d = new Date(t); return d.getFullYear() * 10000 + d.getMonth() * 100 + d.getDate(); };
  const today = dayKey(Date.now()), yesterday = dayKey(Date.now() - 86400000);
  function dayLabel(t) {
    const k = dayKey(t), d = new Date(t);
    if (k === today) return "Today";
    if (k === yesterday) return "Yesterday";
    const opts = { weekday: "short", day: "numeric", month: "long" };
    if (d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
    return d.toLocaleDateString(undefined, opts);
  }
  const when = (t) => new Date(t).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

  // ---------- loading ----------
  async function load(reset) {
    if (loading) return;
    loading = true;
    const mine = ++stamp;
    if (reset) { items = []; total = 0; drawn = 0; picked.clear(); lastPicked = -1; }
    try {
      const r = await fetch(`/desk/api/gallery?kind=${kind}&q=${encodeURIComponent(q)}&offset=${items.length}&limit=${PAGE}`);
      const d = await r.json();
      if (mine !== stamp) return;
      if (reset) { $("galGrid").innerHTML = ""; $("galScroll").scrollTop = 0; }
      items = items.concat(d.items);
      total = d.total;
      home = d.home || home;
      loaded = true;
      counts(d.counts);
      $("galEmpty").hidden = total > 0;
      if (!total) $("galEmpty").innerHTML = q ? "<b>Nothing found</b>No name or folder matches your search."
        : "<b>Nothing here yet</b>Add a folder with the Folders button to see its photos, videos and files.";
      draw();
      updateBar();
    } catch (_) { toast("Couldn't load the gallery"); }
    finally { loading = false; }
  }
  function counts(c) {
    if (!c) return;
    const n = { media: c.photo + c.video, photo: c.photo, video: c.video, file: c.file };
    document.querySelectorAll("#galKind button").forEach((b) => { b.querySelector("small").textContent = n[b.dataset.k].toLocaleString(); });
  }

  // ---------- drawing (in batches, as you scroll) ----------
  function draw() {
    const grid = $("galGrid"), end = Math.min(items.length, drawn + BATCH);
    let section = grid.lastElementChild, holder = section && section.lastElementChild;
    const frag = document.createDocumentFragment();
    for (let i = drawn; i < end; i++) {
      const it = items[i], k = String(dayKey(it.t));
      if (!section || section.dataset.day !== k) {
        section = document.createElement("section");
        section.className = "gal-day";
        section.dataset.day = k;
        section.innerHTML = `<h3>${dayLabel(it.t)}</h3><div class="${kind === "file" ? "gal-list" : "gal-grid"}"></div>`;
        holder = section.lastElementChild;
        frag.appendChild(section);
      }
      holder.appendChild(kind === "file" ? row(it) : tile(it));
    }
    grid.appendChild(frag);
    drawn = end;
  }
  function tile(it) {
    const b = document.createElement("button");
    b.className = "tile" + (picked.has(it.id) ? " sel" : "");
    b.dataset.id = it.id;
    b.title = it.name;
    b.innerHTML = `<img loading="lazy" decoding="async" alt="" src="${thumb(it)}"><span class="pick"></span>${it.kind === "video" ? '<span class="play">▶ VIDEO</span>' : ""}`;
    if (it.kind === "video") {
      // No thumbnailer on this computer: let the browser show the first frame itself.
      b.firstChild.onerror = () => {
        const v = document.createElement("video");
        v.muted = true; v.preload = "metadata"; v.playsInline = true; v.src = media(it) + "#t=0.5";
        b.firstChild.replaceWith(v);
      };
    }
    return b;
  }
  function row(it) {
    const b = document.createElement("button");
    b.className = "frow" + (picked.has(it.id) ? " sel" : "");
    b.dataset.id = it.id;
    const ext = (it.name.includes(".") ? it.name.split(".").pop() : "file").slice(0, 4);
    b.innerHTML = `<span class="pick"></span><span class="ext"></span><span class="nm"><b></b><small></small></span><span class="sz">${size(it.size)}</span><span class="dt">${when(it.t)}</span>`;
    b.querySelector(".ext").textContent = ext;
    b.querySelector("b").textContent = it.name;
    b.querySelector("small").textContent = short(it.dir);
    return b;
  }
  $("galScroll").addEventListener("scroll", () => {
    const sc = $("galScroll");
    if (sc.scrollHeight - sc.scrollTop - sc.clientHeight > 1400) return;
    if (drawn < items.length) draw();
    else if (items.length < total) load(false);
  }, { passive: true });

  // ---------- selection ----------
  const indexOf = (id) => items.findIndex((x) => x.id === id);
  function setPicked(id, on) {
    if (on) picked.add(id); else picked.delete(id);
    const el = $("galGrid").querySelector(`[data-id="${id}"]`);
    if (el) el.classList.toggle("sel", on);
  }
  function updateBar() {
    selecting = selecting && true;
    if (!picked.size && !selecting) { $("galActions").hidden = true; }
    else { $("galActions").hidden = false; $("galSel").textContent = picked.size ? `${picked.size} selected` : "Select items"; }
    $("galGrid").classList.toggle("selecting", selecting || picked.size > 0);
    $("galSelect").textContent = selecting || picked.size ? "Done" : "Select";
    $("galCount").textContent = loaded ? `${total.toLocaleString()} item${total === 1 ? "" : "s"}` : "";
  }
  $("galGrid").addEventListener("click", (e) => {
    const el = e.target.closest("[data-id]");
    if (!el) return;
    const id = el.dataset.id, i = indexOf(id);
    const onPick = e.target.classList.contains("pick");
    if (selecting || picked.size || onPick || e.ctrlKey || e.metaKey) {
      if (e.shiftKey && lastPicked >= 0) {
        const [a, b] = [Math.min(lastPicked, i), Math.max(lastPicked, i)];
        for (let k = a; k <= b; k++) setPicked(items[k].id, true);
      } else setPicked(id, !picked.has(id));
      lastPicked = i;
      updateBar();
    } else if (items[i].kind === "file") {
      api("/desk/api/gallery/open", { id });
    } else open(i);
  });
  $("galSelect").onclick = () => { if (selecting || picked.size) clearPick(); else { selecting = true; updateBar(); } };
  $("galCancel").onclick = clearPick;
  function clearPick() { [...picked].forEach((id) => setPicked(id, false)); selecting = false; lastPicked = -1; updateBar(); }

  async function trash(ids) {
    if (!ids.length) return 0;
    const r = await api("/desk/api/gallery/trash", { ids });
    if (!r.ok) { toast("Couldn't move to Trash"); return 0; }
    const d = await r.json();
    const failed = new Set(d.failed || []);
    const gone = new Set(ids.filter((id) => { const it = items.find((x) => x.id === id); return it && !failed.has(it.name); }));
    items = items.filter((x) => !gone.has(x.id));
    total -= gone.size; drawn -= gone.size;
    gone.forEach((id) => {
      picked.delete(id);
      const el = $("galGrid").querySelector(`[data-id="${id}"]`);
      if (el) { const sec = el.closest(".gal-day"); el.remove(); if (sec && !sec.lastElementChild.children.length) sec.remove(); }
    });
    toast(d.failed && d.failed.length ? `Moved ${d.moved} to Trash. ${d.failed.length} couldn't be moved.` : `Moved ${d.moved} to Trash`);
    $("galEmpty").hidden = total > 0;
    updateBar();
    return gone.size;
  }
  $("galTrash").onclick = async () => { await trash([...picked]); selecting = false; updateBar(); };
  $("galSend").onclick = async () => {
    const r = await api("/desk/api/gallery/send", { ids: [...picked], to: ($("toSel") || {}).value || "" });
    if (r.ok) { const d = await r.json(); toast(`Sent ${d.sent} to your phone`); clearPick(); } else toast("Couldn't send");
  };

  // ---------- filters ----------
  $("galKind").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || b.dataset.k === kind) return;
    kind = b.dataset.k;
    document.querySelectorAll("#galKind button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    selecting = false;
    load(true);
  });
  let typing;
  $("galSearch").addEventListener("input", (e) => { clearTimeout(typing); typing = setTimeout(() => { q = e.target.value.trim(); load(true); }, 180); });

  // ---------- folders ----------
  async function folders(body) {
    const r = body ? await api("/desk/api/gallery/folders", body) : await fetch("/desk/api/gallery/folders");
    if (r.status === 501) return toast("No folder picker on this computer. Install zenity, then try again.");
    if (!r.ok) return toast(await r.text());
    const d = await r.json(), ul = $("galFolderList");
    ul.innerHTML = "";
    d.folders.forEach((f) => {
      const li = document.createElement("li");
      li.innerHTML = `<span></span><button>Remove</button>`;
      li.firstChild.textContent = f.path;
      li.lastChild.onclick = () => folders({ remove: f.path }).then(() => load(true));
      ul.appendChild(li);
    });
  }
  $("galFolders").onclick = () => { const p = $("galFolderPanel"); p.hidden = !p.hidden; if (!p.hidden) folders(); };
  $("galFolderAdd").onclick = () => folders({ pick: true }).then(() => load(true));
  $("galFolderClose").onclick = () => { $("galFolderPanel").hidden = true; };

  // ---------- viewer ----------
  let at = -1, wheelAt = 0;
  const stage = $("lbStage");
  function open(i) { at = i; $("lb").hidden = false; show(0); }
  function close() {
    $("lb").hidden = true; at = -1;
    stage.querySelectorAll("img,video").forEach((n) => { if (n.pause) n.pause(); n.remove(); });
    stage.style.backgroundImage = "";
  }
  /** Next photo or video in the timeline, skipping nothing; loads more when the end is near. */
  function step(d) {
    const n = at + d;
    if (n < 0 || n >= items.length) return;
    at = n;
    show(d);
    if (items.length - at < 40 && items.length < total) load(false);
  }
  function show(dir) {
    const it = items[at];
    if (!it) return close();
    stage.querySelectorAll("img,video,.lb-note").forEach((n) => { if (n.pause) n.pause(); n.remove(); });
    stage.classList.remove("in-next", "in-prev");
    void stage.offsetWidth;
    if (dir) stage.classList.add(dir > 0 ? "in-next" : "in-prev");
    $("lbName").textContent = it.name;
    $("lbInfo").textContent = `${at + 1} of ${total.toLocaleString()} · ${when(it.t)} · ${size(it.size)} · ${short(it.dir)}`;
    // The grid thumbnail is already in the browser's cache: show it at once, then sharpen.
    stage.style.backgroundImage = `url("${thumb(it)}")`;
    let node;
    if (it.kind === "video") {
      node = document.createElement("video");
      node.controls = true; node.autoplay = true; node.playsInline = true; node.preload = "auto";
      node.poster = thumb(it);
      node.onplaying = () => { stage.style.backgroundImage = ""; };
      node.onerror = () => {
        node.remove();
        const note = document.createElement("div");
        note.className = "lb-note";
        note.innerHTML = `<span>This video format can't play inside Tonefer on this computer.</span><button class="lb-btn">Open in your video player</button>`;
        note.lastChild.onclick = () => api("/desk/api/gallery/open", { id: it.id });
        stage.appendChild(note);
      };
    } else {
      node = new Image();
      node.decoding = "async";
      node.alt = it.name;
      node.onload = () => { stage.style.backgroundImage = ""; };
    }
    node.src = media(it);
    stage.insertBefore(node, stage.firstChild);
    // Warm the neighbours so the next step is instant.
    [at + 1, at - 1, at + 2].forEach((k) => {
      const nb = items[k];
      if (!nb) return;
      if (nb.kind === "photo") { const im = new Image(); im.decoding = "async"; im.src = media(nb); }
      else { const im = new Image(); im.src = thumb(nb); }
    });
  }
  $("lbPrev").onclick = () => step(-1);
  $("lbNext").onclick = () => step(1);
  $("lbClose").onclick = close;
  $("lbFolder").onclick = () => api("/desk/api/gallery/open", { id: items[at].id, folder: true });
  $("lbSend").onclick = async () => { const r = await api("/desk/api/gallery/send", { ids: [items[at].id], to: ($("toSel") || {}).value || "" }); toast(r.ok ? "Sent to your phone" : "Couldn't send"); };
  $("lbTrash").onclick = async () => {
    const id = items[at].id, keep = at;
    if (await trash([id])) { at = Math.min(keep, items.length - 1); if (at < 0) close(); else show(1); }
  };
  stage.addEventListener("wheel", (e) => {
    e.preventDefault();
    const now = performance.now();
    if (Math.abs(e.deltaY) < 12 || now - wheelAt < 260) return;
    wheelAt = now;
    step(e.deltaY > 0 ? 1 : -1);
  }, { passive: false });
  window.addEventListener("keydown", (e) => {
    if ($("lb").hidden) {
      if (!$("paneGallery").hidden && e.key === "Escape" && (picked.size || selecting)) clearPick();
      if (!$("paneGallery").hidden && e.key === "Delete" && picked.size) $("galTrash").click();
      return;
    }
    const v = stage.querySelector("video");
    if (e.key === "Escape") close();
    else if (e.key === "ArrowRight" || e.key === "ArrowDown" || e.key === "PageDown") { e.preventDefault(); step(1); }
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp" || e.key === "PageUp") { e.preventDefault(); step(-1); }
    else if (e.key === "Delete") $("lbTrash").click();
    else if (e.key === " " && v) { e.preventDefault(); if (v.paused) v.play(); else v.pause(); }
  });

  // ---------- public ----------
  window.Gallery = {
    show() { if (!loaded) load(true); else if ($("galScroll").scrollTop < 40 && !picked.size) load(true); },
    refreshed() { if (!$("paneGallery").hidden && $("lb").hidden && $("galScroll").scrollTop < 40 && !picked.size && !loading) load(true); },
  };
})();
