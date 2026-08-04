import 'package:flutter/material.dart';
import 'package:media_kit/media_kit.dart';

import 'config.dart';
import 'home.dart';
import 'setup.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  MediaKit.ensureInitialized();
  runApp(const BabyMonitorApp());
}

// Palette "chiaro pastello" coerente con la webapp.
const kMint = Color(0xFF46C299);
const kPeach = Color(0xFFFF9D86);
const kBg = Color(0xFFFBF7F2);
const kInk = Color(0xFF403B46);

class BabyMonitorApp extends StatelessWidget {
  const BabyMonitorApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Baby Monitor',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: kBg,
        colorScheme: ColorScheme.fromSeed(seedColor: kMint, primary: kMint),
        fontFamily: 'SF Pro',
      ),
      home: const _Root(),
    );
  }
}

class _Root extends StatefulWidget {
  const _Root();
  @override
  State<_Root> createState() => _RootState();
}

class _RootState extends State<_Root> {
  CameraConfig? _cfg;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final cfg = await CameraConfig.load();
    setState(() => _cfg = cfg);
  }

  @override
  Widget build(BuildContext context) {
    final cfg = _cfg;
    if (cfg == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (!cfg.isConfigured) {
      return SetupScreen(config: cfg, onDone: () => _load());
    }
    return HomeScreen(config: cfg, onReconfigure: () => _load());
  }
}
