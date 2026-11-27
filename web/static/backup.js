/* Phone backup tab: scans the phone over USB (adb) and copies or moves every photo and video. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const { toast, size, esc } = window.T;
  let shown = false, timer = 0, last = null;

  const eta = (s) => {
    if (s == null) return "–";
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h ? `${h}h ${String(m).padStart(2, "0")}m` : m ? `${m}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
  };
  const n = (x) => Number(x || 0).toLocaleString();

  async function call(body) {
    const r = await fetch("/desk/api/backup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({ error: `the laptop answered ${r.status}` }));
    if (d.error && r.status >= 400) toast(d.error);
    if (d.progress) render(d);
    return d;
  }

  async function poll() {
    clearTimeout(timer);
    try {
      const r = await fetch("/desk/api/backup");
      if (r.ok) render(await r.json());
    } catch (_) {}
    const busy = last && last.busy;
    if (shown || busy) timer = setTimeout(poll, busy ? 800 : 2000);
  }

  function render(s) {
    last = s;
    const d = s.device, p = s.progress, sm = s.summary;

    // 01 phone
    $("bkPill").classList.toggle("on", !!d);
    $("bkPill").textContent = d ? (d.wireless ? "Wi‑Fi" : "USB") : "no phone";
    $("bkPhone").textContent = d ? (d.model || d.serial) : (s.adb ? "No phone connected" : "Android's USB tool is missing");
    $("bkPhoneSub").textContent = d ? `Ready · ${d.serial}` : "";
    $("bkDevErr").hidden = !!d || !s.error;
    $("bkDevErr").textContent = s.error || "";
    if (!d && !$("bkHow").dataset.touched) $("bkHow").open = true;
    $("bkAdbHint").hidden = s.adb;

    // 02 library + scan
    $("bkLib").textContent = s.library;
    $("bkLibReset").hidden = s.library === s.default_library;
    $("bkScan").disabled = s.busy || !d;
    $("bkScan").textContent = p.phase === "scanning" ? "Scanning…" : sm ? "Scan again" : "Scan the phone";
    $("bkScanMsg").className = "bk-msg " + (p.phase === "scanning" ? "scanning" : "");
    $("bkScanMsg").textContent = p.phase === "scanning" ? p.message : "";
    $("bkSummary").hidden = !sm;
    if (sm) {
      $("bkFiles").textContent = n(sm.files);
      $("bkSize").textContent = size(sm.bytes);
      $("bkMix").textContent = `${n(sm.photos)} / ${n(sm.videos)}`;
      $("bkSaved").textContent = n(sm.saved);
      $("bkSources").innerHTML = sm.sources.map((x) =>
        `<tr><td>${esc(x.name)}</td><td>${n(x.photos)}</td><td>${n(x.videos)}</td><td>${size(x.bytes)}</td>` +
        `<td class="${x.saved === x.files ? "all" : ""}">${n(x.saved)}</td></tr>`).join("");
    }

    // 03 run
    const ready = !!sm && sm.files > 0 && !s.busy && !!d;
    $("bkCopy").disabled = $("bkMove").disabled = !ready;
    if (!ready) $("bkConfirm").hidden = true;
    const running = p.phase === "running";
    const showProg = running || (p.total_files > 0 && (p.phase === "done" || p.phase === "stopped"));
    $("bkProg").hidden = !showProg;
    if (showProg) {
      const pct = p.total_bytes ? Math.min(100, 100 * p.live_bytes / p.total_bytes) : (p.phase === "done" ? 100 : 0);
      $("bkBar").style.width = pct.toFixed(1) + "%";
      $("bkPct").textContent = pct.toFixed(pct < 10 ? 1 : 0) + "%";
      $("bkCount").textContent = `${n(p.done_files)} of ${n(p.total_files)} files`;
      $("bkBytes").textContent = `${size(p.done_bytes)} of ${size(p.total_bytes)}`;
      $("bkSpeed").textContent = running && p.speed ? size(p.speed) + "/s" : "–";
      $("bkEta").textContent = running ? eta(p.eta) : "–";
      $("bkCurrent").textContent = running ? p.current : "";
      $("bkStop").disabled = !running;
      $("bkStop").hidden = !running;
    }
    const end = ["done", "stopped", "error"].includes(p.phase) && p.phase !== "scanning";
    $("bkMsg").className = "bk-msg " + p.phase;
    $("bkMsg").textContent = end ? p.message : (p.phase === "ready" && sm && sm.saved === sm.files && sm.files ? "Everything on the phone is already on this laptop." : "");
    $("bkFails").innerHTML = (p.failed || []).map((f) => `✗ ${esc(f.path)}: ${esc(f.error)}`).join("<br>") +
      (p.failed_count > (p.failed || []).length ? `<br>…and ${p.failed_count - p.failed.length} more (listed in Activity)` : "");
    $("bkAfter").hidden = p.phase !== "done" || !p.done_files;
    $("bkLog").textContent = (s.log || []).join("\n");
  }

  $("bkHow").addEventListener("toggle", () => { $("bkHow").dataset.touched = "1"; });
  $("bkScan").onclick = () => call({ action: "scan", hidden: $("bkHidden").checked }).then(poll);
  $("bkCopy").onclick = () => call({ action: "copy", verify: $("bkVerify").checked }).then(poll);
  $("bkMove").onclick = () => { $("bkConfirm").hidden = false; };
  $("bkMoveNo").onclick = () => { $("bkConfirm").hidden = true; };
  $("bkMoveYes").onclick = () => { $("bkConfirm").hidden = true; call({ action: "move" }).then(poll); };
  $("bkStop").onclick = () => call({ action: "stop" });
  $("bkLibChange").onclick = () => call({ action: "folder" });
  $("bkLibReset").onclick = () => call({ action: "folder", reset: true });
  $("bkLibOpen").onclick = () => call({ action: "open" });
  $("bkToGallery").onclick = () => window.showTab && window.showTab("gallery");
  $("bkPair").onclick = () => call({ action: "pair", address: $("bkPairAddr").value, code: $("bkPairCode").value }).then((d) => d.log && toast(d.log[d.log.length - 1] || "Done"));
  $("bkConnect").onclick = () => call({ action: "connect", address: $("bkConnAddr").value }).then((d) => d.log && toast(d.log[d.log.length - 1] || "Done"));

  window.PhoneBackup = {
    visible(on) { shown = on; if (on) poll(); },
  };
})();
