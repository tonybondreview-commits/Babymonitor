import 'dart:convert';
import 'dart:math';
import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;

import 'config.dart';

/// Controllo PTZ via ONVIF (SOAP + WS-Security UsernameToken).
/// Porta in Dart la stessa logica della versione Python.
class OnvifPtz {
  final CameraConfig cfg;
  OnvifPtz(this.cfg);

  static const _nsDev = 'http://www.onvif.org/ver10/device/wsdl';
  static const _nsMedia = 'http://www.onvif.org/ver10/media/wsdl';
  static const _nsPtz = 'http://www.onvif.org/ver20/ptz/wsdl';
  static const _nsSchema = 'http://www.onvif.org/ver10/schema';

  String get _base => 'http://${cfg.ip}:${cfg.onvifPort}';

  String _token = '';
  String _ptzUrl = '';
  bool _checked = false;
  bool available = false;
  String? _preferred; // "12" o "11"

  String _security() {
    if (cfg.username.isEmpty) return '';
    final created = DateTime.now().toUtc().toIso8601String().split('.').first + 'Z';
    final rnd = Random.secure();
    final nonce = List<int>.generate(16, (_) => rnd.nextInt(256));
    final digest = base64.encode(
        sha1.convert([...nonce, ...utf8.encode(created), ...utf8.encode(cfg.password)]).bytes);
    final n64 = base64.encode(nonce);
    return '<s:Header><Security s:mustUnderstand="1" '
        'xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">'
        '<UsernameToken><Username>${cfg.username}</Username>'
        '<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">$digest</Password>'
        '<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">$n64</Nonce>'
        '<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">$created</Created>'
        '</UsernameToken></Security></s:Header>';
  }

  String _env(String ns, String header, String body) =>
      '<?xml version="1.0" encoding="UTF-8"?>'
      '<s:Envelope xmlns:s="$ns">$header<s:Body>$body</s:Body></s:Envelope>';

  bool _ok(String r) {
    final low = r.toLowerCase();
    return r.isNotEmpty &&
        !low.contains('fault') &&
        !low.contains('versionmismatch') &&
        !low.contains('actionnotsupported');
  }

  Future<String> _post(String url, String body, String action) async {
    final header = _security();
    final order = _preferred == '11' ? ['11', '12'] : ['12', '11'];
    String last = '';
    for (final ver in order) {
      try {
        http.Response resp;
        if (ver == '12') {
          resp = await http
              .post(Uri.parse(url),
                  headers: {'Content-Type': 'application/soap+xml; charset=utf-8; action="$action"'},
                  body: _env('http://www.w3.org/2003/05/soap-envelope', header, body))
              .timeout(const Duration(seconds: 4));
        } else {
          resp = await http
              .post(Uri.parse(url),
                  headers: {'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': '"$action"'},
                  body: _env('http://schemas.xmlsoap.org/soap/envelope/', header, body))
              .timeout(const Duration(seconds: 4));
        }
        last = resp.body;
        if (_ok(last)) {
          _preferred = ver;
          return last;
        }
      } catch (_) {}
    }
    return last;
  }

  Future<bool> ensure() async {
    if (_checked) return available;
    _checked = true;
    if (cfg.ip.isEmpty) return false;

    // GetCapabilities -> XAddr di Media e PTZ
    final caps = await _post(
        '$_base/onvif/device_service',
        '<GetCapabilities xmlns="$_nsDev"><Category>All</Category></GetCapabilities>',
        '$_nsDev/GetCapabilities');
    final xaddrs = RegExp(r'XAddr>\s*(https?://[^<\s]+)')
        .allMatches(caps)
        .map((m) => m.group(1)!)
        .toList();
    String mediaX = xaddrs.firstWhere((x) => x.toLowerCase().contains('media'),
        orElse: () => '$_base/onvif/media_service');
    String ptzX = xaddrs.firstWhere((x) => x.toLowerCase().contains('ptz'), orElse: () => '');

    // GetProfiles -> token
    final prof =
        await _post(mediaX, '<GetProfiles xmlns="$_nsMedia"/>', '$_nsMedia/GetProfiles');
    final tk = RegExp(r'token="([^"]+)"').firstMatch(prof);
    if (tk == null) return false;
    _token = tk.group(1)!;

    // endpoint PTZ
    final candidates = [
      if (ptzX.isNotEmpty) ptzX,
      '$_base/onvif/ptz_service',
      '$_base/onvif/PTZ',
      '$_base/onvif/device_service',
    ];
    for (final url in candidates) {
      final r = await _post(url, _stopBody(), '$_nsPtz/Stop');
      if (r.contains('StopResponse')) {
        _ptzUrl = url;
        available = true;
        break;
      }
    }
    if (!available && ptzX.isNotEmpty) {
      _ptzUrl = ptzX;
      available = true;
    }
    return available;
  }

  String _moveBody(double x, double y, double z) =>
      '<ContinuousMove xmlns="$_nsPtz"><ProfileToken>$_token</ProfileToken>'
      '<Velocity><PanTilt x="$x" y="$y" xmlns="$_nsSchema"/><Zoom x="$z" xmlns="$_nsSchema"/></Velocity>'
      '</ContinuousMove>';

  String _stopBody() =>
      '<Stop xmlns="$_nsPtz"><ProfileToken>$_token</ProfileToken><PanTilt>true</PanTilt><Zoom>true</Zoom></Stop>';

  static const _dirs = {
    'left': [-0.6, 0.0, 0.0],
    'right': [0.6, 0.0, 0.0],
    'up': [0.0, 0.6, 0.0],
    'down': [0.0, -0.6, 0.0],
  };

  Future<void> move(String dir) async {
    if (!await ensure()) return;
    final v = _dirs[dir];
    if (v == null) return;
    await _post(_ptzUrl, _moveBody(v[0], v[1], v[2]), '$_nsPtz/ContinuousMove');
  }

  Future<void> stop() async {
    if (!await ensure()) return;
    await _post(_ptzUrl, _stopBody(), '$_nsPtz/Stop');
  }
}
