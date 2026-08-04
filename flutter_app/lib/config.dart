import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

/// Configurazione della camera, salvata sul dispositivo.
class CameraConfig {
  String ip;
  int rtspPort;
  int onvifPort;
  String username;
  String password;
  String path; // percorso RTSP alta qualita', es. "onvif1"
  String subPath; // percorso RTSP bassa qualita' (sotto-stream), es. "onvif2"
  bool lowQuality; // usa il sotto-stream (piu' leggero)
  int sensitivity; // 1..100
  bool motionEnabled;
  bool soundEnabled;

  CameraConfig({
    this.ip = '',
    this.rtspPort = 554,
    this.onvifPort = 5000,
    this.username = 'admin',
    this.password = '',
    this.path = 'onvif1',
    this.subPath = 'onvif2',
    this.lowQuality = false,
    this.sensitivity = 55,
    this.motionEnabled = true,
    this.soundEnabled = true,
  });

  bool get isConfigured => ip.isNotEmpty;

  String get activePath => lowQuality ? subPath : path;

  /// URL RTSP completo (con credenziali).
  String get rtspUrl {
    final auth = username.isNotEmpty
        ? '${Uri.encodeComponent(username)}:${Uri.encodeComponent(password)}@'
        : '';
    return 'rtsp://$auth$ip:$rtspPort/$activePath';
  }

  Map<String, dynamic> toJson() => {
        'ip': ip,
        'rtspPort': rtspPort,
        'onvifPort': onvifPort,
        'username': username,
        'password': password,
        'path': path,
        'subPath': subPath,
        'lowQuality': lowQuality,
        'sensitivity': sensitivity,
        'motionEnabled': motionEnabled,
        'soundEnabled': soundEnabled,
      };

  factory CameraConfig.fromJson(Map<String, dynamic> j) => CameraConfig(
        ip: j['ip'] ?? '',
        rtspPort: j['rtspPort'] ?? 554,
        onvifPort: j['onvifPort'] ?? 5000,
        username: j['username'] ?? 'admin',
        password: j['password'] ?? '',
        path: j['path'] ?? 'onvif1',
        subPath: j['subPath'] ?? 'onvif2',
        lowQuality: j['lowQuality'] ?? false,
        sensitivity: j['sensitivity'] ?? 55,
        motionEnabled: j['motionEnabled'] ?? true,
        soundEnabled: j['soundEnabled'] ?? true,
      );

  static const _key = 'camera_config';

  Future<void> save() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, jsonEncode(toJson()));
  }

  static Future<CameraConfig> load() async {
    final prefs = await SharedPreferences.getInstance();
    final s = prefs.getString(_key);
    if (s == null) return CameraConfig();
    try {
      return CameraConfig.fromJson(jsonDecode(s));
    } catch (_) {
      return CameraConfig();
    }
  }
}
