// Phone view. Every payload is sealed with the pairing key (XSalsa20-Poly1305).
(function () {
  const { ICONS, toast, renderTimeline, mark, brand } = window.T;
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
    T.hideLoader();
    $("wMark").innerHTML = mark(title ? "apart" : "pulse", 32);
    if (title) $("wTitle").innerHTML = title;
    if (text) $("wText").textContent = text;
  }

  function unpair(reason) {
    try { localStorage.removeItem(STORE); } catch (_) {}
    key = null;
    showWelcome("Unpaired.", reason || "Scan the new code on your laptop to pair again.");
  }

  // ---------------- state + rendering ----------------
  let items = [];
  const urls = new Map(); // item id -> object URL (decrypted)

  // ---------------- big transfers (protocol v2) ----------------
  // Every chunk is sealed on its own with a header naming its transfer and position:
  //   tid (16 ASCII) | index (uint32 BE) | flags (1 = last)
  const HDR = 21;
  function chunkHeader(tid, index, last) {
    const h = new Uint8Array(HDR);
    h.set(enc.encode(tid).subarray(0, 16));
    new DataView(h.buffer).setUint32(16, index);
    h[20] = last ? 1 : 0;
    return h;
  }

  /** POST with the token; resolves to parsed JSON, rejects with {status, body}. */
  function post(url, body, onProgress, method = "POST") {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open(method, url);
      xhr.setRequestHeader("X-Tonefer-Token", token);
      if (onProgress) xhr.upload.onprogress = (ev) => onProgress(ev.loaded);
      xhr.onload = () => {
        let data = null;
        try { data = JSON.parse(xhr.responseText); } catch (_) {}
        if (xhr.status < 300) resolve(data || {});
        else reject({ status: xhr.status, body: data, text: xhr.responseText });
      };
      xhr.onerror = () => reject({ status: 0, text: "network error" });
      xhr.send(body ?? null);
    });
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const mbps = (bytes, ms) => (ms > 300 ? (bytes / (ms / 1000) / 1e6).toFixed(1) + " MB/s" : "");

  /** A progress row with a cancel button. */
  function progressRow(label) {
    const row = document.createElement("div");
    row.className = "up";
    row.innerHTML = `<span class="label-text"></span><span class="rate"></span><button class="up-x" aria-label="Cancel">${ICONS.x}</button><div class="progress"><i></i></div>`;
    $("uploads").appendChild(row);
    const r = {
      el: row, cancelled: false, onCancel: null,
      label(t) { row.querySelector(".label-text").textContent = t; },
      set(frac, rate) {
        row.querySelector("i").style.width = Math.min(100, 100 * frac) + "%";
        if (rate !== undefined) row.querySelector(".rate").textContent = rate;
      },
      done() { row.remove(); },
    };
    row.querySelector(".up-x").onclick = () => { r.cancelled = true; r.onCancel && r.onCancel(); };
    r.label(label);
    return r;
  }

  /** Downloads and decrypts a file of any size, frame by frame. */
  async function download(item, onProgress) {
    const r = await fetch(`/api/file/${item.id}?v=2`, { headers: { "X-Tonefer-Token": token } });
    if (!r.ok) throw new Error(await r.text());
    if (r.headers.get("X-Tonefer-Format") !== "2") return [open(new Uint8Array(await r.arrayBuffer()))];
    const total = Number(r.headers.get("X-Tonefer-Size")) || item.size || 0;
    const reader = r.body.getReader();
    const parts = [];
    let acc = new Uint8Array(2 * 1024 * 1024), len = 0, index = 0, got = 0, last = false;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      if (len + value.length > acc.length) {
        const bigger = new Uint8Array(Math.max(acc.length * 2, len + value.length));
        bigger.set(acc.subarray(0, len)); acc = bigger;
      }
      acc.set(value, len); len += value.length;
      let off = 0;
      while (len - off >= 4) {
        const n = new DataView(acc.buffer, acc.byteOffset + off, 4).getUint32(0);
        if (len - off < 4 + n) break;
        const plain = open(acc.slice(off + 4, off + 4 + n));
        off += 4 + n;
        const dv = new DataView(plain.buffer, plain.byteOffset);
        if (dec.decode(plain.subarray(0, 16)) !== item.id || dv.getUint32(16) !== index) throw new Error("damaged transfer");
        last = (plain[20] & 1) === 1;
        parts.push(plain.subarray(HDR));
        got += plain.length - HDR; index++;
        if (onProgress) onProgress(got, total);
      }
      if (off) { acc.copyWithin(0, off, len); len -= off; }
    }
    if (!last) throw new Error("connection dropped");
    return parts;
  }

  async function fetchFile(item, onProgress) {
    if (urls.has(item.id)) return urls.get(item.id);
    const p = (async () => {
      const parts = await download(item, onProgress);
      return URL.createObjectURL(new Blob(parts, { type: item.mime || "application/octet-stream" }));
    })();
    urls.set(item.id, p);
    p.catch(() => urls.delete(item.id));
    return p;
  }

  const opts = {
    self: "phone",
    peerLabel: "laptop",
    emptyTitle: "Connected",
    emptyText: "Send a note or a photo. It lands on your laptop right away.",
    image: async (item, img) => {
      img.classList.add("loading");
      try { img.src = await fetchFile(item); } catch (_) { img.alt = "Couldn't load"; }
      img.onload = img.onerror = () => img.classList.remove("loading");
    },
    open: async (item) => {
      viewing = item;
      $("viewerImg").src = await fetchFile(item);
      $("viewer").classList.add("open");
    },
    download: async (item) => {
      const big = item.size > 4 * 1024 * 1024 && !urls.has(item.id);
      const row = big ? progressRow(`Receiving ${item.name}`) : null;
      if (!big) toast("Unlocking…");
      const t0 = performance.now();
      try {
        const url = await fetchFile(item, row && ((got, total) => row.set(got / (total || 1), mbps(got, performance.now() - t0))));
        if (row) row.done();
        const a = document.createElement("a");
        a.href = url; a.download = item.name;
        document.body.appendChild(a); a.click(); a.remove();
        toast("Saved to Downloads");
      } catch (e) { if (row) row.done(); toast("Could not save: " + e.message); }
    },
  };

  function draw(force) {
    const sc = $("scroll");
    const near = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 140;
    renderTimeline($("timeline"), items, opts);
    if (force || near) sc.scrollTop = sc.scrollHeight;
  }

  let offlineTimer;
  function status(text, on) {
    const s = $("status");
    s.textContent = text;
    s.classList.toggle("on", !!on);
    clearTimeout(offlineTimer);
    if (on) $("offline").hidden = true;
    else offlineTimer = setTimeout(() => { $("offline").hidden = false; T.hideLoader(); }, 4000);
    if (!on && text === "laptop offline") T.loaderText("Looking for your laptop");
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
        T.hideLoader();
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
      } else if (m.type === "speedtest") {
        speedTest(m.bytes);
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

  // Attach menu: photos & files one by one, several files as one zip, or a whole folder as a zip.
  const menu = $("attachMenu");
  const closeMenu = () => { menu.hidden = true; };
  $("attach").onclick = (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; };
  document.addEventListener("click", (e) => { if (!menu.contains(e.target)) closeMenu(); });
  $("pickFiles").onclick = () => { closeMenu(); $("file").click(); };
  $("pickZip").onclick = () => { closeMenu(); $("fileZip").click(); };
  $("pickFolder").onclick = () => { closeMenu(); $("folder").click(); };

  $("file").onchange = async (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    for (const f of files) {
      const row = progressRow(`Sending ${f.name}`);
      try { await send([f], null, row); } catch (err) { if (!row.cancelled) toast("Failed: " + err.message); }
      finally { row.done(); }
    }
  };
  const asZip = async (files, name) => {
    if (!files.length) return;
    const row = progressRow(`Zipping ${name}`);
    try { await send(files, name, row); toast(`Sent ${name}`); }
    catch (err) { if (!row.cancelled) toast("Failed: " + err.message); }
    finally { row.done(); }
  };
  $("fileZip").onchange = (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    const d = new Date();
    const name = `Tonefer ${d.toISOString().slice(0, 10)} ${String(d.getHours()).padStart(2, "0")}.${String(d.getMinutes()).padStart(2, "0")}.zip`;
    asZip(files.map((f) => ({ file: f, path: f.name })), name);
  };
  $("folder").onchange = (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    if (!files.length) return;
    const top = (files[0].webkitRelativePath || "").split("/")[0] || "Folder";
    asZip(files.map((f) => ({ file: f, path: f.webkitRelativePath || `${top}/${f.name}` })), top + ".zip");
  };

  /**
   * Sends files to the laptop in sealed 4 MB chunks: any size, constant memory, and a dropped
   * chunk is simply sent again. With zipName, the laptop writes every file into one zip.
   */
  async function send(files, zipName, row) {
    if (!ws || ws.readyState !== 1) throw new Error("laptop not connected");
    const list = files.map((x) => (x instanceof File ? { file: x, path: x.name } : x));
    const total = list.reduce((n, x) => n + x.file.size, 0) || 1;
    const t0 = performance.now();
    let sent = 0, zip = null, current = null;
    row.onCancel = () => {
      if (zip) post(`/api/zip/${zip}`, null, null, "DELETE").catch(() => {});
      else if (current) post(`/api/upload/${current}`, null, null, "DELETE").catch(() => {});
    };
    const show = (extra = 0) => row.set((sent + extra) / total, mbps(sent + extra, performance.now() - t0));
    if (zipName) {
      zip = (await post("/api/zip/start", sealJson({ name: zipName, files: list.length, size: total }))).zip;
      row.label(`Sending ${zipName} · ${list.length} file${list.length === 1 ? "" : "s"}`);
    }
    for (const [n, { file, path }] of list.entries()) {
      if (row.cancelled) throw new Error("cancelled");
      if (zipName) row.label(`Sending ${zipName} · ${n + 1} of ${list.length}`);
      const meta = { name: file.name, mime: file.type, size: file.size, mtime: file.lastModified };
      if (zip) Object.assign(meta, { zip, path });
      const start = await post("/api/upload/start", sealJson(meta));
      const tid = start.id, size = start.chunk || 4 * 1024 * 1024;
      current = tid;
      const count = Math.max(1, Math.ceil(file.size / size));
      const prep = async (i) => {
        const data = new Uint8Array(await file.slice(i * size, Math.min(file.size, (i + 1) * size)).arrayBuffer());
        return { i, bytes: data.length, body: seal(concat(chunkHeader(tid, i, i === count - 1), data)) };
      };
      let i = 0, next = prep(0), tries = 0;
      while (i < count) {
        const c = await next;
        if (c.i !== i) { next = prep(i); continue; }
        if (i + 1 < count) next = prep(i + 1); // encrypt the next chunk while this one travels
        try {
          const r = await post(`/api/upload/${tid}/${i}`, c.body, (loaded) => show(Math.min(loaded, c.bytes)));
          sent += c.bytes; i = r.next; tries = 0;
          show();
        } catch (e) {
          if (row.cancelled) throw new Error("cancelled");
          if (e.status === 409 && e.body && typeof e.body.next === "number") { i = e.body.next; next = prep(i); continue; }
          if (e.status === 403) throw new Error("Pairing changed. Scan the code on your laptop again.");
          if (e.status === 404 || ++tries > 8) throw new Error(e.text || "connection lost");
          await sleep(Math.min(1000 * 2 ** (tries - 1), 10000)); // hotspot hiccup: wait, then send the chunk again
          next = prep(i);
        }
      }
    }
    if (zip) {
      row.label(`Finishing ${zipName}`);
      await post(`/api/zip/${zip}/finish`, sealJson({ zip }));
    }
  }

  // ---------------- speed test (started from the laptop) ----------------
  async function speedTest(bytes) {
    toast("Speed test running…");
    try {
      const t0 = performance.now();
      const r = await fetch(`/api/speedtest?n=${bytes}`, { headers: { "X-Tonefer-Token": token }, cache: "no-store" });
      await r.arrayBuffer();
      const down = bytes / ((performance.now() - t0) / 1000);
      const t1 = performance.now();
      await fetch("/api/speedtest", { method: "POST", headers: { "X-Tonefer-Token": token }, body: new Blob([new Uint8Array(bytes)]) });
      const up = bytes / ((performance.now() - t1) / 1000);
      toast(`↓ ${(down / 1e6).toFixed(1)} MB/s · ↑ ${(up / 1e6).toFixed(1)} MB/s`);
    } catch (e) {
      toast("Speed test failed");
    }
  }

  // ---------------- viewer ----------------
  let viewing;
  $("viewerSave").innerHTML = ICONS.down + " Save";
  $("viewerSave").onclick = () => opts.download(viewing);
  $("viewerClose").onclick = () => $("viewer").classList.remove("open");
  $("viewer").onclick = (e) => { if (e.target === $("viewer")) $("viewer").classList.remove("open"); };

  // ---------------- instructions sheet ----------------
  const closeHelp = () => { $("help").hidden = true; };
  $("helpBtn").onclick = () => { $("help").hidden = false; };
  $("helpClose").onclick = $("helpOk").onclick = closeHelp;
  $("help").onclick = (e) => { if (e.target === $("help")) closeHelp(); };

  // A new pairing link opened in an already-open tab only changes the hash.
  window.addEventListener("hashchange", () => { if (/k=/.test(location.hash)) location.reload(); });

  // ---------------- boot ----------------
  $("attach").innerHTML = ICONS.plus;
  $("brand").innerHTML = brand();
  $("wBrand").innerHTML = brand();
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
