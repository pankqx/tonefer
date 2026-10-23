// Shared helpers for the laptop and phone views.
(function () {
  const ICONS = {
    copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>',
    down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11m0 0 4.5-4.5M12 15l-4.5-4.5M5 19.5h14"/></svg>',
    trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 7h15M10 11v6m4-6v6M6.5 7l1 12a2 2 0 0 0 2 2h5a2 2 0 0 0 2-2l1-12M9.5 7V4.5h5V7"/></svg>',
    arrow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14m0 0-5.5-5.5M19 12l-5.5 5.5"/></svg>',
    send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5m0 0-6 6m6-6 6 6"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
    x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m6 6 12 12M18 6 6 18"/></svg>',
    folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/></svg>',
    qr: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><path d="M14 14h2v2h-2zM18 18h2v2h-2zM14 18h2M18 14h2"/></svg>',
  };

  // Two circles — phone and laptop. "apart" when not connected.
  function mark(cls = "", size = 30) {
    return `<svg class="mark ${cls}" width="${size * 1.6}" height="${size}" viewBox="0 0 48 30" aria-hidden="true">
      <circle class="a" cx="17" cy="15" r="13"/><circle class="b" cx="31" cy="15" r="13"/></svg>`;
  }
  const brand = () => `<span class="brand">tone<i>/</i><em>fer</em></span>`;

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function linkify(text) {
    return esc(text).replace(/\bhttps?:\/\/[^\s<]+[^\s<.,;:!?)\]'"]/g,
      (u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>`);
  }

  function size(n) {
    if (n < 1024) return n + " B";
    const u = ["KB", "MB", "GB"]; let i = -1;
    do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
    return n.toFixed(n < 10 ? 1 : 0) + " " + u[i];
  }

  const time = (ts) => new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  function dayLabel(ts) {
    const d = new Date(ts), today = new Date();
    const y = new Date(); y.setDate(today.getDate() - 1);
    if (d.toDateString() === today.toDateString()) return "Today";
    if (d.toDateString() === y.toDateString()) return "Yesterday";
    return d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
  }

  async function copyText(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (_) { /* fall through */ }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
    document.body.appendChild(ta);
    ta.select(); ta.setSelectionRange(0, text.length);
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (_) {}
    ta.remove();
    return ok;
  }

  let toastTimer;
  function toast(msg) {
    let el = document.querySelector(".toast");
    if (!el) { el = document.createElement("div"); el.className = "toast"; document.body.appendChild(el); }
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 1800);
  }

  /**
   * Render a list of history items, newest at the bottom.
   * opts.self      - origin string for "my" side ("phone" | "laptop")
   * opts.peerLabel - label for the other side
   * opts.image(item, imgEl) - fill an <img> with the picture
   * opts.download(item)     - save a file
   * opts.remove(item)       - optional delete action
   * opts.open(item, imgEl)  - open image viewer
   */
  function renderTimeline(root, items, opts) {
    root.innerHTML = "";
    if (!items.length) {
      root.innerHTML = `<div class="empty"><h3 class="big">${opts.emptyTitle}</h3><div class="dash"></div><p>${opts.emptyText}</p></div>`;
      return;
    }
    let lastDay = "";
    for (const item of items) {
      const day = dayLabel(item.ts);
      if (day !== lastDay) {
        const d = document.createElement("div");
        d.className = "day"; d.textContent = day;
        root.appendChild(d);
        lastDay = day;
      }
      root.appendChild(card(item, opts));
    }
  }

  function card(item, opts) {
    const mine = item.origin === opts.self;
    const el = document.createElement("div");
    el.className = "card" + (mine ? " mine" : "");
    el.dataset.id = item.id;
    const who = mine ? "you" : opts.peerLabel;
    const isImage = item.kind === "file" && /^image\//.test(item.mime || "") && !/svg/.test(item.mime);

    let body = "";
    if (item.kind === "text") {
      body = `<div class="text">${linkify(item.text)}</div>`;
    } else if (isImage) {
      el.classList.add("media");
      body = `<img class="thumb" alt="${esc(item.name)}" loading="lazy">`;
    } else {
      const ext = (item.name.split(".").pop() || "file").slice(0, 4);
      body = `<div class="file-row"><div class="badge">${esc(ext)}</div><div style="min-width:0"><div class="name">${esc(item.name)}</div><div class="size">${size(item.size)}</div></div></div>`;
    }

    const actions = [];
    if (item.kind === "text") actions.push(`<button class="icon-btn" data-act="copy" title="Copy">${ICONS.copy}</button>`);
    else actions.push(`<button class="icon-btn" data-act="save" title="Save">${ICONS.down}</button>`);
    if (opts.remove) actions.push(`<button class="icon-btn" data-act="remove" title="Delete">${ICONS.trash}</button>`);

    const extra = isImage ? ` · ${size(item.size)}` : "";
    el.innerHTML = body + `<div class="meta"><span class="when"><em>${esc(who)}</em> · ${time(item.ts)}${extra}</span>${actions.join("")}</div>`;

    const img = el.querySelector("img.thumb");
    if (img) {
      opts.image(item, img);
      img.addEventListener("click", () => opts.open(item, img));
    }
    el.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-act]");
      if (!b) return;
      const act = b.dataset.act;
      if (act === "copy") {
        const ok = await copyText(item.text);
        if (ok) { b.innerHTML = ICONS.check; setTimeout(() => (b.innerHTML = ICONS.copy), 1200); }
        toast(ok ? "Copied" : "Copy failed: long-press the text instead");
      } else if (act === "save") opts.download(item);
      else if (act === "remove") opts.remove(item);
    });
    return el;
  }

  // Loading screen: stays at least `min` ms so it never just flickers.
  const loaderStart = Date.now();
  function hideLoader(min = 650) {
    const el = document.getElementById("loader");
    if (!el || el.classList.contains("done")) return;
    setTimeout(() => el.classList.add("done"), Math.max(0, min - (Date.now() - loaderStart)));
  }
  function loaderText(html) {
    const m = document.getElementById("loaderMsg");
    if (m) m.innerHTML = html;
  }

  window.T = { hideLoader, loaderText, mark, brand, ICONS, esc, size, time, copyText, toast, renderTimeline };
})();
