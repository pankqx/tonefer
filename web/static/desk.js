// Laptop view. Talks to the local server over loopback only.
(function () {
  const { ICONS, toast, renderTimeline, mark, brand, copyText } = window.T;
  const $ = (id) => document.getElementById(id);
  let items = [];
  let phones = 0;
  let wantPair = true;      // show the QR card
  let userChoseIp = "";     // address picked from the dropdown, if any
  let lastPairKey = "";
  let ws;

  // ---- static bits ----
  $("brand").innerHTML = brand();
  $("attach").innerHTML = ICONS.plus;
  $("sendBtn").innerHTML = ICONS.send;
  $("copyAddr").innerHTML = ICONS.copy;
  $("copyFix").innerHTML = ICONS.copy;
  $("folder").innerHTML = ICONS.folder + "Open Tonefer folder";
  $("repair").innerHTML = ICONS.x + "Unpair all phones";
  $("clear").innerHTML = ICONS.trash + "Clear history";
  $("viewerSave").innerHTML = ICONS.down + " Save";
  $("pairAnother").innerHTML = "Pair another phone " + ICONS.arrow;
  $("connMark").innerHTML = mark("pulse", 34);
  const tick = () => { $("clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); };
  tick(); setInterval(tick, 10000);

  // ---- rendering ----
  const opts = {
    self: "laptop",
    peerLabel: "phone",
    emptyTitle: "No transfers yet",
    emptyText: "Send a note or drop a photo. It lands on your phone right away.",
    image: (item, img) => {
      img.classList.add("loading");
      img.onload = img.onerror = () => img.classList.remove("loading");
      img.src = `/desk/file/${item.id}`;
    },
    open: (item) => openViewer(item),
    download: (item) => {
      const a = document.createElement("a");
      a.href = `/desk/file/${item.id}?download=1`;
      a.download = item.name;
      a.click();
    },
    remove: async (item) => { await fetch(`/desk/api/delete/${item.id}`, { method: "POST" }); },
    extract: async (item) => {
      toast("Unzipping…");
      const r = await fetch(`/desk/api/extract/${item.id}`, { method: "POST" });
      if (!r.ok) return toast(await r.text());
      const d = await r.json();
      toast(`Unzipped to ${d.name}`);
    },
  };

  // ---- guests, search ----
  let guests = [];
  const guestNames = {};   // remembered after a session ends, so old items keep their label
  const guestName = (id) => guestNames[id] || "guest";
  opts.who = (item) => {
    if (!item.session) return "";
    const n = guestNames[item.session];
    return item.origin === "laptop" ? `you → ${n || "guest"}` : (n ? `guest · ${n}` : "guest");
  };
  let query = "";
  $("search").addEventListener("input", (e) => { query = e.target.value.trim().toLowerCase(); draw(false); });

  function draw(scroll = true) {
    const sc = $("scroll");
    const nearBottom = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 120;
    const shown = query ? items.filter((i) => ((i.text || "") + " " + (i.name || "")).toLowerCase().includes(query)) : items;
    renderTimeline($("timeline"), shown, query && !shown.length
      ? { ...opts, emptyTitle: "Nothing found", emptyText: "No note or file name matches your search." } : opts);
    if (scroll || nearBottom) sc.scrollTop = sc.scrollHeight;
  }


  function setPresence(n) {
    const was = phones;
    phones = n;
    const s = $("status");
    s.classList.toggle("on", n > 0);
    s.textContent = n > 0 ? (n === 1 ? "phone connected" : `${n} phones connected`) : "no phone yet";
    if (n > 0 && was === 0) wantPair = false;
    if (n === 0) wantPair = true;
    layout();
  }

  function layout() {
    $("pairCard").hidden = !wantPair;
    $("connCard").hidden = wantPair || phones === 0;
    if (phones > 0) {
      $("connText").textContent = phones === 1
        ? "Anything you send shows up there instantly."
        : `${phones} phones are connected. Everything you send reaches all of them.`;
    }
  }

  $("pairAnother").onclick = () => { wantPair = true; layout(); loadPair(true); };

  // ---- pairing card: re-polled so the QR always matches the current network ----
  async function loadPair(force) {
    let d;
    try {
      const q = userChoseIp ? `?ip=${encodeURIComponent(userChoseIp)}` : "";
      d = await (await fetch("/desk/api/pair" + q)).json();
    } catch (_) { return; }

    const key = [d.url, d.wifi, JSON.stringify(d.firewall), d.addrs.map((a) => a.ip).join()].join("|");
    if (key === lastPairKey && !force) return;
    const urlChanged = lastPairKey && lastPairKey.split("|")[0] !== d.url;
    lastPairKey = key;

    const qr = $("qr");
    if (d.svg) {
      qr.innerHTML = d.svg;
      if (urlChanged) { qr.classList.remove("fresh"); void qr.offsetWidth; qr.classList.add("fresh"); toast("Network changed. QR code updated"); }
    } else {
      qr.innerHTML = `<div class="none">${mark("apart", 32)}<b>No network yet.</b>Turn on your phone's hotspot and connect this laptop to it. This card updates by itself.</div>`;
    }

    $("addrRow").hidden = !d.address;
    $("addr").textContent = d.address;
    const sel = $("ipsel");
    sel.hidden = d.addrs.length < 2;
    sel.innerHTML = d.addrs.map((a) => `<option value="${a.ip}" ${a.ip === d.ip ? "selected" : ""}>${a.iface}</option>`).join("");

    // checklist
    const c2 = $("c2"), c2t = $("c2t");
    if (d.wifi) {
      c2.className = "n ok";
      c2t.innerHTML = `Laptop is on <mark>${T.esc(d.wifi)}</mark><small>Should be your phone's hotspot.</small>`;
    } else if (d.addrs.length) {
      c2.className = "n";
      c2t.innerHTML = `Laptop joined it<small>Pick your phone in the laptop's Wi‑Fi list.</small>`;
    } else {
      c2.className = "n warn";
      c2t.innerHTML = `Laptop isn't on any network<small>Pick your phone in the laptop's Wi‑Fi list.</small>`;
    }

    // firewall
    const fw = d.firewall;
    $("fw").hidden = !fw || phones > 0;
    if (fw) { $("fwText").textContent = fw.text; $("fwFix").textContent = fw.fix; }
  }
  $("ipsel").onchange = (e) => { userChoseIp = e.target.value; loadPair(true); };
  setInterval(() => { if (wantPair || phones === 0) loadPair(); }, 3000);

  $("copyAddr").onclick = async () => toast((await copyText("http://" + $("addr").textContent)) ? "Address copied" : "Copy failed");
  $("copyFix").onclick = async () => toast((await copyText($("fwFix").textContent)) ? "Copied. Paste it in a terminal" : "Copy failed");

  // ---- live connection ----
  function connect() {
    ws = new WebSocket(`ws://${location.host}/desk/ws`);
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.type === "hello") {
        T.hideLoader();
        items = m.items;
        if (m.guests) setGuests(m.guests);
        $("host").textContent = m.host;
        setPresence(m.phones);
        draw();
      } else if (m.type === "presence") {
        setPresence(m.phones);
        if (m.guests) setGuests(m.guests);
      } else if (m.type === "item") {
        items.push(m.item);
        draw();
        if (m.item.origin === "phone" && m.item.kind === "file") askWhere(m.item);
        if (m.item.origin === "phone") {
          if (!$("paneHelp").hidden) showTab("transfers");
          toast(m.item.kind === "text" ? "New note from your phone" : `Got ${m.item.name}`);
          ping();
        }
      } else if (m.type === "rate") {
        onRate(m);
        incoming(m);
      } else if (m.type === "zipping") {
        zipping(m);
      } else if (m.type === "notice") {
        toast(m.text);
        loadPair(true);
      } else if (m.type === "deleted") {
        items = items.filter((i) => i.id !== m.id);
        draw(false);
      } else if (m.type === "cleared") {
        items = [];
        draw();
      }
    };
    ws.onclose = () => {
      setPresence(0);
      $("status").textContent = "tonefer stopped";
      setTimeout(connect, 1500);
    };
  }
  connect();

  // Live rows for zips being built on the laptop and big files arriving from the phone.
  const rows = {};
  function zipping(m) {
    let r = rows[m.id];
    if (!r) r = rows[m.id] = progressRow(`Zipping ${m.name}`);
    if (m.finished) {
      r.done(); delete rows[m.id];
      if (m.error) toast(`Couldn't zip: ${m.error}`);
      return;
    }
    if (m.total) {
      r.set(m.done / m.total, `${m.files} files`);
      r.label(`Zipping ${m.name} · ${T.size(m.done)} of ${T.size(m.total)}`);
    }
  }
  function incoming(m) {
    if (m.dir !== "in" || m.label === "Speed test" || !m.total || m.total < 4 * 1024 * 1024) return;
    const id = "in" + m.id;
    let r = rows[id];
    if (m.done) { if (r) { r.done(); delete rows[id]; } return; }
    if (!r) r = rows[id] = progressRow(`Receiving ${m.label}`);
    r.set(m.bytes / m.total, (m.bps / 1e6).toFixed(1) + " MB/s");
  }

  let unseen = 0;
  function ping() {
    if (document.hasFocus()) return;
    unseen++;
    document.title = `(${unseen}) tonefer`;
  }
  window.addEventListener("focus", () => { unseen = 0; document.title = "tonefer"; });

  // ---- sending text ----
  const ta = $("text");
  function autosize() {
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
    $("sendBtn").disabled = !ta.value.trim();
  }
  ta.addEventListener("input", autosize);
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendText(); }
  });
  $("composer").addEventListener("submit", (e) => { e.preventDefault(); sendText(); });

  async function sendText() {
    const text = ta.value;
    if (!text.trim()) return;
    ta.value = ""; autosize();
    const r = await fetch("/desk/api/text", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, to: $("toSel").value }),
    });
    if (!r.ok) { ta.value = text; autosize(); toast("Couldn't send"); }
  }

  // ---- sending files and folders ----
  const menu = $("attachMenu");
  const closeMenu = () => { menu.hidden = true; };
  $("attach").onclick = (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; };
  document.addEventListener("click", (e) => { if (!menu.contains(e.target)) closeMenu(); });
  $("pickFiles").onclick = () => { closeMenu(); $("file").click(); };
  $("pickZip").onclick = () => { closeMenu(); $("fileZip").click(); };
  $("pickFolder").onclick = () => { closeMenu(); sendFolder(); };
  $("file").onchange = (e) => { sendFiles([...e.target.files]); e.target.value = ""; };
  $("fileZip").onchange = (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    const d = new Date();
    const name = `Tonefer ${d.toISOString().slice(0, 10)} ${String(d.getHours()).padStart(2, "0")}.${String(d.getMinutes()).padStart(2, "0")}`;
    sendFiles(files.map((f) => ({ file: f, path: f.name })), name);
  };
  $("folderInput").onchange = (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    if (!files.length) return;
    const top = (files[0].webkitRelativePath || "").split("/")[0] || "Folder";
    sendFiles(files.map((f) => ({ file: f, path: f.webkitRelativePath || `${top}/${f.name}` })), top);
  };

  // The laptop zips the folder straight from disk (fast, no copying through the page).
  // Without a system folder picker, fall back to the browser's own.
  async function sendFolder() {
    const r = await fetch("/desk/api/send-folder", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ to: $("toSel").value }),
    });
    if (r.status === 501) return $("folderInput").click();
    if (!r.ok) return toast(await r.text());
  }

  const mbps = (bytes, ms) => (ms > 300 ? (bytes / (ms / 1000) / 1e6).toFixed(1) + " MB/s" : "");
  function progressRow(label, onCancel) {
    const row = document.createElement("div");
    row.className = "up";
    row.innerHTML = `<span class="label-text"></span><span class="rate"></span>${onCancel ? `<button class="up-x" title="Cancel">${ICONS.x}</button>` : ""}<div class="progress"><i></i></div>`;
    row.querySelector(".label-text").textContent = label;
    if (onCancel) row.querySelector(".up-x").onclick = onCancel;
    $("uploads").appendChild(row);
    return {
      el: row,
      label: (t) => { row.querySelector(".label-text").textContent = t; },
      set: (frac, rate) => {
        row.querySelector("i").style.width = Math.min(100, 100 * frac) + "%";
        if (rate !== undefined) row.querySelector(".rate").textContent = rate;
      },
      done: () => row.remove(),
    };
  }

  /** Files go to the laptop's own disk, streamed: any size. With zipName they become one zip. */
  function sendFiles(list, zipName) {
    list = list.map((x) => (x instanceof File ? { file: x, path: x.name } : x));
    if (!list.length) return;
    const label = zipName ? `Zipping ${zipName}.zip · ${list.length} files`
      : list.length === 1 ? `Sending ${list[0].file.name || "pasted image"}` : `Sending ${list.length} files`;
    const xhr = new XMLHttpRequest();
    const row = progressRow(label, () => xhr.abort());
    const fd = new FormData();
    for (const { file, path } of list) {
      if (zipName) {
        fd.append("path", path);
        fd.append("size", String(file.size));
        fd.append("mtime", String(file.lastModified || 0));
      }
      fd.append("file", file, file.name || "pasted.png");
    }
    const t0 = performance.now();
    const qs = new URLSearchParams();
    if (zipName) qs.set("zip", zipName);
    if ($("toSel").value) qs.set("to", $("toSel").value);
    xhr.open("POST", "/desk/api/upload?" + qs);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) row.set(e.loaded / e.total, mbps(e.loaded, performance.now() - t0));
      if (zipName && e.loaded === e.total) row.label(`Finishing ${zipName}.zip`);
    };
    xhr.onload = () => { row.done(); if (xhr.status >= 300) toast("Couldn't send: " + xhr.responseText); };
    xhr.onerror = () => { row.done(); toast("Couldn't send"); };
    xhr.onabort = () => { row.done(); toast("Cancelled"); };
    xhr.send(fd);
  }

  // Dropped folders are walked in the page and sent as one zip each; loose files go one by one.
  async function walk(entry, prefix, out) {
    if (entry.isFile) {
      const file = await new Promise((res, rej) => entry.file(res, rej));
      out.push({ file, path: prefix + file.name });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      for (;;) {
        const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
        if (!batch.length) break;
        for (const e of batch) await walk(e, prefix + entry.name + "/", out);
      }
    }
  }

  let depth = 0;
  window.addEventListener("dragenter", (e) => { if (e.dataTransfer.types.includes("Files")) { depth++; $("drop").classList.add("on"); } });
  window.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; $("drop").classList.remove("on"); } });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", async (e) => {
    e.preventDefault(); depth = 0; $("drop").classList.remove("on");
    const entries = [...(e.dataTransfer.items || [])].map((it) => it.webkitGetAsEntry && it.webkitGetAsEntry()).filter(Boolean);
    const folders = entries.filter((x) => x.isDirectory);
    if (!folders.length) return sendFiles([...e.dataTransfer.files]);
    const loose = [];
    for (const f of entries.filter((x) => x.isFile)) { try { await walk(f, "", loose); } catch (_) {} }
    if (loose.length) sendFiles(loose);
    for (const dir of folders) {
      const files = [];
      try { await walk(dir, "", files); } catch (err) { toast(`Couldn't read ${dir.name}`); continue; }
      if (files.length) sendFiles(files, dir.name); else toast(`${dir.name} is empty`);
    }
  });
  window.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.files || [])];
    if (files.length) { e.preventDefault(); sendFiles(files); }
  });

  // ---- guest sessions ----
  const openQr = {};   // guest id -> QR svg currently shown
  function setGuests(list) {
    guests = list;
    list.forEach((g) => { guestNames[g.id] = g.name; });
    const box = $("guestList");
    box.innerHTML = "";
    for (const g of list) {
      const hours = Math.max(0, (g.expires - Date.now()) / 3600000);
      const el = document.createElement("div");
      el.className = "guest";
      el.innerHTML = `<div class="head"><i class="dot ${g.online ? "on" : ""}"></i><b></b></div>
        <div class="sub">${g.online ? "Connected" : "Waiting for them to scan"} · ends in ${hours >= 1 ? Math.round(hours) + " h" : Math.round(hours * 60) + " min"}</div>
        ${openQr[g.id] ? `<div class="qr">${openQr[g.id]}</div>` : ""}
        <div class="row"><button class="btn ghost" data-a="qr">${openQr[g.id] ? "Hide code" : "Show code"}</button><button class="btn ghost danger" data-a="end">End session</button></div>`;
      el.querySelector("b").textContent = g.name;
      el.querySelector('[data-a="qr"]').onclick = async () => {
        if (openQr[g.id]) delete openQr[g.id];
        else {
          const d = await (await fetch(`/desk/api/guest/${g.id}` + (userChoseIp ? "?ip=" + encodeURIComponent(userChoseIp) : ""))).json();
          if (!d.svg) return toast("Connect the laptop to the hotspot first");
          openQr[g.id] = d.svg;
        }
        setGuests(guests);
      };
      el.querySelector('[data-a="end"]').onclick = async () => {
        delete openQr[g.id];
        await fetch(`/desk/api/guest/${g.id}/end`, { method: "POST" });
        toast(`${g.name}'s session ended`);
      };
      box.appendChild(el);
    }
    // "Send to" appears only while a guest session is open.
    const sel = $("toSel"), keep = sel.value;
    sel.innerHTML = "";
    sel.add(new Option("My phone", ""));
    list.forEach((g) => sel.add(new Option(`Guest · ${g.name}`, g.id)));
    sel.value = list.some((g) => g.id === keep) ? keep : "";
    $("sendTo").hidden = !list.length;
  }
  $("guestForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const r = await fetch("/desk/api/guest" + (userChoseIp ? "?ip=" + encodeURIComponent(userChoseIp) : ""), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: $("guestName").value }),
    });
    if (!r.ok) return toast(await r.text());
    const d = await r.json();
    $("guestName").value = "";
    if (d.svg) openQr[d.id] = d.svg;
    guestNames[d.id] = d.name;
    setGuests(guests.some((g) => g.id === d.id) ? guests : [...guests, { id: d.id, name: d.name, expires: d.expires, online: 0 }]);
    toast(d.svg ? `Ask ${d.name} to scan the code` : "Connect the laptop to the hotspot, then press Show code");
  });

  // ---- where received files are saved ----
  let saveAsk = false;
  function showSave(d) {
    saveAsk = d.ask;
    $("savePath").textContent = d.dir;
    $("savePath").title = d.dir;
    $("saveReset").hidden = !d.custom;
    $("saveAsk").checked = d.ask;
  }
  async function setSave(body) {
    const r = await fetch("/desk/api/save-location", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (r.status === 501) {
      const typed = prompt("Folder to save received files in (full path):", $("savePath").textContent);
      if (typed) return setSave({ dir: typed });
      return;
    }
    if (!r.ok) return toast(await r.text());
    showSave(await r.json());
  }
  fetch("/desk/api/save-location").then((r) => r.json()).then(showSave).catch(() => {});
  $("saveChange").onclick = () => setSave({ pick: true });
  $("saveReset").onclick = () => setSave({ reset: true });
  $("saveAsk").onchange = (e) => setSave({ ask: e.target.checked });

  // With "ask" on, each file from a phone gets a bar: pick a folder for it, or leave it where it is.
  function askWhere(item) {
    if (!saveAsk) return;
    const el = document.createElement("div");
    el.className = "ask";
    el.innerHTML = `<span></span><button class="btn" data-a="pick">Choose folder…</button><button class="btn ghost" data-a="keep">Keep in Tonefer folder</button>`;
    el.querySelector("span").textContent = `Where should ${item.name} go?`;
    el.querySelector('[data-a="keep"]').onclick = () => el.remove();
    el.querySelector('[data-a="pick"]').onclick = async () => {
      let r = await fetch(`/desk/api/move/${item.id}`, { method: "POST" });
      if (r.status === 501) {
        const typed = prompt(`Folder to save ${item.name} in (full path):`);
        if (!typed) return;
        r = await fetch(`/desk/api/move/${item.id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dir: typed }) });
      }
      if (!r.ok) return toast(await r.text());
      const d = await r.json();
      if (d.cancelled) return;
      el.remove();
      toast(`Saved to ${d.dir}`);
    };
    $("asks").appendChild(el);
  }

  // ---- side actions ----
  $("folder").onclick = async () => {
    const d = await (await fetch("/desk/api/open-folder", { method: "POST" })).json();
    toast("Files are in " + d.path);
  };
  $("repair").onclick = async () => {
    if (!confirm("Unpair every phone? They'll need to scan a new code.")) return;
    await fetch("/desk/api/repair", { method: "POST" });
    wantPair = true; layout(); loadPair(true);
    toast("All phones unpaired. New code ready");
  };
  $("clear").onclick = async () => {
    if (!confirm("Clear the history on both devices? Files stay in your Tonefer folder.")) return;
    await fetch("/desk/api/clear", { method: "POST" });
  };

  // ---- viewer ----
  let viewing;
  function openViewer(item) {
    viewing = item;
    $("viewerImg").src = `/desk/file/${item.id}`;
    $("viewer").classList.add("open");
  }
  const closeViewer = () => $("viewer").classList.remove("open");
  $("viewerClose").onclick = closeViewer;
  $("viewer").onclick = (e) => { if (e.target === $("viewer")) closeViewer(); };
  $("viewerSave").onclick = () => opts.download(viewing);
  window.addEventListener("keydown", (e) => { if (e.key === "Escape") closeViewer(); });

  // ---- speedometer: real bytes/second measured by the laptop during each transfer ----
  const MAX_MBPS = 100;
  const R = 110, CX = 140, CY = 140, ARC = Math.PI * R;
  const frac = (mbps) => Math.min(1, Math.log10(1 + Math.max(0, mbps)) / Math.log10(1 + MAX_MBPS));
  (function drawGauge() {
    const ticks = [0, 1, 5, 10, 25, 50, 100].map((v) => {
      const th = Math.PI * (1 - frac(v));
      const p = (r) => [CX + r * Math.cos(th), CY - r * Math.sin(th)];
      const [x1, y1] = p(92), [x2, y2] = p(99), [lx, ly] = p(131);
      return `<line class="tick" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/><text class="ticklabel" x="${lx}" y="${ly + 3}">${v}</text>`;
    }).join("");
    $("gauge").innerHTML = `<svg viewBox="0 -6 280 160" aria-label="Transfer speed">
      <path class="track" d="M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}"/>
      <path class="fill" id="gFill" d="M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}" stroke-dasharray="${ARC}" stroke-dashoffset="${ARC}"/>
      ${ticks}
      <g class="needle" id="gNeedle" style="transform: rotate(-90deg)"><line x1="${CX}" y1="${CY}" x2="${CX}" y2="${CY - 84}"/></g>
      <circle class="hub" cx="${CX}" cy="${CY}" r="7"/></svg>`;
  })();

  const fmt = (bps) => {
    const mb = bps / 1e6;
    return mb >= 100 ? mb.toFixed(0) : mb >= 10 ? mb.toFixed(1) : mb.toFixed(2);
  };
  function setNeedle(bps) {
    const f = frac(bps / 1e6);
    $("gNeedle").style.transform = `rotate(${-90 + 180 * f}deg)`;
    $("gFill").setAttribute("stroke-dashoffset", String(ARC * (1 - f)));
    $("speedValue").textContent = fmt(bps);
  }
  let idleTimer;
  const live = {};
  function onRate(m) {
    clearTimeout(idleTimer);
    const dir = m.dir === "in" ? "Phone → laptop" : "Laptop → phone";
    const name = m.label === "Speed test" ? "speed test" : m.label;
    if (!m.done) {
      live[m.id] = m;
      setNeedle(m.bps);
      const pct = m.total ? Math.round(100 * m.bytes / m.total) : 0;
      $("speedWhat").textContent = `${dir} · ${name} · ${pct}%`;
    } else {
      delete live[m.id];
      // Small transfers finish before TCP gets up to speed; only big ones say much about the link.
      const meaningful = m.bytes >= 512 * 1024;
      const stat = m.dir === "in" ? "statIn" : "statOut";
      if (meaningful || m.label === "Speed test") $(stat).textContent = fmt(m.bps) + " MB/s";
      setNeedle(m.bps);
      $("speedWhat").textContent = `${dir} · ${name} · avg ${fmt(m.bps)} MB/s in ${(m.seconds || 0).toFixed(1)} s`;
      idleTimer = setTimeout(() => { if (!Object.keys(live).length) setNeedle(0); }, 2500);
      if (m.label === "Speed test" && m.dir === "in") {
        $("speedTest").disabled = false;
        $("speedTest").textContent = "Run speed test";
        toast(`Speed test: ↓ ${$("statOut").textContent} · ↑ ${$("statIn").textContent}`);
      }
    }
  }
  $("speedTest").onclick = async () => {
    const r = await fetch("/desk/api/speedtest", { method: "POST" });
    if (!r.ok) { toast(await r.text()); return; }
    $("speedTest").disabled = true;
    $("speedTest").textContent = "Testing… 16 MB each way";
    setTimeout(() => { $("speedTest").disabled = false; $("speedTest").textContent = "Run speed test"; }, 60000);
  };

  // ---- auto-join hotspot ----
  async function loadHotspot() {
    let d;
    try { d = await (await fetch("/desk/api/hotspot")).json(); } catch (_) { return; }
    const sel = $("hsName");
    const names = [...new Set([...(d.saved || []), d.name].filter(Boolean))];
    if (document.activeElement !== sel) {
      sel.innerHTML = `<option value="">Choose your phone's hotspot…</option>` +
        names.map((n) => `<option ${n === d.name ? "selected" : ""}>${T.esc(n)}</option>`).join("");
    }
    $("hsOn").checked = !!d.enabled && !!d.name;
    $("hsStatus").textContent = d.name
      ? (d.status || (d.current === d.name ? `Connected to ${d.name}` : `Watching for ${d.name}`))
      : names.length ? "Pick the hotspot once. The laptop then joins it whenever it's on."
      : "Join your phone's hotspot once from the Wi‑Fi menu, then pick it here.";
  }
  async function saveHotspot() {
    await fetch("/desk/api/hotspot", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: $("hsName").value, enabled: $("hsOn").checked }),
    });
    loadHotspot();
  }
  $("hsName").onchange = () => { if ($("hsName").value) $("hsOn").checked = true; saveHotspot(); };
  $("hsOn").onchange = saveHotspot;
  loadHotspot();
  setInterval(loadHotspot, 5000);

  // ---- tabs: Transfers | Instructions ----
  function showTab(name) {
    const help = name === "help";
    $("paneTransfers").hidden = help;
    $("paneHelp").hidden = !help;
    $("tabTransfers").setAttribute("aria-selected", String(!help));
    $("tabHelp").setAttribute("aria-selected", String(help));
    $("menuTransfers").classList.toggle("on", !help);
    $("menuHelp").classList.toggle("on", help);
    try { localStorage.setItem("tonefer.tab", name); } catch (_) {}
    if (!help) ta.focus();
  }
  $("tabTransfers").onclick = $("menuTransfers").onclick = () => showTab("transfers");
  $("tabHelp").onclick = $("menuHelp").onclick = () => showTab("help");
  window.addEventListener("keydown", (e) => {
    if (e.key === "F1") { e.preventDefault(); showTab($("paneHelp").hidden ? "help" : "transfers"); }
  });
  document.querySelectorAll(".toc a").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    document.querySelector(a.getAttribute("href")).scrollIntoView({ behavior: "smooth" });
  }));
  let savedTab = "transfers";
  try { savedTab = localStorage.getItem("tonefer.tab") || "transfers"; } catch (_) {}

  layout();
  loadPair(true);
  showTab(savedTab);
  ta.focus();
})();
