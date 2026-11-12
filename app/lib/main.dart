import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'brand/theme.dart';
import 'core/state.dart';
import 'screens/auth.dart';
import 'screens/platform_ui.dart' show ConsoleShell;
import 'shell/shell.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(ChangeNotifierProvider(create: (_) => AppState(), child: const DakboxApp()));
}

/// Web fonts are fetched on first use. Hold the splash until the ones we need have arrived,
/// so nobody sees fallback letters or Bangla boxes on a cold start.
Future<void> preloadFonts() async {
  const w = [FontWeight.w500, FontWeight.w600, FontWeight.w700, FontWeight.w800];
  for (final x in w) {
    GoogleFonts.figtree(fontWeight: x);
    GoogleFonts.bricolageGrotesque(fontWeight: x);
    GoogleFonts.hindSiliguri(fontWeight: x == FontWeight.w800 ? FontWeight.w700 : x);
  }
  GoogleFonts.jetBrainsMono(fontWeight: FontWeight.w500);
  GoogleFonts.jetBrainsMono(fontWeight: FontWeight.w700);
  try {
    await GoogleFonts.pendingFonts().timeout(const Duration(seconds: 8));
  } catch (_) {/* offline or slow: carry on with fallbacks */}
}

class DakboxApp extends StatefulWidget {
  const DakboxApp({super.key});
  @override
  State<DakboxApp> createState() => _DakboxAppState();
}

class _DakboxAppState extends State<DakboxApp> {
  bool fontsReady = false;
  @override
  void initState() {
    super.initState();
    preloadFonts().then((_) { if (mounted) setState(() => fontsReady = true); });
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    return MaterialApp(
      title: 'Dakbox',
      debugShowCheckedModeBanner: false,
      themeMode: s.themeMode,
      theme: buildTheme(DK.light),
      darkTheme: buildTheme(DK.dark),
      home: !(s.booted && fontsReady) || s.phase == Phase.loading ? const _Splash() : (s.phase == Phase.ready ? (s.inAdmin ? const ConsoleShell() : const Shell()) : const AuthScreen()),
    );
  }
}

class _Splash extends StatelessWidget {
  const _Splash();
  @override
  Widget build(BuildContext context) {
    final c = DK.light;
    return Scaffold(
      backgroundColor: c.bg,
      body: Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Theme(data: buildTheme(DK.light), child: const Brand(light: false)),
          const SizedBox(height: 22),
          SizedBox(width: 120, child: ClipRRect(borderRadius: BorderRadius.circular(8), child: LinearProgressIndicator(minHeight: 4, color: c.primary, backgroundColor: c.sunken))),
        ]),
      ),
    );
  }
}
