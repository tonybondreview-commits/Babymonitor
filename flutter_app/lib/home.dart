import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';
import 'package:vibration/vibration.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import 'config.dart';
import 'main.dart' show kMint, kPeach, kBg, kInk;
import 'motion.dart';
import 'onvif.dart';
import 'rtsp_probe.dart';
import 'setup.dart';

/// Schermata principale: video dal vivo con decoder integrato (media_kit,
/// motore ffmpeg), rilevamento movimento sul dispositivo, PTZ, ascolto audio
/// e ninna nanne.
class HomeScreen extends StatefulWidget {
  final CameraConfig config;
  final VoidCallback onReconfigure;
  const HomeScreen(
      {super.key, required this.config, required this.onReconfigure});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with WidgetsBindingObserver {
  Player? _player;
  VideoController? _video;
  final List<StreamSubscription> _subs = [];
  late OnvifPtz _ptz;
  MotionDetector? _motion;

  final _beep = AudioPlayer();
  final _lullaby = AudioPlayer();

  bool _listening = false; // audio della telecamera attivo?
  bool _motionActive = false; // movimento in corso adesso
  bool _night = false;
  bool _connecting = true;
  bool _error = false;
  String? _playingLullaby;

  // Apertura del flusso: prova varie combinazioni finche' una funziona.
  Timer? _watchdog;
  int _attempt = 0;
  bool _swapping = false;
  String? _errText;
  // trasporto (UDP/TCP) x decodifica (software/hardware). Software prima:
  // e' esattamente il percorso ffmpeg che funzionava su Termux.
  static const _configs = <_PlayCfg>[
    _PlayCfg(false, false), // UDP, software
    _PlayCfg(true, false), // TCP, software
    _PlayCfg(false, true), // UDP, hardware
    _PlayCfg(true, true), // TCP, hardware
  ];
  _PlayCfg get _cfgNow => _configs[_attempt % _configs.length];
  String get _transport => _cfgNow.label;

  // Diagnostica di rete (quando il video non parte).
  String? _diag;
  String? _suggestPath;
  bool _diagRunning = false;

  bool _fullscreen = false;
  bool _searching = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WakelockPlus.enable();
    // Verticale fisso finche' non si tocca "schermo intero".
    SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
    _ptz = OnvifPtz(widget.config);
    _beep.setReleaseMode(ReleaseMode.stop);
    _lullaby.setReleaseMode(ReleaseMode.stop);
    _motion = MotionDetector(
      grabFrame: _grabFrame,
      onEvent: _onMotionEvent,
      onState: (active) {
        if (mounted) setState(() => _motionActive = active);
      },
      sensitivity: widget.config.sensitivity,
    );
    _startPlayer();
  }

  Future<void> _startPlayer() async {
    setState(() {
      _connecting = true;
      _error = false;
      _errText = null;
    });

    final cfg = _cfgNow;
    final player = Player();
    final video = VideoController(player);

    // Opzioni mpv/ffmpeg: stesso motore che funzionava con Termux.
    final dynamic native = player.platform;
    Future<void> setProp(String k, String v) async {
      try {
        await native.setProperty(k, v);
      } catch (_) {}
    }

    await setProp('rtsp-transport', cfg.tcp ? 'tcp' : 'udp');
    await setProp('hwdec', cfg.hw ? 'auto-safe' : 'no');
    await setProp('cache', 'no');
    await setProp('network-timeout', '10');

    _player = player;
    _video = video;

    // Ascolta gli eventi del player.
    _subs.add(player.stream.playing.listen((playing) {
      if (playing) _onConnected();
    }));
    _subs.add(player.stream.width.listen((w) {
      if (w != null && w > 0) _onConnected();
    }));
    _subs.add(player.stream.error.listen((e) {
      _errText = e;
      _failAttempt();
    }));

    try {
      await player.open(Media(widget.config.rtspUrl), play: true);
      await player.setVolume(_listening ? 100.0 : 0.0);
    } catch (e) {
      _errText = '$e';
      _failAttempt();
      return;
    }

    if (widget.config.motionEnabled) _motion?.start();

    _swapping = false;
    _armWatchdog();
    setState(() {});
  }

