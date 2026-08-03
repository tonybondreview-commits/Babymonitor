"""Baby Monitor companion app per camere Fredi / Yoosee.

Aggiunge due funzioni a una camera Fredi/Yoosee tramite lo stream RTSP:
  1. Rilevamento del movimento del bimbo -> popup + notifica.
  2. Riproduzione di ninna nanne vicino al bimbo.

Nota: l'app Yoosee e' un sistema chiuso e non modificabile. Questa e' una
applicazione "companion" separata che gira su un PC / Raspberry Pi / vecchio
telefono e si collega alla camera sulla rete locale.
"""

__version__ = "1.0.0"
