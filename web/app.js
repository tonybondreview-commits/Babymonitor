/* Baby Monitor - logica della webapp (PWA).
 * Tutto in locale: si collega al "cervello" sulla rete di casa. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const video = $("video");
  const statusPill = $("status-pill");
  const statusText = $("status-text");
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
  const beepAudio = $("beep-audio");
  const videoCard = $("video-card");

  // ---- video live -----------------------------------------------------
  function reloadVideo() { video.src = "stream.mjpg?" + Date.now(); }
  reloadVideo();
  video.onerror = () => setTimeout(reloadVideo, 3000);
  // Quando torni sull'app (o la riapri), lo stream MJPEG puo' essere caduto:
  // lo ricarichiamo cosi' rivedi il video senza dover aggiornare a mano.
  window.addEventListener("pageshow", reloadVideo);

  // ---- suono d'allarme (file audio: affidabile anche su iPhone) -------
  let soundOn = true;
  function unlockAudio() {
    // iOS: il primo play va fatto durante un tocco per "sbloccare" l'audio.
    try {
      const p = beepAudio.play();
      if (p) p.then(() => { beepAudio.pause(); beepAudio.currentTime = 0; }).catch(() => {});
    } catch (e) { /* ignora */ }
  }
  function startBeeping() {
    if (!soundOn) return;
    try { beepAudio.loop = true; beepAudio.currentTime = 0; beepAudio.play().catch(() => {}); } catch (e) {}
  }
  function stopBeeping() {
    try { beepAudio.loop = false; beepAudio.pause(); beepAudio.currentTime = 0; } catch (e) {}
  }
  function testBeep() {
    try { beepAudio.loop = false; beepAudio.currentTime = 0; beepAudio.play().catch(() => {}); } catch (e) {}
  }

  // ---- simbolo "il bimbo si muove" (tempo reale) ---------------------
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

  // ---- schermo intero (stile player) ---------------------------------
  const fsBtn = $("fs-btn");
  function enterFs(gesture) {
    videoCard.classList.add("fs");
    document.body.classList.add("fs-open");
    if (fsBtn) fsBtn.textContent = "✕";
    // Android: se e' un tocco, prova a bloccare in orizzontale (iOS lo ignora).
    if (gesture) {
      try {
        if (screen.orientation && screen.orientation.lock) {
          screen.orientation.lock("landscape").catch(() => {});
        }
      } catch (e) { /* iOS non lo supporta */ }
    }
  }
  function exitFs() {
    videoCard.classList.remove("fs");
    document.body.classList.remove("fs-open");
    if (fsBtn) fsBtn.textContent = "⛶";
    try { if (screen.orientation && screen.orientation.unlock) screen.orientation.unlock(); } catch (e) {}
  }
  function toggleFs() {
    if (videoCard.classList.contains("fs")) exitFs(); else enterFs(true);
  }
  if (fsBtn) fsBtn.onclick = toggleFs;
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && videoCard.classList.contains("fs")) exitFs();
  });

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
    if (document.visibilityState === "visible") { keepScreenAwake(); reloadVideo(); }
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
  function setStatus(text, ok) {
    if (statusText) statusText.textContent = text;
    statusPill.className = "pill " + (ok ? "pill--on" : "pill--off");
  }
  function applyStatus(s) {
    setStatus(s.connected ? "Camera connessa" : "Camera offline", s.connected);
    motionToggle.checked = !!s.motion_enabled;
    motionCount.textContent = (s.motion_count || 0) + " rilevamenti";
    if (typeof s.sensitivity === "number") {
      sensitivity.value = s.sensitivity;
      sensValue.textContent = s.sensitivity;
    }
    setMotionActive(!!s.active && !!s.motion_enabled);
    if (s.quality) setQualityUI(s.quality);
  }

  // ---- qualità video --------------------------------------------------
  const qualitySeg = $("quality-seg");
  function setQualityUI(q) {
    if (!qualitySeg) return;
    qualitySeg.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.q === q));
  }
  if (qualitySeg) {
    qualitySeg.querySelectorAll("button").forEach((b) => {
      b.onclick = async () => {
        setQualityUI(b.dataset.q);
        try {
          await fetch("api/quality", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ quality: b.dataset.q }),
          });
        } catch (e) { /* ignora */ }
        setTimeout(reloadVideo, 1600);  // la camera si riavvia con la nuova qualità
      };
    });
  }

  // ---- avviso "fuori portata" (collegamento col cervello perso) -------
  let linkLost = false;
  let lostBeepTimer = null;
  function setLinkLost(lost) {
    if (lost === linkLost) return;
    linkLost = lost;
    offlineBanner.classList.toggle("hidden", !lost);
    if (lost) {
      stopBeeping();               // il movimento non e' piu' affidabile
      testBeep();                  // un suono per avvisare della disconnessione
      lostBeepTimer = setInterval(testBeep, 5000);
      if (navigator.vibrate) navigator.vibrate([300, 150, 300]);
      setStatus("Riconnessione…", false);
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

  // ---- ascolta l'audio della camera (senti il bimbo) -----------------
  const listenBtn = $("listen-btn");
  const audioBtn = $("audio-btn");   // stesso comando, sovrapposto al video
  const camAudio = $("cam-audio");
  let listening = false;
  function setListening(on) {
    listening = on;
    if (on) {
      camAudio.muted = false;
      camAudio.volume = 1;
      camAudio.src = "audio.mp3?" + Date.now();
      camAudio.play().catch((e) => { console.log("audio play:", e); });
    } else {
      camAudio.pause();
      camAudio.removeAttribute("src");
      camAudio.load();
    }
    if (listenBtn) {
      listenBtn.textContent = on ? "🔇 Ascolto attivo — tocca per fermare" : "🔊 Ascolta l'audio della camera";
      listenBtn.classList.toggle("on", on);
    }
    if (audioBtn) {
      audioBtn.textContent = on ? "🔇" : "🔊";
      audioBtn.classList.toggle("on", on);
    }
  }
  if (camAudio) {
    // Mostriamo sempre il tasto: se la camera non avesse audio, resta muto.
    if (listenBtn) { listenBtn.onclick = () => setListening(!listening); listenBtn.classList.remove("hidden"); }
    if (audioBtn) { audioBtn.onclick = () => setListening(!listening); audioBtn.classList.remove("hidden"); }
  }

  // ---- PTZ (muovi la camera) -----------------------------------------
  const ptzToggle = $("ptz-toggle");
  const ptzPad = $("ptz-pad");
  async function ptzCmd(action) {
    try {
      await fetch("api/ptz", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) });
    } catch (e) { /* ignora */ }
  }
  if (ptzToggle && ptzPad) {
    ptzToggle.onclick = () => {
      const show = ptzPad.classList.toggle("hidden") === false;
      ptzToggle.classList.toggle("on", show);
    };
    ptzPad.querySelectorAll(".ptz-btn").forEach((b) => {
      const dir = b.dataset.dir;
      const start = (e) => { e.preventDefault(); ptzCmd(dir); };
      const end = () => ptzCmd("stop");
      b.addEventListener("pointerdown", start);
      b.addEventListener("pointerup", end);
      b.addEventListener("pointerleave", end);
      b.addEventListener("pointercancel", end);
    });
    // Mostra il joystick solo se la camera supporta davvero il PTZ.
    fetch("api/ptz/available").then((r) => r.json()).then((j) => {
      if (j.available) ptzToggle.classList.remove("hidden");
    }).catch(() => {});
  }

  // Interruttore "Suono di avviso" + pulsante "Prova".
  const soundToggle = $("sound-toggle");
  if (soundToggle) {
    soundToggle.onchange = () => {
      soundOn = soundToggle.checked;
      if (!soundOn) stopBeeping(); else testBeep();
    };
  }
  const soundTest = $("sound-test");
  if (soundTest) soundTest.onclick = () => {
    soundOn = true;
    if (soundToggle) soundToggle.checked = true;
    testBeep();
  };

  // Modo notte (tema chiaro/scuro), ricordato sul dispositivo.
  const themeBtn = $("theme-btn");
  function applyTheme(night) {
    document.body.classList.toggle("night", night);
    if (themeBtn) themeBtn.textContent = night ? "☀️" : "🌙";
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", night ? "#171520" : "#fbf7f2");
  }
  let nightMode = false;
  try { nightMode = localStorage.getItem("bm-theme") === "night"; } catch (e) {}
  applyTheme(nightMode);
  if (themeBtn) themeBtn.onclick = () => {
    nightMode = !nightMode;
    applyTheme(nightMode);
    try { localStorage.setItem("bm-theme", nightMode ? "night" : "light"); } catch (e) {}
  };

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
    unlockAudio();
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
    document.body.removeEventListener("click", armOnce);
  }, { once: true });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }

  // Al primo avvio parte il wizard; se la camera e' gia' configurata, apri
  // subito il video a schermo pieno (stile monitor).
  (async () => {
    let wizardShown = false;
    if (window.BabyWizard) wizardShown = await window.BabyWizard.maybeStart();
    if (!wizardShown) setTimeout(() => enterFs(false), 400);
  })();

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
