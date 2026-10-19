// Phone view. Every payload is sealed with the pairing key (XSalsa20-Poly1305).
(function () {
  const { ICONS, toast, renderTimeline } = window.T;
  const $ = (id) => document.getElementById(id);
  const STORE = "tonefer.key";

  // ---------------- crypto ----------------
  const enc = new TextEncoder(), dec = new TextDecoder();

  function b64urlToBytes(s) {
    s = s.replace(/-/g, "+").replace(/_/g, "/");
    while (s.length % 4) s += "=";
    return b64ToBytes(s);
  }
  function b64ToBytes(s) {
    const bin = atob(s), out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  function bytesToB64(u8) {
    let s = "";
    for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
    return btoa(s);
  }
  const hex = (u8) => Array.from(u8, (b) => b.toString(16).padStart(2, "0")).join("");
  function concat(a, b) { const o = new Uint8Array(a.length + b.length); o.set(a); o.set(b, a.length); return o; }

  let key = null, token = "";

  function setKey(k) {
    key = k;
    token = hex(nacl.hash(concat(key, enc.encode("tonefer-auth")))).slice(0, 64);
  }
  function seal(bytes) {
    const nonce = nacl.randomBytes(24);
    return concat(nonce, nacl.secretbox(bytes, nonce, key));
  }
  function open(bytes) {
    const out = nacl.secretbox.open(bytes.subarray(24), bytes.subarray(0, 24), key);
    if (!out) throw new Error("decrypt failed");
    return out;
  }
  const sealJson = (o) => bytesToB64(seal(enc.encode(JSON.stringify(o))));
  const openJson = (s) => JSON.parse(dec.decode(open(b64ToBytes(s))));

  // ---------------- pairing ----------------
  function loadKey() {
    const m = location.hash.match(/k=([A-Za-z0-9_-]{40,})/);
    if (m) {
      try { localStorage.setItem(STORE, m[1]); } catch (_) {}
      history.replaceState(null, "", location.pathname); // drop key from the address bar
      return b64urlToBytes(m[1]);
    }
    try {
      const s = localStorage.getItem(STORE);
      if (s) return b64urlToBytes(s);
    } catch (_) {}
    return null;
  }

  function showWelcome(title, text) {
    $("app").hidden = true;
    $("welcome").hidden = false;
    if (title) $("wTitle").textContent = title;
    if (text) $("wText").textContent = text;
  }

  function unpair(reason) {
    try { localStorage.removeItem(STORE); } catch (_) {}
    key = null;
    showWelcome("This phone was unpaired.", reason || "Scan the new code on your laptop to pair again.");
  }

  // ---------------- state + rendering ----------------
  let items = [];
  const urls = new Map(); // item id -> object URL (decrypted)

  async function fetchFile(item) {
    if (urls.has(item.id)) return urls.get(item.id);
    const p = (async () => {
      const r = await fetch(`/api/file/${item.id}`, { headers: { "X-Tonefer-Token": token } });
      if (!r.ok) throw new Error(await r.text());
      const plain = open(new Uint8Array(await r.arrayBuffer()));
      return URL.createObjectURL(new Blob([plain], { type: item.mime || "application/octet-stream" }));
    })();
    urls.set(item.id, p);
    p.catch(() => urls.delete(item.id));
    return p;
  }

  const opts = {
    self: "phone",
    peerLabel: "laptop",
    emptyTitle: "Connected",
    emptyText: "Send a message or a photo — it shows up on your laptop instantly.",
    image: (item, img) => {
      const io = new IntersectionObserver(async (entries) => {
        if (!entries[0].isIntersecting) return;
        io.disconnect();
        try { img.src = await fetchFile(item); } catch (_) { img.alt = "Could not load"; }
      }, { rootMargin: "400px" });
      io.observe(img);
    },
    open: async (item) => {
      viewing = item;
      $("viewerImg").src = await fetchFile(item);
      $("viewer").classList.add("open");
    },
    download: async (item) => {
      toast("Decrypting…");
      try {
        const url = await fetchFile(item);
        const a = document.createElement("a");
        a.href = url; a.download = item.name;
        document.body.appendChild(a); a.click(); a.remove();
        toast("Saved to Downloads");
      } catch (e) { toast("Could not save: " + e.message); }
    },
  };

  function draw(force) {
    const sc = $("scroll");
    const near = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 140;
    renderTimeline($("timeline"), items, opts);
    if (force || near) sc.scrollTop = sc.scrollHeight;
  }

  function status(text, on) {
    const s = $("status");
    s.textContent = text;
    s.classList.toggle("on", !!on);
  }

  // ---------------- live connection ----------------
  let ws, retry = 0, timer;
  function connect() {
    if (!key) return;
    clearTimeout(timer);
    status("connecting");
    ws = new WebSocket(`ws://${location.host}/ws?t=${token}`);
    ws.onmessage = (e) => {
      let m;
      try { m = openJson(e.data); } catch (_) { return; }
      if (m.type === "hello") {
        retry = 0;
        items = m.items;
        status(m.host || "laptop", true);
        draw(true);
      } else if (m.type === "item") {
        items.push(m.item);
        draw(m.item.origin === "phone");
        if (m.item.origin === "laptop" && navigator.vibrate) navigator.vibrate(25);
      } else if (m.type === "deleted") {
        items = items.filter((i) => i.id !== m.id);
        draw();
      } else if (m.type === "cleared") {
        items = []; draw();
      }
    };
    ws.onclose = (e) => {
      if (e.code === 4001 || e.code === 1008) return unpair();
      status("laptop offline");
      checkPaired().then((ok) => {
        if (ok) timer = setTimeout(connect, Math.min(1000 * 2 ** retry++, 8000));
      });
    };
  }

  // Server rejects the token (e.g. after "Unpair all phones") with HTTP 401
  // before the socket opens; detect that so we don't retry forever.
  async function checkPaired() {
    try {
      const r = await fetch("/api/ping", { headers: { "X-Tonefer-Token": token } });
      if (r.status === 401) { unpair(); return false; }
    } catch (_) {}
    return true;
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && key && (!ws || ws.readyState > 1)) { retry = 0; connect(); }
  });

  // ---------------- sending ----------------
  const ta = $("text");
  function autosize() {
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 140) + "px";
    $("sendBtn").disabled = !ta.value.trim();
  }
  ta.addEventListener("input", autosize);
  $("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = ta.value;
    if (!text.trim()) return;
    if (!ws || ws.readyState !== 1) return toast("Laptop not connected");
    ws.send(sealJson({ type: "text", text }));
    ta.value = ""; autosize();
  });

  $("attach").onclick = () => $("file").click();
  $("file").onchange = async (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    for (const f of files) await upload(f);
  };

  async function upload(file) {
    const row = document.createElement("div");
    row.className = "up";
    row.innerHTML = `Encrypting ${T.esc(file.name)}<div class="progress"><i></i></div>`;
    $("uploads").appendChild(row);
    try {
      const plain = new Uint8Array(await file.arrayBuffer());
      const body = seal(plain);
      row.firstChild.textContent = `Sending ${file.name}`;
      await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/upload");
        xhr.setRequestHeader("X-Tonefer-Token", token);
        xhr.setRequestHeader("X-Tonefer-Meta", sealJson({ name: file.name, mime: file.type }));
        xhr.upload.onprogress = (ev) => {
          if (ev.lengthComputable) row.querySelector("i").style.width = (100 * ev.loaded / ev.total) + "%";
        };
        xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new Error(xhr.responseText || xhr.status)));
        xhr.onerror = () => reject(new Error("network error"));
        xhr.send(new Blob([body]));
      });
    } catch (err) {
      toast("Failed: " + err.message);
    } finally {
      row.remove();
    }
  }

  // ---------------- viewer ----------------
  let viewing;
  $("viewerSave").innerHTML = ICONS.down + " Save";
  $("viewerSave").onclick = () => opts.download(viewing);
  $("viewerClose").onclick = () => $("viewer").classList.remove("open");
  $("viewer").onclick = (e) => { if (e.target === $("viewer")) $("viewer").classList.remove("open"); };

  // A new pairing link opened in an already-open tab only changes the hash.
  window.addEventListener("hashchange", () => { if (/k=/.test(location.hash)) location.reload(); });

  // ---------------- boot ----------------
  $("attach").innerHTML = ICONS.plus;
  $("sendBtn").innerHTML = ICONS.send;

  const k = loadKey();
  if (!k || k.length !== 32) {
    showWelcome();
  } else {
    setKey(k);
    $("welcome").hidden = true;
    $("app").hidden = false;
    checkPaired().then((ok) => ok && connect());
  }
})();
