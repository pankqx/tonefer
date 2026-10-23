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
  $("connMark").innerHTML = mark("pulse", 54);

  // ---- rendering ----
  const opts = {
    self: "laptop",
    peerLabel: "phone",
    emptyTitle: "Nothing <em>here</em> yet.",
    emptyText: "Send a note or drop a photo. It lands on your phone right away.",
    image: (item, img) => { img.src = `/desk/file/${item.id}`; },
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
      qr.innerHTML = `<div class="none">${mark("apart", 44)}<b>No network yet.</b>Turn on your phone's hotspot and connect this laptop to it. This card updates by itself.</div>`;
    }

    $("addrRow").hidden = !d.address;
    $("addr").textContent = d.address;
    const sel = $("ipsel");
    sel.hidden = d.addrs.length < 2;
    sel.innerHTML = d.addrs.map((a) => `<option value="${a.ip}" ${a.ip === d.ip ? "selected" : ""}>${a.iface}</option>`).join("");

    // checklist
    const c2 = $("c2"), c2t = $("c2t");
    if (d.wifi) {
      c2.className = "n ok"; c2.textContent = "✓";
      c2t.innerHTML = `Laptop is on <mark>${T.esc(d.wifi)}</mark><small>Is that your phone's hotspot? If not, switch to it.</small>`;
    } else if (d.addrs.length) {
      c2.className = "n"; c2.textContent = "02";
      c2t.innerHTML = `Join it from this laptop<small>Pick your phone in the laptop's Wi‑Fi list.</small>`;
    } else {
      c2.className = "n warn"; c2.textContent = "02";
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
          toast(m.item.kind === "text" ? "New note from your phone" : `Got ${m.item.name}`);
          ping();
        }
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

  layout();
  loadPair(true);
  ta.focus();
})();
