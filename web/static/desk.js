// Laptop view. Talks to the local server over loopback only.
(function () {
  const { ICONS, toast, renderTimeline } = window.T;
  const $ = (id) => document.getElementById(id);
  let items = [];
  let phones = 0;
  let pairOpen = true;
  let ws;

  // ---- static labels / icons ----
  $("attach").innerHTML = ICONS.plus;
  $("sendBtn").innerHTML = ICONS.send;
  $("folder").innerHTML = ICONS.folder + "Open Tonefer folder";
  $("togglePair").innerHTML = ICONS.qr + "Hide pairing code";
  $("repair").innerHTML = ICONS.x + "Unpair all phones";
  $("clear").innerHTML = ICONS.trash + "Clear history";
  $("viewerSave").innerHTML = ICONS.down + " Save";
  $("viewerClose").textContent = "Close";

  // ---- rendering ----
  const opts = {
    self: "laptop",
    peerLabel: "phone",
    emptyTitle: "Nothing here yet",
    emptyText: "Send a note or drop a photo — it lands on your phone instantly.",
    image: (item, img) => { img.src = `/desk/file/${item.id}`; },
    open: (item) => openViewer(item),
    download: (item) => {
      const a = document.createElement("a");
      a.href = `/desk/file/${item.id}?download=1`;
      a.download = item.name;
      a.click();
    },
    remove: async (item) => {
      await fetch(`/desk/api/delete/${item.id}`, { method: "POST" });
    },
  };

  function draw(scroll = true) {
    const sc = $("scroll");
    const nearBottom = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 120;
    renderTimeline($("timeline"), items, opts);
    if (scroll || nearBottom) sc.scrollTop = sc.scrollHeight;
  }

  function setPresence(n) {
    phones = n;
    const s = $("status");
    s.classList.toggle("on", n > 0);
    s.textContent = n > 0 ? (n === 1 ? "phone connected" : `${n} phones connected`) : "no phone";
    if (n > 0 && pairOpen && !userToggled) setPair(false);
    if (n === 0 && !pairOpen && !userToggled) setPair(true);
  }

  let userToggled = false;
  function setPair(open) {
    pairOpen = open;
    $("pair").style.display = open ? "" : "none";
    $("togglePair").innerHTML = ICONS.qr + (open ? "Hide pairing code" : "Pair a phone");
    if (open) loadPair();
  }
  $("togglePair").onclick = () => { userToggled = true; setPair(!pairOpen); };

  // ---- pairing QR ----
  async function loadPair(ip) {
    const r = await fetch("/desk/api/pair" + (ip ? `?ip=${encodeURIComponent(ip)}` : ""));
    const d = await r.json();
    const sel = $("ipsel");
    if (d.svg) {
      $("qr").innerHTML = d.svg;
    } else {
      $("qr").innerHTML = '<div class="none">No network found.<br>Join your phone\'s hotspot, then this refreshes.</div>';
    }
    sel.hidden = d.ips.length < 2;
    sel.innerHTML = d.ips.map((x) => `<option ${x === d.ip ? "selected" : ""}>${x}</option>`).join("");
  }
  $("ipsel").onchange = (e) => loadPair(e.target.value);
  setInterval(() => { if (pairOpen && !$("qr").querySelector("svg")) loadPair(); }, 4000);

  // ---- live connection ----
  function connect() {
    ws = new WebSocket(`ws://${location.host}/desk/ws`);
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.type === "hello") {
        items = m.items;
        $("host").textContent = m.host + " · v" + m.version;
        setPresence(m.phones);
        draw();
      } else if (m.type === "presence") {
        setPresence(m.phones);
      } else if (m.type === "item") {
        items.push(m.item);
        draw();
        if (m.item.origin === "phone") {
          toast(m.item.kind === "text" ? "New message from phone" : `Received ${m.item.name}`);
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
      $("status").textContent = "server stopped";
      setTimeout(connect, 1500);
    };
  }
  connect();

  // tab-title badge when not focused
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
    if (!r.ok) { ta.value = text; autosize(); toast("Could not send"); }
  }

  // ---- sending files ----
  $("attach").onclick = () => $("file").click();
  $("file").onchange = (e) => { sendFiles([...e.target.files]); e.target.value = ""; };

  function sendFiles(files) {
    if (!files.length) return;
    const row = document.createElement("div");
    row.className = "up";
    const label = files.length === 1 ? files[0].name : `${files.length} files`;
    row.innerHTML = `Sending ${T.esc(label)}<div class="progress"><i></i></div>`;
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

  // drag & drop anywhere
  let depth = 0;
  const main = $("main");
  window.addEventListener("dragenter", (e) => { if (e.dataTransfer.types.includes("Files")) { depth++; $("drop").classList.add("on"); } });
  window.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; $("drop").classList.remove("on"); } });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => {
    e.preventDefault(); depth = 0; $("drop").classList.remove("on");
    sendFiles([...e.dataTransfer.files]);
  });

  // paste images / files
  window.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.files || [])];
    if (files.length) { e.preventDefault(); sendFiles(files); }
  });

  // ---- side actions ----
  $("folder").onclick = async () => {
    const r = await fetch("/desk/api/open-folder", { method: "POST" });
    const d = await r.json();
    toast("Files are in " + d.path);
  };
  $("repair").onclick = async () => {
    if (!confirm("Unpair every phone? They will need to scan a new code.")) return;
    await fetch("/desk/api/repair", { method: "POST" });
    userToggled = false;
    setPair(true);
    toast("All phones unpaired — new code ready");
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

  loadPair();
  ta.focus();
})();
