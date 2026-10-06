import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../data/stores.dart';
import '../state/app_state.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _server = TextEditingController();
  final _user = TextEditingController();
  final _pass = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _server.text = context.read<AppState>().serverUrl;
  }

  Future<void> _go() async {
    final app = context.read<AppState>();
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await app.setServerUrl(_server.text);
      await app.login(_user.text, _pass.text);
    } on OfflineException catch (e) {
      _error = '${e.message}. Logging in needs internet the first time.';
    } on ApiException catch (e) {
      _error = e.message;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                const Icon(Icons.payments_outlined, size: 56),
                const SizedBox(height: 8),
                Text('Collector', style: Theme.of(context).textTheme.headlineMedium),
                const SizedBox(height: 24),
                TextField(
                  controller: _server,
                  keyboardType: TextInputType.url,
                  decoration: const InputDecoration(
                      labelText: 'Server address', hintText: 'https://billing.example.com'),
                ),
                const SizedBox(height: 12),
                TextField(
                    controller: _user,
                    autocorrect: false,
                    decoration: const InputDecoration(labelText: 'Username')),
                const SizedBox(height: 12),
                TextField(
                  controller: _pass,
                  obscureText: true,
                  onSubmitted: (_) => _go(),
                  decoration: const InputDecoration(labelText: 'Password'),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 20),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: _busy ? null : _go,
                    child: _busy
                        ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Text('Log in'),
                  ),
                ),
                if (app.pending > 0) ...[
                  const SizedBox(height: 16),
                  Text(
                    '${app.pending} payment(s) collected on this phone are waiting to upload. '
                    'They are safe and will upload after you log in.',
                    textAlign: TextAlign.center,
                  ),
                ],
              ]),
            ),
          ),
        ),
      ),
    );
  }
}