  void _onConnected() {
    if (!mounted) return;
    _watchdog?.cancel();
    if (_connecting || _error) {
      setState(() {
        _connecting = false;
        _error = false;
        _errText = null;
      });
    }
    _player?.setVolume(_listening ? 100.0 : 0.0);
  }

  void _armWatchdog() {
    _watchdog?.cancel();
    _watchdog = Timer(const Duration(seconds: 8), _failAttempt);
  }

  // L'attuale tentativo non ha prodotto video: passa al trasporto successivo
  // oppure, se le ho provate tutte, mostra l'errore.
  void _failAttempt() {
    if (!mounted || _swapping) return;
    _watchdog?.cancel();
    if (_player?.state.playing == true) return;
    if (_attempt < _configs.length - 1) {
      _attempt++;
      _swapPlayer();
    } else {
      setState(() {
        _connecting = false;
        _error = true;
      });
      _runDiagnostics();
    }
  }

  // Parla direttamente con la telecamera per capire cosa non va.
  Future<void> _runDiagnostics() async {
    if (_diagRunning) return;
    setState(() {
      _diagRunning = true;
      _diag = 'Diagnostica in corso…';
      _suggestPath = null;
    });
    RtspResult res;
    try {
      res = await RtspProbe(widget.config).run();
    } catch (e) {
      res = RtspResult(reachable: false, message: 'Diagnostica fallita: $e');
    }
    if (!mounted) return;
    setState(() {
      _diagRunning = false;
      _diag = res.message;
      _suggestPath = res.suggestPath;
    });
    // Se non risponde proprio, prova a ritrovarla (IP cambiato).
    if (!res.reachable) {
      _autoSearchIp();
    }
  }

  Future<void> _applySuggestedPath() async {
    final p = _suggestPath;
    if (p == null) return;
    widget.config.path = p;
    await widget.config.save();
    _suggestPath = null;
    _diag = null;
    await _refresh();
  }

  Future<void> _swapPlayer() async {
    _swapping = true;
    _watchdog?.cancel();
    if (mounted) {
      setState(() {
        _connecting = true;
        _error = false;
      });
    }
    for (final s in _subs) {
      s.cancel();
    }
    _subs.clear();
    final old = _player;
    _player = null;
    _video = null;
    if (old != null) {
      try {
        await old.stop();
      } catch (_) {}
      try {
        await old.dispose();
      } catch (_) {}
    }
    // La telecamera (economica) tiene aperta la vecchia sessione RTSP per
    // qualche istante: aspetta che la liberi, altrimenti rifiuta la nuova
    // connessione (schermo nero / riconnessione infinita).
    await Future.delayed(const Duration(milliseconds: 1200));
    if (!mounted) return;
    await _startPlayer();
  }

  Future<Uint8List?> _grabFrame() async {
    final p = _player;
    if (p == null) return null;
    try {
      return await p.screenshot(format: 'image/jpeg');
    } catch (_) {
      return null;
    }
  }

  Future<void> _onMotionEvent() async {
    if (!mounted) return;
    if (!widget.config.soundEnabled) return; // "Avvisi" spenti = silenzio
    try {
      await _beep.stop();
      await _beep.play(AssetSource('beep.wav'), volume: 1.0);
    } catch (_) {}
    try {
      if (await Vibration.hasVibrator() ?? false) {
        Vibration.vibrate(pattern: [0, 260, 120, 260]);
      }
    } catch (_) {}
  }

  Future<void> _refresh() async {
    _attempt = 0;
    _motion?.stop();
    await _swapPlayer();
  }

  void _toggleListen() {
    setState(() => _listening = !_listening);
    _player?.setVolume(_listening ? 100.0 : 0.0);
  }

