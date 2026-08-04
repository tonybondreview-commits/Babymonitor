import 'dart:async';
import 'dart:typed_data';
import 'package:image/image.dart' as img;

/// Rilevamento del movimento SUL DISPOSITIVO.
///
/// Ogni ~700ms prende uno "snapshot" del video (dal player), lo riduce in
/// scala di grigi e lo confronta con il precedente: se cambia abbastanza per
/// alcuni scatti consecutivi, segnala il movimento. Nessun cervello esterno.
class MotionDetector {
  final Future<Uint8List?> Function() grabFrame;
  int sensitivity;
  final void Function() onEvent; // nuovo evento (rispetta il cooldown)
  final void Function(bool active) onState;

  MotionDetector({
    required this.grabFrame,
    required this.onEvent,
    required this.onState,
    this.sensitivity = 55,
  });

  Timer? _timer;
  Uint8List? _prev;
  int _w = 0, _h = 0;
  int _hot = 0;
  bool _active = false;
  DateTime _lastEvent = DateTime.fromMillisecondsSinceEpoch(0);
  static const _cooldown = Duration(seconds: 12);
  static const _consec = 2;

  int get _pixelThreshold => (60 - 0.45 * sensitivity).clamp(12, 60).toInt();
  double get _minAreaRatio =>
      ((101 - sensitivity) / 100.0 * 0.06).clamp(0.0008, 0.06);

  void start() {
    stop();
    _timer = Timer.periodic(const Duration(milliseconds: 700), (_) => _tick());
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
    _prev = null;
    _hot = 0;
    if (_active) {
      _active = false;
      onState(false);
    }
  }

  Future<void> _tick() async {
    Uint8List? bytes;
    try {
      bytes = await grabFrame();
    } catch (_) {
      return;
    }
    if (bytes == null || bytes.isEmpty) return;

    final decoded = img.decodeImage(bytes);
    if (decoded == null) return;
    final small = img.copyResize(decoded, width: 96);
    final w = small.width, h = small.height;
    final gray = Uint8List(w * h);
    var i = 0;
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        final p = small.getPixel(x, y);
        gray[i++] =
            ((p.r * 299 + p.g * 587 + p.b * 114) ~/ 1000).clamp(0, 255);
      }
    }

    final prev = _prev;
    _prev = gray;
    _w = w;
    _h = h;
    if (prev == null || prev.length != gray.length) return;

    var changed = 0;
    final thr = _pixelThreshold;
    for (var k = 0; k < gray.length; k++) {
      if ((gray[k] - prev[k]).abs() > thr) changed++;
    }
    final ratio = changed / gray.length;
    final moving = ratio >= _minAreaRatio;

    if (moving) {
      _hot++;
    } else {
      _hot = 0;
      if (_active) {
        _active = false;
        onState(false);
      }
    }

    if (_hot >= _consec) {
      if (!_active && DateTime.now().difference(_lastEvent) >= _cooldown) {
        _lastEvent = DateTime.now();
        onEvent();
      }
      if (!_active) {
        _active = true;
        onState(true);
      }
    }
  }
}
