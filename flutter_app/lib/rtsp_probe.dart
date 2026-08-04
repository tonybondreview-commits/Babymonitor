import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';

import 'config.dart';

/// Esito della diagnostica RTSP.
class RtspResult {
  final bool reachable; // la porta 554 risponde?
  final int? status; // ultimo codice RTSP (200, 401, 404...)
  final String message; // messaggio leggibile per l'utente
  final String? codec; // H264 / H265 / ...
  final String? suggestPath; // percorso alternativo che ha funzionato
  final bool ok; // DESCRIBE 200 con video

  RtspResult({
    required this.reachable,
    required this.message,
    this.status,
    this.codec,
    this.suggestPath,
    this.ok = false,
  });
}

/// Parla direttamente con la telecamera in RTSP (OPTIONS/DESCRIBE) per capire
/// PERCHE' il video non parte: rete, password, percorso o codec.
class RtspProbe {
  final CameraConfig cfg;
  RtspProbe(this.cfg);

  static const _paths = ['onvif1', 'onvif2', 'live/ch0', 'live/ch1', '11', '12'];

  /// Scansiona la rete locale (stessa sottorete dell'IP attuale) cercando un
  /// dispositivo con la porta RTSP aperta. Restituisce il primo IP trovato.
  Future<String?> findCamera() async {
    final ip = cfg.ip;
    final base = ip.contains('.')
        ? ip.substring(0, ip.lastIndexOf('.') + 1)
        : '192.168.1.';
    final hosts = [for (var i = 1; i <= 254; i++) '$base$i'];
    const batchSize = 32;
    for (var start = 0; start < hosts.length; start += batchSize) {
      final chunk = hosts.skip(start).take(batchSize).toList();
      final results = await Future.wait(chunk.map(_portOpen));
      for (final h in results) {
        if (h != null) return h;
      }
    }
    return null;
  }

  Future<String?> _portOpen(String host) async {
    try {
      final s = await Socket.connect(host, cfg.rtspPort,
          timeout: const Duration(milliseconds: 600));
      s.destroy();
      return host;
    } catch (_) {
      return null;
    }
  }

  Future<RtspResult> run() async {
    Socket? sock;
    try {
      sock = await Socket.connect(cfg.ip, cfg.rtspPort,
          timeout: const Duration(seconds: 4));
    } catch (_) {
      return RtspResult(
        reachable: false,
        message:
            'Non risponde su ${cfg.ip}:${cfg.rtspPort}.\nControlla che IP e rete Wi-Fi siano giusti (stessa rete della telecamera).',
      );
    }

    final incoming = StreamController<List<int>>();
    sock.listen(incoming.add, onError: (_) {}, onDone: () {});
    final reader = _Reader(incoming.stream);

    var cseq = 1;
    try {
      // Prima il percorso configurato, poi gli altri come tentativo.
      final tryPaths = <String>[
        cfg.path,
        ..._paths.where((p) => p != cfg.path),
      ];

      int? lastStatus;
      for (final path in tryPaths) {
        final uri = 'rtsp://${cfg.ip}:${cfg.rtspPort}/$path';
        var resp = await _describe(sock, reader, uri, cseq, null);
        cseq += 1;
        lastStatus = resp.status;

        if (resp.status == 401 && resp.authHeader != null) {
          final auth = _authorize(resp.authHeader!, 'DESCRIBE', uri);
          resp = await _describe(sock, reader, uri, cseq, auth);
          cseq += 1;
          lastStatus = resp.status;
        }

        if (resp.status == 200) {
          final codec = _codecFromSdp(resp.body);
          final same = path == cfg.path;
          return RtspResult(
            reachable: true,
            status: 200,
            ok: true,
            codec: codec,
            suggestPath: same ? null : path,
            message: same
                ? 'Telecamera raggiunta ✓ (percorso "$path"${codec != null ? ", video $codec" : ""}).\nSe il video non parte comunque, il problema è il decoder/codec.'
                : 'Trovato un percorso che funziona: "$path"${codec != null ? " (video $codec)" : ""}.\nAprila con questo percorso nelle impostazioni (⚙️).',
          );
        }
      }

      if (lastStatus == 401) {
        return RtspResult(
          reachable: true,
          status: 401,
          message:
              'La telecamera risponde ma rifiuta la password (401).\nControlla utente e password (⚙️).',
        );
      }
      if (lastStatus == 404) {
        return RtspResult(
          reachable: true,
          status: 404,
          message:
              'La telecamera risponde ma il percorso "${cfg.path}" non esiste (404).\nProva un altro percorso RTSP nelle impostazioni (es. onvif2).',
        );
      }
      return RtspResult(
        reachable: true,
        status: lastStatus,
        message:
            'La telecamera risponde (porta ${cfg.rtspPort}) ma non fornisce il video${lastStatus != null ? " (codice $lastStatus)" : ""}.',
      );
    } catch (e) {
      return RtspResult(
        reachable: true,
        message: 'Errore durante la diagnostica: $e',
      );
    } finally {
      try {
        await sock.close();
      } catch (_) {}
      await incoming.close();
    }
  }

