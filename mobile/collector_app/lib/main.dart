import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'screens/home.dart';
import 'screens/login.dart';
import 'state/app_state.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final state = AppState();
  await state.init();
  runApp(ChangeNotifierProvider.value(value: state, child: const CollectorApp()));
}

class CollectorApp extends StatelessWidget {
  const CollectorApp({super.key});

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    return MaterialApp(
      title: 'Collector',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: const Color(0xFF0B6E4F), useMaterial3: true),
      home: !app.ready
          ? const Scaffold(body: Center(child: CircularProgressIndicator()))
          : app.loggedIn
              ? const HomeScreen()
              : const LoginScreen(),
    );
  }
}
