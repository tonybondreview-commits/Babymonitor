"""Rilevamento del movimento.

Il "cuore" dell'algoritmo lavora su fotogrammi gia' in scala di grigi
(array numpy 2D uint8), cosi' e' testabile senza avere una camera reale.
La conversione video -> grigi + sfocatura viene fatta in camera.py con OpenCV.

Tecnica: differenza tra il fotogramma corrente e quello precedente. Quando il
bimbo si muove, molti pixel cambiano e la "frazione di immagine cambiata"
sale; appena si ferma, torna a zero. E' la scelta piu' adatta a un baby
monitor, che deve avvisare *appena* si muove.

Per evitare falsi allarmi:
  - si contano solo i pixel che cambiano oltre una soglia (rumore escluso);
  - serve movimento per alcuni fotogrammi consecutivi (consec_frames);
  - dopo un allarme parte un "cooldown" che evita raffiche di notifiche.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np


@dataclass
class MotionResult:
    """Esito dell'analisi di un singolo fotogramma."""
    motion: bool          # True solo nell'istante in cui scatta un nuovo evento
    active: bool          # True finche' c'e' movimento in corso
    ratio: float          # frazione di immagine cambiata (0..1)
    warming_up: bool      # True finche' non ci sono abbastanza fotogrammi


def sensitivity_to_params(sensitivity: int) -> tuple[int, float]:
    """Converte una sensibilita' 1..100 in (soglia_pixel, area_minima).

    Sensibilita' alta -> soglia pixel bassa e area minima piccola
    (si accorge anche di movimenti piccoli). Sensibilita' bassa -> serve un
    movimento ampio per far scattare l'allarme (meno falsi positivi).
    """
    s = max(1, min(100, int(sensitivity)))
    pixel_threshold = int(round(60 - 0.45 * s))          # ~55 (bassa) .. ~15 (alta)
    pixel_threshold = max(12, min(60, pixel_threshold))
    min_area_ratio = ((101 - s) / 100.0) * 0.06          # ~0.06 (bassa) .. ~0.0006 (alta)
    min_area_ratio = max(0.0008, min(0.06, min_area_ratio))
    return pixel_threshold, min_area_ratio


class MotionDetector:
    """Rileva il movimento confrontando fotogrammi consecutivi."""

    def __init__(
        self,
        sensitivity: int = 55,
        cooldown: float = 15.0,
        consec_frames: int = 3,
        warmup_frames: int = 15,
        hold_frames: int = 5,
        clock=time.monotonic,
    ):
        self.pixel_threshold, self.min_area_ratio = sensitivity_to_params(sensitivity)
        self.cooldown = cooldown
        self.consec_frames = max(1, consec_frames)
        self.warmup_frames = max(1, warmup_frames)
        # Per quanti fotogrammi "fermi" il movimento resta considerato attivo,
        # cosi' l'allarme non lampeggia tra un fotogramma e l'altro.
        self.hold_frames = max(1, hold_frames)
        self._clock = clock
        self.reset()

    def reset(self) -> None:
        self._prev: np.ndarray | None = None
        self._frames_seen = 0
        self._hot_streak = 0        # fotogrammi consecutivi con movimento
        self._idle_frames = 0       # fotogrammi consecutivi senza movimento
        self._event_active = False  # allarme in corso (latch)
        self._last_event = -1e9

    def update(self, gray: np.ndarray) -> MotionResult:
        """Analizza un fotogramma in scala di grigi (2D, uint8)."""
        if gray.ndim != 2:
            raise ValueError("update() vuole un fotogramma 2D in scala di grigi")
        g = gray.astype(np.int16)
        self._frames_seen += 1

        if self._prev is None:
            self._prev = g
            return MotionResult(False, False, 0.0, warming_up=True)

        diff = np.abs(g - self._prev)
        changed = diff > self.pixel_threshold
        ratio = float(changed.mean())
        self._prev = g

        if self._frames_seen <= self.warmup_frames:
            return MotionResult(False, False, ratio, warming_up=True)

        is_moving = ratio >= self.min_area_ratio
        if is_moving:
            self._hot_streak += 1
            self._idle_frames = 0
        else:
            self._hot_streak = 0
            self._idle_frames += 1

        # L'allarme resta "attivo" finche' non passano abbastanza fotogrammi fermi.
        active = self._idle_frames < self.hold_frames and (
            self._event_active or self._hot_streak > 0
        )
        if self._idle_frames >= self.hold_frames:
            self._event_active = False

        now = self._clock()
        new_event = False
        if self._hot_streak >= self.consec_frames:
            if not self._event_active and (now - self._last_event) >= self.cooldown:
                new_event = True
                self._last_event = now
            self._event_active = True
            active = True

        return MotionResult(new_event, active, ratio, warming_up=False)
