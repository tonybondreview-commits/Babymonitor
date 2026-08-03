/* Baby Monitor - logica della webapp (PWA).
 * Tutto in locale: si collega al "cervello" sulla rete di casa. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const video = $("video");
  const statusPill = $("status-pill");
  const motionBadge = $("motion-badge");
  const motionToggle = $("motion-toggle");
  const motionCount = $("motion-count");
  const sensitivity = $("sensitivity");
  const sensValue = $("sens-value");
  const player = $("player");
  const nowPlaying = $("now-playing");
  const npTitle = $("np-title");
  const loopToggle = $("loop-toggle");
  const offlineBanner = $("offline-banner");

  // ---- video live -----------------------------------------------------
  video.src = "stream.mjpg";
  video.onerror = () => setTimeout(() => { video.src = "stream.mjpg?" + Date.now(); }, 3000);

  // ---- suono (beep sintetico, funziona offline, nessun file) ----------
  // Un solo AudioContext condiviso, "sbloccato" al primo tocco (richiesto da iOS).
  let audioCtx = null;
  function ensureAudio() {
    try {
      if (!audioCtx) {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (Ctx) audioCtx = new Ctx();
      }
      if (audioCtx && audioCtx.state === "suspended") audioCtx.resume();
    } catch (e) { /* ignora */ }
    return audioCtx;
  }
  function beep(freq = 880, dur = 0.35, vol = 0.5) {
    const ctx = ensureAudio();
    if (!ctx) return;
    try {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(vol, ctx.currentTime + 0.03);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + dur);
      osc.connect(gain).connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + dur + 0.05);
    } catch (e) { /* ignora */ }
  }

  // Beep ripetuto finche' il bimbo si muove.
  let beepTimer = null;
  let soundOn = true;
  function startBeeping() {
    if (beepTimer || !soundOn) return;
    beep();
    beepTimer = setInterval(() => beep(), 1200);
  }
  function stopBeeping() {
    if (beepTimer) { clearInterval(beepTimer); beepTimer = null; }
  }

  // ---- simbolo "il bimbo si muove" (tempo reale) ---------------------
  const videoCard = document.querySelector(".video-card");
  function setMotionActive(active) {
    motionBadge.classList.toggle("hidden", !active);
    if (videoCard) videoCard.classList.toggle("motion", active);
    if (active && motionToggle.checked) {
      startBeeping();
      if (navigator.vibrate) navigator.vibrate(200);
    } else {
      stopBeeping();
    }
  }

  // ---- tieni lo schermo acceso mentre fai da monitor ------------------
  // (utile quando ti porti il dispositivo in giro per casa)
  let wakeLock = null;
  async function keepScreenAwake() {
    try {
      if ("wakeLock" in navigator && document.visibilityState === "visible") {
        wakeLock = await navigator.wakeLock.request("screen");
        wakeLock.addEventListener("release", () => { wakeLock = null; });
      }
    } catch (e) { /* alcuni browser lo negano finche' non tocchi lo schermo */ }
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") keepScreenAwake();
  });

  // Notifica del browser sul nuovo movimento (utile se sei su un'altra scheda).
  function notifyMotion() {
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification("👶 Il bimbo si è mosso!", {
        body: new Date().toLocaleTimeString("it-IT"),
        tag: "baby-motion",
      });
    }
  }

  // ---- stato ----------------------------------------------------------
  function applyStatus(s) {
    if (s.connected) {
      statusPill.textContent = "Camera connessa";
      statusPill.className = "pill pill--on";
    } else {
      statusPill.textContent = "Camera offline";
      statusPill.className = "pill pill--off";
    }
    motionToggle.checked = !!s.motion_enabled;
    motionCount.textContent = (s.motion_count || 0) + " rilevamenti";
    if (typeof s.sensitivity === "number") {
      sensitivity.value = s.sensitivity;
      sensValue.textContent = s.sensitivity;
    }
    setMotionActive(!!s.active && !!s.motion_enabled);
  }

  // ---- avviso "fuori portata" (collegamento col cervello perso) -------
  let linkLost = false;
  let lostBeepTimer = null;
  function setLinkLost(lost) {
    if (lost === linkLost) return;
    linkLost = lost;
    offlineBanner.classList.toggle("hidden", !lost);
    if (lost) {
      // suono discendente ripetuto, diverso dall'allarme movimento
      const warn = () => { beep(440, 0.5, 0.5); setTimeout(() => beep(300, 0.5, 0.5), 250); };
      warn();
      lostBeepTimer = setInterval(warn, 5000);
      if (navigator.vibrate) navigator.vibrate([300, 150, 300]);
    } else {
      clearInterval(lostBeepTimer);
      lostBeepTimer = null;
    }
  }

  // ---- eventi in tempo reale (SSE) -----------------------------------
  function connectEvents() {
    const es = new EventSource("events");
    es.onopen = () => setLinkLost(false);
    es.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      setLinkLost(false);
      if (msg.type === "status") applyStatus(msg.data);
      else if (msg.type === "motion_state") {
        // inizio/fine movimento in tempo reale -> simbolo + beep
        setMotionActive(!!msg.data.active && motionToggle.checked);
        if (typeof msg.data.count === "number") {
          motionCount.textContent = msg.data.count + " rilevamenti";
        }
      } else if (msg.type === "motion") {
        motionCount.textContent = (msg.data.count || 0) + " rilevamenti";
        if (motionToggle.checked) notifyMotion();
      }
    };
    es.onerror = () => {
      statusPill.textContent = "Riconnessione…";
      statusPill.className = "pill pill--off";
      // Il collegamento col cervello e' caduto (WiFi fuori portata o cervello
      // spento). EventSource riprova da solo; intanto avvisiamo.
      setLinkLost(true);
    };
  }

  // ---- comandi movimento ---------------------------------------------
  async function postMotion(body) {
    try {
      const r = await fetch("api/motion", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      applyStatus(await r.json());
    } catch (e) { /* offline temporaneo */ }
  }
  motionToggle.onchange = () => {
    if (!motionToggle.checked) setMotionActive(false);
    postMotion({ enabled: motionToggle.checked });
  };
  sensitivity.oninput = () => { sensValue.textContent = sensitivity.value; };
  sensitivity.onchange = () => postMotion({ sensitivity: parseInt(sensitivity.value, 10) });

  // ---- ninna nanne ----------------------------------------------------
  let currentBtn = null;
  async function loadLullabies() {
    const list = $("lullaby-list");
    try {
      const r = await fetch("api/lullabies");
      const items = await r.json();
      list.innerHTML = "";
      if (!items.length) {
        list.innerHTML = '<div class="empty">Nessuna ninna nanna.<br>Tocca "Aggiungi ninna nanna" qui sotto.</div>';
        return;
      }
      for (const item of items) {
        const row = document.createElement("div");
        row.className = "lullaby-row";
        const btn = document.createElement("button");
        btn.className = "lullaby-item";
        btn.innerHTML = '<span class="ico">🎵</span><span>' + escapeHtml(item.title) + "</span>";
        btn.onclick = () => playLullaby(item, btn);
        const del = document.createElement("button");
        del.className = "lullaby-del";
        del.textContent = "🗑";
        del.title = "Elimina";
        del.onclick = async () => {
          if (!confirm('Eliminare "' + item.title + '"?')) return;
          await fetch("api/lullabies/" + encodeURIComponent(item.name), { method: "DELETE" }).catch(() => {});
          loadLullabies();
        };
        row.appendChild(btn);
        row.appendChild(del);
        list.appendChild(row);
      }
    } catch (e) {
      list.innerHTML = '<div class="empty">Impossibile caricare le ninna nanne.</div>';
    }
  }

  // Caricamento di nuove ninna nanne dalla webapp.
  const uploadInput = $("lullaby-upload");
  if (uploadInput) {
    uploadInput.onchange = async (ev) => {
      for (const f of ev.target.files) {
        const fd = new FormData();
        fd.append("file", f);
        await fetch("api/lullabies/upload", { method: "POST", body: fd }).catch(() => {});
      }
      uploadInput.value = "";
      loadLullabies();
    };
  }

  // Pulsante impostazioni: riapre il wizard di configurazione.
  const settingsBtn = $("settings-btn");
  if (settingsBtn && window.BabyWizard) {
    settingsBtn.onclick = () => window.BabyWizard.open();
  }

  // Pulsante suono: accende/spegne il beep di avviso.
  const soundBtn = $("sound-btn");
  if (soundBtn) {
    soundBtn.onclick = () => {
      soundOn = !soundOn;
      soundBtn.textContent = soundOn ? "🔔" : "🔕";
      if (!soundOn) stopBeeping();
      else ensureAudio();
    };
  }

  // Pulsante QR: mostra l'indirizzo per aprire l'app su un altro dispositivo.
  const qrBtn = $("qr-btn");
  const qrModal = $("qr-modal");
  async function showQr() {
    const holder = $("qr-holder");
    const urlBox = $("qr-url");
    holder.innerHTML = '<img src="qr.svg?' + Date.now() + '" alt="QR" onerror="this.style.display=\'none\'">';
    try {
      const info = await (await fetch("api/url")).json();
      urlBox.textContent = info.url || "";
      if (!info.qr) holder.innerHTML = '<p class="hint">Installa il modulo <code>qrcode</code> per il QR.</p>';
    } catch (e) { urlBox.textContent = ""; }
    qrModal.classList.remove("hidden");
  }
  if (qrBtn) qrBtn.onclick = showQr;
  if ($("qr-close")) $("qr-close").onclick = () => qrModal.classList.add("hidden");

  function playLullaby(item, btn) {
    player.src = "lullabies/" + encodeURIComponent(item.name);
    player.loop = loopToggle.checked;
    player.play().catch(() => {});
    npTitle.textContent = "In riproduzione: " + item.title;
    nowPlaying.classList.remove("hidden");
    if (currentBtn) currentBtn.classList.remove("playing");
    currentBtn = btn;
    btn.classList.add("playing");
  }

  loopToggle.onchange = () => { player.loop = loopToggle.checked; };
  $("stop-btn").onclick = () => {
    player.pause();
    player.currentTime = 0;
    nowPlaying.classList.add("hidden");
    if (currentBtn) currentBtn.classList.remove("playing");
    currentBtn = null;
  };
  player.onended = () => {
    if (!player.loop) {
      nowPlaying.classList.add("hidden");
      if (currentBtn) currentBtn.classList.remove("playing");
    }
  };

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ---- avvio ----------------------------------------------------------
  // Al primo tocco: sblocca l'audio (richiesto da iOS) e chiede le notifiche.
  document.body.addEventListener("click", function armOnce() {
    ensureAudio();
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
    document.body.removeEventListener("click", armOnce);
  }, { once: true });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }

  // Al primo avvio (camera non configurata) parte il wizard guidato.
  if (window.BabyWizard) window.BabyWizard.maybeStart();

  keepScreenAwake();
  connectEvents();
  loadLullabies();
  // Aggiorna lo stato periodicamente come rete di sicurezza; se la richiesta
  // fallisce, siamo probabilmente fuori portata.
  setInterval(() => {
    fetch("api/status")
      .then((r) => r.json())
      .then((s) => { setLinkLost(false); applyStatus(s); })
      .catch(() => setLinkLost(true));
  }, 10000);
})();
