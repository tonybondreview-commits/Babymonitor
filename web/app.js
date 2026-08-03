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
  const alertBox = $("alert");
  const alertTime = $("alert-time");
  const player = $("player");
  const nowPlaying = $("now-playing");
  const npTitle = $("np-title");
  const loopToggle = $("loop-toggle");

  let alarmOsc = null; // suono d'allarme generato via WebAudio (nessun file)

  // ---- video live -----------------------------------------------------
  video.src = "stream.mjpg";
  video.onerror = () => setTimeout(() => { video.src = "stream.mjpg?" + Date.now(); }, 3000);

  // ---- suono d'allarme (beep sintetico, funziona offline) -------------
  function beep() {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.4, ctx.currentTime + 0.05);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.8);
      osc.connect(gain).connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.85);
    } catch (e) { /* ignora */ }
  }

  // ---- popup di allarme ----------------------------------------------
  function showAlert() {
    const now = new Date();
    alertTime.textContent = "Ore " + now.toLocaleTimeString("it-IT");
    alertBox.classList.remove("hidden");
    beep(); setTimeout(beep, 900); setTimeout(beep, 1800);
    if (navigator.vibrate) navigator.vibrate([200, 100, 200]);

    // Notifica del browser (utile se sei su un'altra scheda, app aperta).
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification("👶 Il bimbo si è mosso!", {
        body: now.toLocaleTimeString("it-IT"),
        tag: "baby-motion",
      });
    }
  }
  $("alert-dismiss").onclick = () => alertBox.classList.add("hidden");

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
    motionBadge.classList.toggle("hidden", !s.active);
  }

  // ---- eventi in tempo reale (SSE) -----------------------------------
  function connectEvents() {
    const es = new EventSource("events");
    es.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === "status") applyStatus(msg.data);
      else if (msg.type === "motion") {
        motionCount.textContent = (msg.data.count || 0) + " rilevamenti";
        if (motionToggle.checked) showAlert();
      }
    };
    es.onerror = () => {
      statusPill.textContent = "Riconnessione…";
      statusPill.className = "pill pill--off";
      // EventSource riprova da solo; forziamo comunque un refresh stato.
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
  motionToggle.onchange = () => postMotion({ enabled: motionToggle.checked });
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
        list.innerHTML = '<div class="empty">Nessuna ninna nanna.<br>Metti dei file audio nella cartella <code>lullabies/</code>.</div>';
        return;
      }
      for (const item of items) {
        const btn = document.createElement("button");
        btn.className = "lullaby-item";
        btn.innerHTML = '<span class="ico">🎵</span><span>' + escapeHtml(item.title) + "</span>";
        btn.onclick = () => playLullaby(item, btn);
        list.appendChild(btn);
      }
    } catch (e) {
      list.innerHTML = '<div class="empty">Impossibile caricare le ninna nanne.</div>';
    }
  }

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
  // Chiediamo il permesso notifiche al primo tocco (richiesto da iOS).
  document.body.addEventListener("click", function askOnce() {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
    document.body.removeEventListener("click", askOnce);
  }, { once: true });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }

  connectEvents();
  loadLullabies();
  // Aggiorna lo stato periodicamente come rete di sicurezza.
  setInterval(() => fetch("api/status").then((r) => r.json()).then(applyStatus).catch(() => {}), 10000);
})();
