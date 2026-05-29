import 'package:flutter/material.dart';

import 'screens/home_screen.dart';
import 'services/ropac_local.dart';
import 'theme/ropac_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final root = await RopacPaths.loadRoot();
  runApp(RopacApp(ropacRoot: root));
}

class RopacApp extends StatelessWidget {
  const RopacApp({super.key, required this.ropacRoot});

  final String ropacRoot;

  @override
  Widget build(BuildContext context) {
    final ropac = RopacLocal(ropacRoot);
    return MaterialApp(
      title: 'RoPac',
      debugShowCheckedModeBanner: false,
      theme: RoPacTheme.dark(),
      home: HomeScreen(ropac: ropac),
    );
  }
}
