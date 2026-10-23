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
  };

  function draw(scroll = true) {
    const sc = $("scroll");
    const nearBottom = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 120;
    renderTimeline($("timeline"), items, opts);
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
        $("host").textContent = m.host;
        setPresence(m.phones);
        draw();
      } else if (m.type === "presence") {
        setPresence(m.phones);
      } else if (m.type === "item") {
        items.push(m.item);
        draw();
        if (m.item.origin === "phone") {
          if (!$("paneHelp").hidden) showTab("transfers");
          toast(m.item.kind === "text" ? "New note from your phone" : `Got ${m.item.name}`);
          ping();
        }
      } else if (m.type === "rate") {
        onRate(m);
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
      body: JSON.stringify({ text }),
    });
    if (!r.ok) { ta.value = text; autosize(); toast("Couldn't send"); }
  }

  // ---- sending files ----
  $("attach").onclick = () => $("file").click();
  $("file").onchange = (e) => { sendFiles([...e.target.files]); e.target.value = ""; };

  function sendFiles(files) {
    if (!files.length) return;
    const row = document.createElement("div");
    row.className = "up";
    const label = files.length === 1 ? files[0].name : `${files.length} files`;
    row.innerHTML = `Sending ${T.esc(label)}…<div class="progress"><i></i></div>`;
    $("uploads").appendChild(row);
    const fd = new FormData();
    files.forEach((f) => fd.append("file", f, f.name || "pasted.png"));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/desk/api/upload");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) row.querySelector("i").style.width = (100 * e.loaded / e.total) + "%";
    };
    xhr.onload = () => { row.remove(); if (xhr.status >= 300) toast("Upload failed: " + xhr.responseText); };
    xhr.onerror = () => { row.remove(); toast("Upload failed"); };
    xhr.send(fd);
  }

  let depth = 0;
  window.addEventListener("dragenter", (e) => { if (e.dataTransfer.types.includes("Files")) { depth++; $("drop").classList.add("on"); } });
  window.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; $("drop").classList.remove("on"); } });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => {
    e.preventDefault(); depth = 0; $("drop").classList.remove("on");
    sendFiles([...e.dataTransfer.files]);
  });
  window.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.files || [])];
    if (files.length) { e.preventDefault(); sendFiles(files); }
  });

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
