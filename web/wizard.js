/* Wizard di prima configurazione del Baby Monitor.
 * Guida l'utente in pochi passi: trova la camera, prova il collegamento,
 * regola la sensibilita', carica le ninna nanne. Nessun file da modificare.
 *
 * Espone window.BabyWizard.maybeStart() e window.BabyWizard.open().
 */

(() => {
  "use strict";

  const root = document.getElementById("wizard");
  let cam = { ip: "", rtsp_port: 554, username: "admin", password: "", stream: "sub", rtsp_url: "" };
  let step = 0;
  let onDone = null;

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function show() { root.classList.remove("hidden"); render(); }
  function close() { root.classList.add("hidden"); root.innerHTML = ""; }

  async function api(path, opts) {
    const r = await fetch(path, opts);
    return r.json();
  }

  // ---- passi -----------------------------------------------------------
  const steps = [stepWelcome, stepCamera, stepTest, stepSensitivity, stepLullabies, stepDone];

  function render() {
    root.innerHTML =
      '<div class="wiz-box">' +
      '<div class="wiz-progress">Passo ' + (step + 1) + ' di ' + steps.length + '</div>' +
      '<div class="wiz-content"></div>' +
      '</div>';
    steps[step](root.querySelector(".wiz-content"));
  }

  function go(n) { step = Math.max(0, Math.min(steps.length - 1, n)); render(); }

  function nav(el, { back = true, next = null, nextLabel = "Avanti →", nextDisabled = false } = {}) {
    const bar = document.createElement("div");
    bar.className = "wiz-nav";
    if (back && step > 0) {
      const b = document.createElement("button");
      b.className = "btn btn--ghost";
      b.textContent = "← Indietro";
      b.onclick = () => go(step - 1);
      bar.appendChild(b);
    } else {
      bar.appendChild(document.createElement("span"));
    }
    if (next) {
      const n = document.createElement("button");
      n.className = "btn btn--primary";
      n.textContent = nextLabel;
      n.disabled = nextDisabled;
      n.onclick = next;
      bar.appendChild(n);
    }
    el.appendChild(bar);
  }

  // 1) Benvenuto
  function stepWelcome(el) {
    el.innerHTML =
      '<div class="wiz-emoji">👶</div>' +
      '<h2>Benvenuto nel Baby Monitor</h2>' +
      '<p>Configuriamo tutto in pochi passi. Assicurati che nell\'app <b>Yoosee</b> ' +
      'sia attivo <b>ONVIF</b> e che la camera sia accesa sulla stessa rete WiFi.</p>';
    nav(el, { back: false, next: () => go(1), nextLabel: "Iniziamo →" });
  }

  // 2) Trova / inserisci la camera
  function stepCamera(el) {
    el.innerHTML =
      '<h2>📷 Trova la camera</h2>' +
      '<button id="wiz-scan" class="btn btn--primary wiz-full">🔍 Cerca camera in rete</button>' +
      '<div id="wiz-found" class="wiz-found"></div>' +
      '<p class="wiz-or">oppure inserisci i dati a mano</p>' +
      '<label>Indirizzo IP<input id="wiz-ip" inputmode="decimal" placeholder="192.168.1.100" value="' + esc(cam.ip) + '"></label>' +
      '<label>Utente<input id="wiz-user" value="' + esc(cam.username) + '"></label>' +
      '<label>Password<input id="wiz-pass" type="password" value="' + esc(cam.password) + '"></label>' +
      '<label>Qualità video' +
      '<select id="wiz-stream">' +
      '<option value="sub"' + (cam.stream === "sub" ? " selected" : "") + '>Leggera (consigliata)</option>' +
      '<option value="main"' + (cam.stream === "main" ? " selected" : "") + '>Alta qualità</option>' +
      '</select></label>';

    const collect = () => {
      cam.ip = el.querySelector("#wiz-ip").value.trim();
      cam.username = el.querySelector("#wiz-user").value.trim();
      cam.password = el.querySelector("#wiz-pass").value;
      cam.stream = el.querySelector("#wiz-stream").value;
    };

    el.querySelector("#wiz-scan").onclick = async (ev) => {
      const btn = ev.target;
      btn.disabled = true; btn.textContent = "⏳ Cerco...";
      const box = el.querySelector("#wiz-found");
      try {
        const res = await api("api/setup/discover", { method: "POST" });
        if (res.cameras && res.cameras.length) {
          box.innerHTML = res.cameras.map((ip) =>
            '<button class="wiz-cam" data-ip="' + esc(ip) + '">📷 ' + esc(ip) + '</button>').join("");
          box.querySelectorAll(".wiz-cam").forEach((b) => {
            b.onclick = () => { el.querySelector("#wiz-ip").value = b.dataset.ip; };
          });
        } else {
          box.innerHTML = '<p class="wiz-warn">Nessuna camera trovata. Inserisci l\'IP a mano (lo trovi nel router o nell\'app Yoosee).</p>';
        }
      } catch (e) {
        box.innerHTML = '<p class="wiz-warn">Ricerca non riuscita. Inserisci l\'IP a mano.</p>';
      } finally {
        btn.disabled = false; btn.textContent = "🔍 Cerca camera in rete";
      }
    };

    nav(el, {
      next: () => { collect(); if (!cam.ip) { alert("Inserisci l'indirizzo IP della camera."); return; } go(2); },
    });
  }

  // 3) Prova il collegamento
  function stepTest(el) {
    el.innerHTML =
      '<h2>🔌 Prova il collegamento</h2>' +
      '<p>Verifico che i dati siano corretti e che arrivi il video.</p>' +
      '<div id="wiz-test-result" class="wiz-test"></div>';
    const box = el.querySelector("#wiz-test-result");

    const runTest = async () => {
      box.className = "wiz-test wiz-test--wait";
      box.innerHTML = "⏳ Sto provando a collegarmi alla camera...";
      let res;
      try {
        res = await api("api/setup/test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cam),
        });
      } catch (e) { res = { ok: false, error: "errore di rete" }; }

      if (res.ok) {
        box.className = "wiz-test wiz-test--ok";
        box.innerHTML = "✅ Collegamento riuscito! La camera funziona.";
        nav(el, { next: () => saveAndNext(), nextLabel: "Perfetto, avanti →" });
      } else {
        box.className = "wiz-test wiz-test--err";
        box.innerHTML = "❌ Non riesco a collegarmi.<br><small>" + esc(res.error || "") + "</small>" +
          "<br><small>Controlla IP, utente/password e che ONVIF sia attivo in Yoosee.</small>";
        const retry = document.createElement("button");
        retry.className = "btn btn--primary wiz-full";
        retry.textContent = "🔄 Riprova";
        retry.onclick = runTest;
        box.appendChild(retry);
        nav(el, { next: null });
      }
    };

    const saveAndNext = async () => {
      box.innerHTML = "💾 Salvo la configurazione...";
      await api("api/setup/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cam),
      });
      go(3);
    };

    runTest();
  }

  // 4) Sensibilita' (con anteprima video)
  function stepSensitivity(el) {
    el.innerHTML =
      '<h2>🎚️ Sensibilità del movimento</h2>' +
      '<div class="wiz-preview"><img id="wiz-video" src="stream.mjpg?' + Date.now() + '" alt="anteprima"></div>' +
      '<p>Più alta = nota anche piccoli movimenti. Più bassa = meno falsi allarmi.</p>' +
      '<input type="range" id="wiz-sens" min="1" max="100" value="55">' +
      '<div class="range-hints"><span>Meno falsi allarmi</span><span id="wiz-sens-val">55</span><span>Più sensibile</span></div>';
    const s = el.querySelector("#wiz-sens");
    const v = el.querySelector("#wiz-sens-val");
    s.oninput = () => { v.textContent = s.value; };
    s.onchange = () => api("api/motion", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sensitivity: parseInt(s.value, 10) }),
    }).catch(() => {});
    nav(el, { next: () => go(4) });
  }

  // 5) Ninna nanne
  function stepLullabies(el) {
    el.innerHTML =
      '<h2>🎵 Ninna nanne</h2>' +
      '<p>Carica 4-5 brani (facoltativo, puoi farlo anche dopo).</p>' +
      '<label class="btn btn--primary wiz-full" for="wiz-lull-file">➕ Carica file audio</label>' +
      '<input type="file" id="wiz-lull-file" accept="audio/*" multiple hidden>' +
      '<div id="wiz-lull-list" class="wiz-found"></div>';
    const list = el.querySelector("#wiz-lull-list");

    async function refresh() {
      const items = await api("api/lullabies");
      list.innerHTML = items.length
        ? items.map((i) => '<div class="wiz-lull">🎵 ' + esc(i.title) + '</div>').join("")
        : '<p class="hint">Nessuna ninna nanna ancora.</p>';
    }
    el.querySelector("#wiz-lull-file").onchange = async (ev) => {
      for (const f of ev.target.files) {
        const fd = new FormData(); fd.append("file", f);
        await fetch("api/lullabies/upload", { method: "POST", body: fd }).catch(() => {});
      }
      refresh();
    };
    refresh();
    nav(el, { next: () => go(5), nextLabel: "Fine →" });
  }

  // 6) Fatto
  function stepDone(el) {
    el.innerHTML =
      '<div class="wiz-emoji">🎉</div>' +
      '<h2>Tutto pronto!</h2>' +
      '<p>Il baby monitor è configurato. Tieni la webapp aperta per ricevere ' +
      'i popup quando il bimbo si muove.</p>';
    const done = document.createElement("button");
    done.className = "btn btn--primary wiz-full";
    done.textContent = "Apri il monitor";
    done.onclick = () => { close(); if (onDone) onDone(); };
    el.appendChild(done);
  }

  // ---- API pubblica ----------------------------------------------------
  window.BabyWizard = {
    open(cb) { onDone = cb || (() => window.location.reload()); step = 0; show(); },
    async maybeStart(cb) {
      try {
        const st = await api("api/setup/status");
        if (st.camera) {
          cam.ip = st.camera.ip && st.camera.ip !== "192.168.1.100" ? st.camera.ip : "";
          cam.rtsp_port = st.camera.rtsp_port || 554;
          cam.username = st.camera.username || "admin";
          cam.stream = st.camera.stream || "sub";
        }
        if (!st.configured) { this.open(cb); return true; }
      } catch (e) { /* se non risponde, ci pensa app.js */ }
      return false;
    },
  };
})();
