/* Service worker minimale: rende installabile la PWA, ma NON mette nulla in
 * cache. Cosi' l'app e' sempre aggiornata (niente versioni "vecchie") e non
 * appare mai la pagina rotta con il "?". Il baby monitor funziona comunque
 * solo quando il cervello e' raggiungibile sulla rete, quindi la cache offline
 * non servirebbe. */

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    // Cancella ogni vecchia cache lasciata dalle versioni precedenti.
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

// Nessun handler "fetch" che intercetta: ogni richiesta va direttamente in
// rete, quindi si carica sempre la versione piu' recente.