  Future<void> _toggleMotion() async {
    widget.config.motionEnabled = !widget.config.motionEnabled;
    await widget.config.save();
    if (widget.config.motionEnabled) {
      _motion?.start();
    } else {
      _motion?.stop();
      setState(() => _motionActive = false);
    }
    setState(() {});
  }

  Future<void> _toggleQuality() async {
    widget.config.lowQuality = !widget.config.lowQuality;
    await widget.config.save();
    setState(() {});
    await _refresh();
  }

  Future<void> _toggleSound() async {
    widget.config.soundEnabled = !widget.config.soundEnabled;
    await widget.config.save();
    setState(() {});
  }

  // Cerca la telecamera nella rete locale (se ha cambiato IP).
  Future<void> _autoSearchIp() async {
    if (_searching) return;
    setState(() {
      _searching = true;
      _diag = 'Ricerca telecamera nella rete…';
      _suggestPath = null;
    });
    String? found;
    try {
      found = await RtspProbe(widget.config).findCamera();
    } catch (_) {}
    if (!mounted) return;
    if (found != null && found != widget.config.ip) {
      widget.config.ip = found;
      await widget.config.save();
      setState(() {
        _searching = false;
        _diag = 'Trovata a $found. Riconnessione…';
      });
      await _refresh();
    } else if (found != null) {
      setState(() {
        _searching = false;
        _diag = 'La telecamera è a $found ma non manda il video.';
      });
    } else {
      setState(() {
        _searching = false;
        _diag =
            'Nessuna telecamera trovata sulla rete.\nControlla che telefono e telecamera siano sullo stesso Wi-Fi.';
      });
    }
  }

  Future<void> _enterFullscreen() async {
    setState(() => _fullscreen = true);
    await SystemChrome.setPreferredOrientations([
      DeviceOrientation.landscapeLeft,
      DeviceOrientation.landscapeRight,
    ]);
    await SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
  }

  Future<void> _exitFullscreen() async {
    setState(() => _fullscreen = false);
    await SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    await SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _player?.play();
      if (widget.config.motionEnabled) _motion?.start();
    } else if (state == AppLifecycleState.paused) {
      _motion?.stop();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    WakelockPlus.disable();
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    SystemChrome.setPreferredOrientations(DeviceOrientation.values);
    _watchdog?.cancel();
    for (final s in _subs) {
      s.cancel();
    }
    _subs.clear();
    _motion?.stop();
    _beep.dispose();
    _lullaby.dispose();
    _player?.dispose();
    super.dispose();
  }

  Color get _bg => _night ? const Color(0xFF15131A) : kBg;
  Color get _ink => _night ? const Color(0xFFEDE9F0) : kInk;

  @override
  Widget build(BuildContext context) {
    return OrientationBuilder(
      builder: (context, orientation) {
        final landscape = orientation == Orientation.landscape;
        return Scaffold(
          backgroundColor: _bg,
          body: SafeArea(
            bottom: !landscape,
            child: landscape ? _landscape() : _portrait(),
          ),
        );
      },
    );
  }

  // ---- LAYOUT VERTICALE -----------------------------------------------

