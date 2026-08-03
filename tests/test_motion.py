"""Test del cuore del rilevamento movimento (senza camera reale).

Simuliamo fotogrammi in scala di grigi come array numpy. Un movimento reale
si simula spostando un blocco chiaro ad ogni fotogramma (cosi' ci sono
differenze frame-to-frame, come da una camera vera).
"""

import numpy as np
import pytest

from babymonitor.motion import MotionDetector, sensitivity_to_params


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def still(value=100, size=64):
    return np.full((size, size), value, dtype=np.uint8)


def frame_with_block(pos, size=64, block=18, value=240, bg=100):
    """Fotogramma con un blocco chiaro alla posizione 'pos' (bimbo che si muove)."""
    img = np.full((size, size), bg, dtype=np.uint8)
    p = max(0, min(size - block, pos))
    img[20:20 + block, p:p + block] = value
    return img


def feed(det, frame, n):
    last = None
    for _ in range(n):
        last = det.update(frame)
    return last


def feed_moving(det, n, start=2, step=4):
    """Alimenta n fotogrammi con il blocco che si sposta (movimento continuo)."""
    last = None
    events = 0
    for i in range(n):
        last = det.update(frame_with_block(start + i * step))
        if last.motion:
            events += 1
    return last, events


def test_sensitivity_mapping_monotonic():
    thr_low, area_low = sensitivity_to_params(5)
    thr_high, area_high = sensitivity_to_params(95)
    # Piu' sensibile -> soglia e area minima piu' basse.
    assert thr_high < thr_low
    assert area_high < area_low


def test_warmup_no_events():
    det = MotionDetector(sensitivity=80, warmup_frames=10, clock=FakeClock())
    res = feed(det, still(), 10)
    assert res.warming_up is True
    assert res.motion is False


def test_still_scene_no_motion():
    det = MotionDetector(sensitivity=60, warmup_frames=5, clock=FakeClock())
    feed(det, still(120), 6)
    res = feed(det, still(120), 10)
    assert res.motion is False
    assert res.active is False


def test_movement_triggers_event():
    det = MotionDetector(sensitivity=70, warmup_frames=5, consec_frames=3,
                         cooldown=15, clock=FakeClock())
    feed(det, still(100), 6)  # scena ferma
    _, events = feed_moving(det, 6)
    assert events >= 1


def test_motion_clears_when_still():
    det = MotionDetector(sensitivity=70, warmup_frames=5, consec_frames=2,
                         hold_frames=3, cooldown=15, clock=FakeClock())
    feed(det, still(100), 6)
    feed_moving(det, 6)
    # Dopo che il bimbo si ferma, l'allarme deve tornare inattivo.
    res = feed(det, still(100), 5)
    assert res.active is False


def test_cooldown_prevents_repeat():
    clock = FakeClock()
    det = MotionDetector(sensitivity=70, warmup_frames=5, consec_frames=2,
                         hold_frames=3, cooldown=15, clock=clock)
    feed(det, still(100), 6)

    # Primo movimento -> 1 evento.
    _, e1 = feed_moving(det, 6)
    feed(det, still(100), 5)  # si ferma (l'allarme si azzera)
    assert e1 == 1

    # Nuovo movimento entro il cooldown -> nessun nuovo evento.
    clock.advance(2)
    _, e2 = feed_moving(det, 6, start=2)
    feed(det, still(100), 5)
    assert e2 == 0

    # Passato il cooldown -> puo' riscattare.
    clock.advance(20)
    _, e3 = feed_moving(det, 6, start=2)
    assert e3 == 1


def test_update_rejects_non_2d():
    det = MotionDetector()
    with pytest.raises(ValueError):
        det.update(np.zeros((10, 10, 3), dtype=np.uint8))