  Future<_Resp> _describe(Socket sock, _Reader reader, String uri, int cseq,
      String? auth) async {
    final b = StringBuffer()
      ..write('DESCRIBE $uri RTSP/1.0\r\n')
      ..write('CSeq: $cseq\r\n')
      ..write('User-Agent: BabyMonitor\r\n')
      ..write('Accept: application/sdp\r\n');
    if (auth != null) b.write('Authorization: $auth\r\n');
    b.write('\r\n');
    sock.write(b.toString());
    await sock.flush();
    return reader.readResponse(const Duration(seconds: 4));
  }

  String? _codecFromSdp(String sdp) {
    final low = sdp.toLowerCase();
    if (low.contains('h265') || low.contains('hevc')) return 'H265';
    if (low.contains('h264')) return 'H264';
    if (low.contains('mjpeg') || low.contains('jpeg')) return 'MJPEG';
    return null;
  }

  String _authorize(String header, String method, String uri) {
    // Basic
    if (header.toLowerCase().startsWith('basic')) {
      final token = base64.encode(utf8.encode('${cfg.username}:${cfg.password}'));
      return 'Basic $token';
    }
    // Digest
    String field(String name) {
      final m = RegExp('$name="?([^",]+)"?').firstMatch(header);
      return m?.group(1) ?? '';
    }

    final realm = field('realm');
    final nonce = field('nonce');
    final qop = field('qop');
    final opaque = field('opaque');

    String md5hex(String s) => md5.convert(utf8.encode(s)).toString();
    final ha1 = md5hex('${cfg.username}:$realm:${cfg.password}');
    final ha2 = md5hex('$method:$uri');

    String response;
    final parts = StringBuffer()
      ..write('Digest username="${cfg.username}", realm="$realm", ')
      ..write('nonce="$nonce", uri="$uri", ');
    if (qop.isNotEmpty) {
      const nc = '00000001';
      final cnonce = md5hex('${DateTime.now().microsecondsSinceEpoch}');
      response = md5hex('$ha1:$nonce:$nc:$cnonce:auth:$ha2');
      parts.write('qop=auth, nc=$nc, cnonce="$cnonce", ');
    } else {
      response = md5hex('$ha1:$nonce:$ha2');
    }
    parts.write('response="$response"');
    if (opaque.isNotEmpty) parts.write(', opaque="$opaque"');
    return parts.toString();
  }
}

class _Resp {
  final int? status;
  final String? authHeader;
  final String body;
  _Resp(this.status, this.authHeader, this.body);
}

/// Legge una risposta RTSP (header + eventuale corpo SDP) dal socket.
class _Reader {
  final Stream<List<int>> stream;
  final List<int> _buf = [];
  StreamSubscription<List<int>>? _sub;
  Completer<void>? _dataWaiter;

  _Reader(this.stream) {
    _sub = stream.listen((chunk) {
      _buf.addAll(chunk);
      _dataWaiter?.complete();
      _dataWaiter = null;
    });
  }

  Future<_Resp> readResponse(Duration timeout) async {
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      final text = ascii.decode(_buf, allowInvalid: true);
      final headerEnd = text.indexOf('\r\n\r\n');
      if (headerEnd != -1) {
        final head = text.substring(0, headerEnd);
        final status = _statusOf(head);
        final auth = _headerOf(head, 'www-authenticate');
        final clen = int.tryParse(_headerOf(head, 'content-length') ?? '');
        final bodyStart = headerEnd + 4;
        if (clen == null || text.length - bodyStart >= clen) {
          final end = clen == null ? text.length : bodyStart + clen;
          final body = text.substring(bodyStart, end);
          // consuma i byte letti, cosi' la prossima risposta parte pulita
          _buf.removeRange(0, end);
          return _Resp(status, auth, body);
        }
      }
      // aspetta altri dati
      final remain = deadline.difference(DateTime.now()).inMilliseconds;
      if (remain <= 0) break;
      _dataWaiter = Completer<void>();
      await _dataWaiter!.future.timeout(
        Duration(milliseconds: remain.clamp(1, 4000)),
        onTimeout: () {},
      );
    }
    // timeout: restituisci quello che c'e' e svuota il buffer
    final text = ascii.decode(_buf, allowInvalid: true);
    _buf.clear();
    final idx = text.indexOf('\r\n\r\n');
    final head = idx == -1 ? text : text.substring(0, idx);
    final body = idx == -1 ? '' : text.substring(idx + 4);
    return _Resp(_statusOf(head), _headerOf(head, 'www-authenticate'), body);
  }

  int? _statusOf(String head) {
    final first = head.split('\r\n').first; // RTSP/1.0 200 OK
    final m = RegExp(r'RTSP/\d\.\d\s+(\d+)').firstMatch(first);
    return m != null ? int.tryParse(m.group(1)!) : null;
  }

  String? _headerOf(String head, String name) {
    for (final line in head.split('\r\n')) {
      final i = line.indexOf(':');
      if (i > 0 && line.substring(0, i).trim().toLowerCase() == name) {
        return line.substring(i + 1).trim();
      }
    }
    return null;
  }

  void dispose() {
    _sub?.cancel();
  }
}
