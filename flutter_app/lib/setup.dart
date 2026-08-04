import 'package:flutter/material.dart';

import 'config.dart';
import 'main.dart' show kMint, kPeach, kBg, kInk;

/// Schermata di configurazione: si inseriscono i dati della telecamera.
/// Compare al primo avvio oppure quando si tocca "Impostazioni".
class SetupScreen extends StatefulWidget {
  final CameraConfig config;
  final VoidCallback onDone;
  const SetupScreen({super.key, required this.config, required this.onDone});

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  late final TextEditingController _ip;
  late final TextEditingController _user;
  late final TextEditingController _pass;
  late final TextEditingController _path;
  late final TextEditingController _rtspPort;
  late final TextEditingController _onvifPort;
  late int _sensitivity;
  bool _showAdvanced = false;
  bool _obscure = true;

  @override
  void initState() {
    super.initState();
    final c = widget.config;
    _ip = TextEditingController(text: c.ip);
    _user = TextEditingController(text: c.username);
    _pass = TextEditingController(text: c.password);
    _path = TextEditingController(text: c.path);
    _rtspPort = TextEditingController(text: c.rtspPort.toString());
    _onvifPort = TextEditingController(text: c.onvifPort.toString());
    _sensitivity = c.sensitivity;
  }

  @override
  void dispose() {
    _ip.dispose();
    _user.dispose();
    _pass.dispose();
    _path.dispose();
    _rtspPort.dispose();
    _onvifPort.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final ip = _ip.text.trim();
    if (ip.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Inserisci l\'indirizzo IP della telecamera')),
      );
      return;
    }
    final c = widget.config;
    c.ip = ip;
    c.username = _user.text.trim();
    c.password = _pass.text;
    c.path = _path.text.trim().replaceAll(RegExp(r'^/+'), '');
    c.rtspPort = int.tryParse(_rtspPort.text.trim()) ?? 554;
    c.onvifPort = int.tryParse(_onvifPort.text.trim()) ?? 5000;
    c.sensitivity = _sensitivity;
    await c.save();
    widget.onDone();
  }

  InputDecoration _dec(String label, {String? hint, Widget? suffix}) {
    return InputDecoration(
      labelText: label,
      hintText: hint,
      suffixIcon: suffix,
      filled: true,
      fillColor: Colors.white,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: BorderSide(color: kMint.withOpacity(0.25)),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: BorderSide(color: kMint.withOpacity(0.25)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: const BorderSide(color: kMint, width: 2),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final canGoBack = widget.config.isConfigured;
    return Scaffold(
      backgroundColor: kBg,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        foregroundColor: kInk,
        title: const Text('Configura la telecamera',
            style: TextStyle(fontWeight: FontWeight.w700)),
        leading: canGoBack
            ? IconButton(
                icon: const Icon(Icons.arrow_back),
                onPressed: () => Navigator.of(context).maybePop(),
              )
            : null,
        automaticallyImplyLeading: canGoBack,
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 40),
          children: [
            _card(
              icon: Icons.videocam_rounded,
              title: 'Telecamera',
              children: [
                TextField(
                  controller: _ip,
                  keyboardType: TextInputType.url,
                  decoration: _dec('Indirizzo IP', hint: 'es. 192.168.1.67'),
                ),
                const SizedBox(height: 14),
                TextField(
                  controller: _user,
                  decoration: _dec('Utente', hint: 'admin'),
                ),
                const SizedBox(height: 14),
                TextField(
                  controller: _pass,
                  obscureText: _obscure,
                  decoration: _dec(
                    'Password',
                    suffix: IconButton(
                      icon: Icon(_obscure ? Icons.visibility_off : Icons.visibility),
                      onPressed: () => setState(() => _obscure = !_obscure),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 18),
            _card(
              icon: Icons.tune_rounded,
              title: 'Sensibilità movimento',
              children: [
                Text(
                  _sensLabel(),
                  style: const TextStyle(fontWeight: FontWeight.w600, color: kInk),
                ),
                Slider(
                  value: _sensitivity.toDouble(),
                  min: 1,
                  max: 100,
                  activeColor: kMint,
                  label: '$_sensitivity',
                  divisions: 99,
                  onChanged: (v) => setState(() => _sensitivity = v.round()),
                ),
                const Text(
                  'Più alta = rileva movimenti piccoli. Se hai troppi falsi allarmi, abbassala.',
                  style: TextStyle(fontSize: 12.5, color: Colors.black54),
                ),
              ],
            ),
            const SizedBox(height: 18),
            _card(
              icon: Icons.settings_rounded,
              title: 'Avanzate',
              trailing: IconButton(
                icon: Icon(_showAdvanced ? Icons.expand_less : Icons.expand_more),
                onPressed: () => setState(() => _showAdvanced = !_showAdvanced),
              ),
              children: _showAdvanced
                  ? [
                      TextField(
                        controller: _path,
                        decoration: _dec('Percorso RTSP', hint: 'onvif1'),
                      ),
                      const SizedBox(height: 14),
                      Row(
                        children: [
                          Expanded(
                            child: TextField(
                              controller: _rtspPort,
                              keyboardType: TextInputType.number,
                              decoration: _dec('Porta RTSP'),
                            ),
                          ),
                          const SizedBox(width: 14),
                          Expanded(
                            child: TextField(
                              controller: _onvifPort,
                              keyboardType: TextInputType.number,
                              decoration: _dec('Porta ONVIF'),
                            ),
                          ),
                        ],
                      ),
                    ]
                  : [],
            ),
            const SizedBox(height: 28),
            SizedBox(
              height: 56,
              child: FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: kMint,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(18),
                  ),
                ),
                onPressed: _save,
                child: const Text('Salva e connetti',
                    style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  String _sensLabel() {
    if (_sensitivity < 33) return 'Bassa ($_sensitivity)';
    if (_sensitivity < 66) return 'Media ($_sensitivity)';
    return 'Alta ($_sensitivity)';
  }

  Widget _card({
    required IconData icon,
    required String title,
    required List<Widget> children,
    Widget? trailing,
  }) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(22),
        boxShadow: [
          BoxShadow(
            color: kInk.withOpacity(0.05),
            blurRadius: 18,
            offset: const Offset(0, 6),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(9),
                decoration: BoxDecoration(
                  color: kPeach.withOpacity(0.18),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(icon, color: kPeach, size: 20),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(title,
                    style: const TextStyle(
                        fontSize: 16, fontWeight: FontWeight.w700, color: kInk)),
              ),
              if (trailing != null) trailing,
            ],
          ),
          if (children.isNotEmpty) const SizedBox(height: 16),
          ...children,
        ],
      ),
    );
  }
}