  Widget _portrait() {
    return Column(
      children: [
        _topBar(),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14),
          child: GestureDetector(
            onTap: _error ? null : _enterFullscreen,
            child: AspectRatio(
              aspectRatio: 16 / 9,
              child: _videoCard(),
            ),
          ),
        ),
        const Spacer(),
        _controlDock(),
        const SizedBox(height: 8),
      ],
    );
  }

  Widget _topBar() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 12, 12, 8),
      child: Row(
        children: [
          Container(
            width: 12,
            height: 12,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: _error
                  ? Colors.redAccent
                  : (_connecting ? Colors.orangeAccent : kMint),
            ),
          ),
          const SizedBox(width: 10),
          Text(
            _error
                ? 'Disconnessa'
                : (_connecting ? 'Connessione…' : 'In diretta'),
            style: TextStyle(
                fontWeight: FontWeight.w700, fontSize: 16, color: _ink),
          ),
          const Spacer(),
          _roundIcon(
            widget.config.lowQuality ? Icons.sd_rounded : Icons.hd_rounded,
            _toggleQuality,
          ),
          _roundIcon(Icons.fullscreen_rounded, _enterFullscreen),
          _roundIcon(_night ? Icons.dark_mode : Icons.light_mode, _toggleNight),
          _roundIcon(Icons.settings_rounded, _openSettings),
        ],
      ),
    );
  }

  // ---- LAYOUT ORIZZONTALE (a schermo intero) ---------------------------

  Widget _landscape() {
    return Stack(
      children: [
        Positioned.fill(child: _videoCard(rounded: false)),
        // Controlli flottanti a destra.
        Positioned(
          right: 12,
          top: 12,
          bottom: 12,
          child: Column(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Flexible(
                child: SingleChildScrollView(
                  child: Column(children: [
                    _glassIcon(Icons.fullscreen_exit_rounded, _exitFullscreen),
                    const SizedBox(height: 10),
                    _glassIcon(
                        _listening ? Icons.volume_up : Icons.volume_off,
                        _toggleListen,
                        active: _listening),
                    const SizedBox(height: 10),
                    _glassIcon(
                        widget.config.motionEnabled
                            ? Icons.sensors
                            : Icons.sensors_off,
                        _toggleMotion,
                        active: widget.config.motionEnabled),
                    const SizedBox(height: 10),
                    _glassIcon(
                        widget.config.soundEnabled
                            ? Icons.notifications_active
                            : Icons.notifications_off,
                        _toggleSound,
                        active: widget.config.soundEnabled),
                    const SizedBox(height: 10),
                    _glassIcon(
                        widget.config.lowQuality
                            ? Icons.sd_rounded
                            : Icons.hd_rounded,
                        _toggleQuality),
                    const SizedBox(height: 10),
                    _glassIcon(Icons.refresh_rounded, _refresh),
                    const SizedBox(height: 10),
                    _glassIcon(Icons.music_note_rounded, _openLullabies),
                  ]),
                ),
              ),
              const SizedBox(height: 8),
              _ptzPad(compact: true),
            ],
          ),
        ),
      ],
    );
  }

  // ---- VIDEO -----------------------------------------------------------

  Widget _videoCard({bool rounded = true}) {
    final video = _video;
    final radius = rounded ? BorderRadius.circular(26) : BorderRadius.zero;
    return ClipRRect(
      borderRadius: radius,
      child: Container(
        color: Colors.black,
        width: double.infinity,
        child: Stack(
          fit: StackFit.expand,
          children: [
            if (video != null)
              Video(
                controller: video,
                fit: BoxFit.contain,
                controls: NoVideoControls,
                fill: Colors.black,
              ),
            if (_error)
              _overlay(
                Icons.videocam_off_rounded,
                'Telecamera non raggiungibile',
                detail: _diag ?? _errorDetail(),
                showRetry: !_searching,
                busy: _searching || _diagRunning,
                extras: [
                  if (_suggestPath != null)
                    _overlayButton(Icons.check_rounded, 'Usa "$_suggestPath"',
                        _applySuggestedPath),
                  if (!_searching && !_diagRunning)
                    _overlayButton(Icons.travel_explore_rounded,
                        'Cerca telecamera', _autoSearchIp),
                ],
              ),
            if (!_error && _connecting)
              _overlay(
                null,
                'Connessione alla telecamera…',
                detail: '$_address · $_transport',
              ),
            if (_motionActive && _video != null && !_error) _motionBanner(),
          ],
        ),
      ),
    );
  }

  String get _address =>
      '${widget.config.ip}:${widget.config.rtspPort}/${widget.config.activePath}';

  String _errorDetail() {
    final e = (_errText ?? '').trim();
    final base = 'Indirizzo: $_address';
    if (e.isEmpty) {
      return '$base\nVerifica IP, percorso e password (⚙️).';
    }
    return '$base\n$e';
  }

  Widget _overlay(IconData? icon, String text,
      {bool showRetry = false,
      String? detail,
      List<Widget> extras = const [],
      bool busy = false}) {
    return Container(
      color: Colors.black.withOpacity(0.6),
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: Center(
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (icon != null)
                Icon(icon, color: Colors.white70, size: 54)
              else
                const SizedBox(
                  width: 42,
                  height: 42,
                  child: CircularProgressIndicator(
                      color: Colors.white, strokeWidth: 3),
                ),
              const SizedBox(height: 16),
              Text(text,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: Colors.white, fontSize: 15)),
              if (detail != null) ...[
                const SizedBox(height: 8),
                Text(detail,
                    textAlign: TextAlign.center,
                    style:
                        const TextStyle(color: Colors.white60, fontSize: 12.5)),
              ],
              if (busy) ...[
                const SizedBox(height: 16),
                const SizedBox(
                  width: 24,
                  height: 24,
                  child: CircularProgressIndicator(
                      color: Colors.white, strokeWidth: 2.5),
                ),
              ],
              if (showRetry || extras.isNotEmpty) ...[
                const SizedBox(height: 18),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  alignment: WrapAlignment.center,
                  children: [
                    if (showRetry)
                      _overlayButton(Icons.refresh, 'Riprova', _refresh),
                    ...extras,
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _overlayButton(IconData icon, String label, VoidCallback onTap) {
    return FilledButton.icon(
      style: FilledButton.styleFrom(backgroundColor: kMint),
      onPressed: onTap,
      icon: Icon(icon, size: 18),
      label: Text(label),
    );
  }

  Widget _motionBanner() {
    return Positioned(
      top: 14,
      left: 0,
      right: 0,
      child: Center(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
          decoration: BoxDecoration(
            color: kPeach,
            borderRadius: BorderRadius.circular(30),
            boxShadow: [
              BoxShadow(
                  color: kPeach.withOpacity(0.5),
                  blurRadius: 18,
                  spreadRadius: 1),
            ],
          ),
          child: const Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.child_care_rounded, color: Colors.white, size: 22),
              SizedBox(width: 8),
              Text('Movimento rilevato',
                  style: TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w800,
                      fontSize: 15)),
            ],
          ),
        ),
      ),
    );
  }

  // ---- DOCK DEI CONTROLLI (verticale) ---------------------------------

  Widget _controlDock() {
    return Container(
      margin: const EdgeInsets.fromLTRB(14, 12, 14, 0),
      padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 8),
      decoration: BoxDecoration(
        color: _night ? const Color(0xFF211E29) : Colors.white,
        borderRadius: BorderRadius.circular(26),
        boxShadow: [
          BoxShadow(
              color: kInk.withOpacity(_night ? 0.25 : 0.06),
              blurRadius: 18,
              offset: const Offset(0, 6)),
        ],
      ),
      child: Column(
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _dockButton(
                _listening ? Icons.volume_up_rounded : Icons.volume_off_rounded,
                'Ascolta',
                _toggleListen,
                active: _listening,
              ),
              _dockButton(
                widget.config.motionEnabled
                    ? Icons.sensors_rounded
                    : Icons.sensors_off_rounded,
                'Movimento',
                _toggleMotion,
                active: widget.config.motionEnabled,
              ),
              _dockButton(
                widget.config.soundEnabled
                    ? Icons.notifications_active_rounded
                    : Icons.notifications_off_rounded,
                'Avvisi',
                _toggleSound,
                active: widget.config.soundEnabled,
              ),
              _dockButton(Icons.refresh_rounded, 'Aggiorna', _refresh),
              _dockButton(
                  Icons.music_note_rounded, 'Ninna nanna', _openLullabies),
            ],
          ),
          const SizedBox(height: 8),
          _ptzPad(),
        ],
      ),
    );
  }

  // ---- PTZ -------------------------------------------------------------

  Widget _ptzPad({bool compact = false}) {
    final size = compact ? 46.0 : 54.0;
    Widget arrow(IconData ic, String dir) {
      return GestureDetector(
        onTapDown: (_) => _ptz.move(dir),
        onTapUp: (_) => _ptz.stop(),
        onTapCancel: () => _ptz.stop(),
        child: Container(
          width: size,
          height: size,
          decoration: BoxDecoration(
            color: compact
                ? Colors.black.withOpacity(0.35)
                : kMint.withOpacity(0.12),
            shape: BoxShape.circle,
          ),
          child: Icon(ic, color: compact ? Colors.white : kMint, size: 26),
        ),
      );
    }

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        arrow(Icons.keyboard_arrow_up_rounded, 'up'),
        const SizedBox(height: 6),
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            arrow(Icons.keyboard_arrow_left_rounded, 'left'),
            SizedBox(width: compact ? 46 : 54),
            arrow(Icons.keyboard_arrow_right_rounded, 'right'),
          ],
        ),
        const SizedBox(height: 6),
        arrow(Icons.keyboard_arrow_down_rounded, 'down'),
      ],
    );
  }

  // ---- NINNA NANNE -----------------------------------------------------

  Future<List<String>> _lullabyAssets() async {
    try {
      final manifest = await rootBundle.loadString('AssetManifest.json');
      final map = jsonDecode(manifest) as Map<String, dynamic>;
      final keys = map.keys
          .where((k) =>
              k.startsWith('assets/lullabies/') &&
              (k.endsWith('.mp3') || k.endsWith('.m4a') || k.endsWith('.wav')))
          .toList()
        ..sort();
      return keys;
    } catch (_) {
      return [];
    }
  }

  void _openLullabies() {
    showModalBottomSheet(
      context: context,
      backgroundColor: _night ? const Color(0xFF211E29) : Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      builder: (ctx) {
        return FutureBuilder<List<String>>(
          future: _lullabyAssets(),
          builder: (ctx, snap) {
            final items = snap.data ?? [];
            return StatefulBuilder(
              builder: (ctx, setSheet) {
                Widget body;
                if (snap.connectionState == ConnectionState.waiting) {
                  body = const Padding(
                    padding: EdgeInsets.all(40),
                    child: Center(child: CircularProgressIndicator()),
                  );
                } else if (items.isEmpty) {
                  body = Padding(
                    padding: const EdgeInsets.fromLTRB(24, 8, 24, 40),
                    child: Column(
                      children: [
                        Icon(Icons.library_music_outlined,
                            size: 46, color: _ink.withOpacity(0.4)),
                        const SizedBox(height: 14),
                        Text(
                          'Nessuna ninna nanna nell\'app.\nAggiungi i file mp3 in '
                          'assets/lullabies/ e ricompila.',
                          textAlign: TextAlign.center,
                          style: TextStyle(color: _ink.withOpacity(0.7)),
                        ),
                      ],
                    ),
                  );
                } else {
                  body = Column(
                    mainAxisSize: MainAxisSize.min,
                    children: items.map((path) {
                      final name = path
                          .split('/')
                          .last
                          .replaceAll(RegExp(r'\.(mp3|m4a|wav)$'), '');
                      final playing = _playingLullaby == path;
                      return ListTile(
                        leading: Icon(
                          playing
                              ? Icons.pause_circle_filled_rounded
                              : Icons.play_circle_fill_rounded,
                          color: kMint,
                          size: 34,
                        ),
                        title: Text(name,
                            style: TextStyle(
                                color: _ink, fontWeight: FontWeight.w600)),
                        onTap: () async {
                          if (playing) {
                            await _lullaby.stop();
                            setSheet(() => _playingLullaby = null);
                            setState(() => _playingLullaby = null);
                          } else {
                            await _lullaby.stop();
                            // Gli asset audioplayers vogliono il percorso
                            // senza il prefisso "assets/".
                            final rel = path.replaceFirst('assets/', '');
                            await _lullaby.play(AssetSource(rel));
                            _lullaby.onPlayerComplete.first.then((_) {
                              if (mounted) setState(() => _playingLullaby = null);
                            });
                            setSheet(() => _playingLullaby = path);
                            setState(() => _playingLullaby = path);
                          }
                        },
                      );
                    }).toList(),
                  );
                }

                return Padding(
                  padding: EdgeInsets.only(
                      bottom: MediaQuery.of(ctx).viewInsets.bottom),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const SizedBox(height: 12),
                      Container(
                        width: 44,
                        height: 5,
                        decoration: BoxDecoration(
                          color: _ink.withOpacity(0.2),
                          borderRadius: BorderRadius.circular(3),
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.fromLTRB(24, 16, 24, 8),
                        child: Row(
                          children: [
                            const Icon(Icons.music_note_rounded, color: kPeach),
                            const SizedBox(width: 10),
                            Text('Ninna nanne',
                                style: TextStyle(
                                    fontSize: 18,
                                    fontWeight: FontWeight.w800,
                                    color: _ink)),
                            const Spacer(),
                            if (_playingLullaby != null)
                              TextButton.icon(
                                onPressed: () async {
                                  await _lullaby.stop();
                                  setSheet(() => _playingLullaby = null);
                                  setState(() => _playingLullaby = null);
                                },
                                icon: const Icon(Icons.stop_rounded),
                                label: const Text('Stop'),
                              ),
                          ],
                        ),
                      ),
                      Flexible(child: SingleChildScrollView(child: body)),
                      const SizedBox(height: 12),
                    ],
                  ),
                );
              },
            );
          },
        );
      },
    );
  }

  // ---- AZIONI VARIE ----------------------------------------------------

  void _toggleNight() => setState(() => _night = !_night);

  Future<void> _openSettings() async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => SetupScreen(
          config: widget.config,
          onDone: () {
            Navigator.of(context).pop();
            widget.onReconfigure();
          },
        ),
      ),
    );
  }

  // ---- WIDGET DI SUPPORTO ---------------------------------------------

  Widget _roundIcon(IconData ic, VoidCallback onTap) {
    return IconButton(
      onPressed: onTap,
      icon: Icon(ic, color: _ink),
    );
  }

  Widget _glassIcon(IconData ic, VoidCallback onTap, {bool active = false}) {
    return Material(
      color: Colors.transparent,
      shape: const CircleBorder(),
      child: InkWell(
        onTap: onTap,
        customBorder: const CircleBorder(),
        child: Container(
          width: 52,
          height: 52,
          decoration: BoxDecoration(
            color: active ? kMint : Colors.black.withOpacity(0.45),
            shape: BoxShape.circle,
            border: Border.all(color: Colors.white24),
          ),
          child: Icon(ic, color: Colors.white, size: 24),
        ),
      ),
    );
  }

  Widget _dockButton(IconData ic, String label, VoidCallback onTap,
      {bool active = false}) {
    final color = active ? kMint : _ink.withOpacity(0.75);
    return InkWell(
      borderRadius: BorderRadius.circular(16),
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 50,
              height: 50,
              decoration: BoxDecoration(
                color: active
                    ? kMint.withOpacity(0.15)
                    : (_night
                        ? Colors.white.withOpacity(0.06)
                        : kBg),
                shape: BoxShape.circle,
              ),
              child: Icon(ic, color: color, size: 25),
            ),
            const SizedBox(height: 6),
            Text(label,
                style: TextStyle(
                    fontSize: 11.5,
                    fontWeight: FontWeight.w600,
                    color: color)),
          ],
        ),
      ),
    );
  }
}

/// Una combinazione di trasporto (UDP/TCP) e decodifica (hardware/software)
/// da provare per aprire il flusso video.
class _PlayCfg {
  final bool tcp;
  final bool hw;
  const _PlayCfg(this.tcp, this.hw);
  String get label =>
      '${tcp ? "TCP" : "UDP"} · ${hw ? "hardware" : "software"}';
}
