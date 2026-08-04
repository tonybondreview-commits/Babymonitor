import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_vlc_player/flutter_vlc_player.dart';
import 'package:vibration/vibration.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import 'config.dart';
import 'main.dart' show kMint, kPeach, kBg, kInk;
import 'motion.dart';
import 'onvif.dart';
import 'rtsp_probe.dart';
import 'setup.dart';

/// Schermata principale: video dal vivo con decoder integrato (libVLC),
/// rilevamento movimento sul dispositivo, PTZ, ascolto audio e ninna nanne.
class HomeScreen extends StatefulWidget {
  final CameraConfig config;
  final VoidCallback onReconfigure;
  const HomeScreen(
      {super.key, required this.config, required this.onReconfigure});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with WidgetsBindingObserver {
  VlcPlayerController? _vlc;
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

  // Apertura del flusso: prova prima UDP (richiesto da questa camera), poi TCP.
  Timer? _watchdog;
  int _attempt = 0;
  bool _swapping = false;
  String? _errText;
  // Prova in sequenza trasporto (UDP/TCP) x decodifica (hardware/software).
  static const _configs = <_PlayCfg>[
    _PlayCfg(false, HwAcc.auto), // UDP, hardware
    _PlayCfg(true, HwAcc.auto), // TCP, hardware
    _PlayCfg(false, HwAcc.disabled), // UDP, software
    _PlayCfg(true, HwAcc.disabled), // TCP, software
  ];
  _PlayCfg get _cfgNow => _configs[_attempt % _configs.length];
  String get _transport => _cfgNow.label;

  // Diagnostica di rete (quando il video non parte).
  String? _diag;
  String? _suggestPath;
  bool _diagRunning = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WakelockPlus.enable();
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
    final ctrl = VlcPlayerController.network(
      widget.config.rtspUrl,
      hwAcc: cfg.hw,
      autoPlay: true,
      options: VlcPlayerOptions(
        advanced: VlcAdvancedOptions([
          VlcAdvancedOptions.networkCaching(1500),
        ]),
        // false = RTP su UDP; true = RTP dentro RTSP/TCP. Proviamo entrambi.
        rtp: VlcRtpOptions([VlcRtpOptions.rtpOverRtsp(cfg.tcp)]),
      ),
    );
    ctrl.addListener(_onVlcState);
    _vlc = ctrl;

    if (widget.config.motionEnabled) _motion?.start();

    _swapping = false;
    _armWatchdog();
    setState(() {});
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
    final v = _vlc;
    if (v != null && v.value.playingState == PlayingState.playing) return;
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
    final old = _vlc;
    _vlc = null;
    if (old != null) {
      old.removeListener(_onVlcState);
      try {
        await old.stopRendererScanning();
      } catch (_) {}
      try {
        await old.dispose();
      } catch (_) {}
    }
    if (!mounted) return;
    await _startPlayer();
  }

  void _onVlcState() {
    final v = _vlc;
    if (v == null || !mounted) return;
    final st = v.value;

    if (st.isInitialized && st.playingState == PlayingState.playing) {
      _watchdog?.cancel();
      if (_connecting || _error) {
        setState(() {
          _connecting = false;
          _error = false;
          _errText = null;
        });
      }
      v.setVolume(_listening ? 100 : 0);
      return;
    }

    if (st.hasError) {
      _errText = st.errorDescription;
      _failAttempt();
    }
  }

  Future<Uint8List?> _grabFrame() async {
    final v = _vlc;
    if (v == null || !v.value.isInitialized) return null;
    if (v.value.playingState != PlayingState.playing) return null;
    try {
      return await v.takeSnapshot();
    } catch (_) {
      return null;
    }
  }

  Future<void> _onMotionEvent() async {
    if (!mounted) return;
    if (widget.config.soundEnabled) {
      try {
        await _beep.stop();
        await _beep.play(AssetSource('beep.wav'), volume: 1.0);
      } catch (_) {}
    }
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
    _vlc?.setVolume(_listening ? 100 : 0);
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

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _vlc?.play();
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
    _watchdog?.cancel();
    _motion?.stop();
    _beep.dispose();
    _lullaby.dispose();
    _vlc?.removeListener(_onVlcState);
    _vlc?.dispose();
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
        Expanded(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14),
            child: _videoCard(),
          ),
        ),
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
              Column(children: [
                _glassIcon(_listening ? Icons.volume_up : Icons.volume_off,
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
                _glassIcon(Icons.refresh_rounded, _refresh),
                const SizedBox(height: 10),
                _glassIcon(Icons.music_note_rounded, _openLullabies),
              ]),
              _ptzPad(compact: true),
            ],
          ),
        ),
      ],
    );
  }

  // ---- VIDEO -----------------------------------------------------------

  Widget _videoCard({bool rounded = true}) {
    final v = _vlc;
    final radius = rounded ? BorderRadius.circular(26) : BorderRadius.zero;
    return ClipRRect(
      borderRadius: radius,
      child: Container(
        color: Colors.black,
        width: double.infinity,
        child: Stack(
          fit: StackFit.expand,
          children: [
            if (v != null)
              VlcPlayer(
                controller: v,
                aspectRatio: 16 / 9,
                placeholder: const ColoredBox(color: Colors.black),
              ),
            if (_error)
              _overlay(
                Icons.videocam_off_rounded,
                'Telecamera non raggiungibile',
                detail: _diag ?? _errorDetail(),
                showRetry: true,
                secondary: _suggestPath != null
                    ? _overlayButton(
                        Icons.check_rounded,
                        'Usa "$_suggestPath"',
                        _applySuggestedPath,
                      )
                    : (!_diagRunning
                        ? _overlayButton(
                            Icons.wifi_find_rounded,
                            'Diagnostica',
                            _runDiagnostics,
                          )
                        : null),
              ),
            if (!_error && _connecting)
              _overlay(
                null,
                'Connessione alla telecamera…',
                detail: '$_address · $_transport',
              ),
            if (_motionActive && _vlc != null && !_error) _motionBanner(),
          ],
        ),
      ),
    );
  }

  String get _address =>
      '${widget.config.ip}:${widget.config.rtspPort}/${widget.config.path}';

  String _errorDetail() {
    final e = (_errText ?? '').trim();
    final base = 'Indirizzo: $_address';
    if (e.isEmpty) {
      return '$base\nVerifica IP, percorso e password (⚙️).';
    }
    return '$base\n$e';
  }

  Widget _overlay(IconData? icon, String text,
      {bool showRetry = false, String? detail, Widget? secondary}) {
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
              if (showRetry || secondary != null) ...[
                const SizedBox(height: 18),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  alignment: WrapAlignment.center,
                  children: [
                    if (showRetry)
                      _overlayButton(Icons.refresh, 'Riprova', _refresh),
                    if (secondary != null) secondary,
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
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 48,
        height: 48,
        decoration: BoxDecoration(
          color: active ? kMint : Colors.black.withOpacity(0.4),
          shape: BoxShape.circle,
        ),
        child: Icon(ic, color: Colors.white, size: 24),
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
  final HwAcc hw;
  const _PlayCfg(this.tcp, this.hw);
  String get label =>
      '${tcp ? "TCP" : "UDP"} · ${hw == HwAcc.disabled ? "software" : "hardware"}';
}
