import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// Dakbox design tokens. One file controls the look: colours, type, radii, shadows.
///
/// Identity: deep ink navigation, a confident "Dak Blue", a saffron spark for everything the
/// assistant does, warm-cool neutrals, and generous rounded panels that float on the canvas.
class DK extends ThemeExtension<DK> {
  const DK({
    required this.bg, required this.surface, required this.surface2, required this.sunken,
    required this.line, required this.line2, required this.text, required this.text2, required this.text3,
    required this.primary, required this.primaryHover, required this.primarySoft, required this.primaryLine,
    required this.ok, required this.okSoft, required this.warn, required this.warnSoft, required this.danger, required this.dangerSoft,
    required this.ink, required this.ink2, required this.inkText, required this.isDark,
  });

  final Color bg, surface, surface2, sunken, line, line2, text, text2, text3;
  final Color primary, primaryHover, primarySoft, primaryLine;
  final Color ok, okSoft, warn, warnSoft, danger, dangerSoft;
  final Color ink, ink2, inkText;
  final bool isDark;

  // Constants shared by both modes.
  static const saffron = Color(0xFFFFB020);
  static const violet = Color(0xFF7B4DFF);
  static const wa = Color(0xFF25D366);
  static const radius = 18.0;
  static const radiusSm = 12.0;

  static const light = DK(
    bg: Color(0xFFF1F3FA), surface: Color(0xFFFFFFFF), surface2: Color(0xFFF7F8FD), sunken: Color(0xFFEDF0F9),
    line: Color(0xFFE3E7F2), line2: Color(0xFFD0D7E8), text: Color(0xFF0D1230), text2: Color(0xFF444C72), text3: Color(0xFF8189AA),
    primary: Color(0xFF3558FA), primaryHover: Color(0xFF2644D8), primarySoft: Color(0xFFEBEEFF), primaryLine: Color(0xFFC8D1FF),
    ok: Color(0xFF0E9F68), okSoft: Color(0xFFE2F6EE), warn: Color(0xFFB87300), warnSoft: Color(0xFFFFF2D6), danger: Color(0xFFD93A42), dangerSoft: Color(0xFFFFEAEA),
    ink: Color(0xFF0A0F26), ink2: Color(0xFF141B40), inkText: Color(0xFFA6B0DB), isDark: false,
  );

  static const dark = DK(
    bg: Color(0xFF080B1A), surface: Color(0xFF10162E), surface2: Color(0xFF141B38), sunken: Color(0xFF0B1024),
    line: Color(0xFF1E2748), line2: Color(0xFF2B3662), text: Color(0xFFEEF1FF), text2: Color(0xFFA7B1DA), text3: Color(0xFF6D78A6),
    primary: Color(0xFF7088FF), primaryHover: Color(0xFF8A9DFF), primarySoft: Color(0xFF18214D), primaryLine: Color(0xFF2D3C8A),
    ok: Color(0xFF3DD598), okSoft: Color(0xFF0E2A24), warn: Color(0xFFFFC24D), warnSoft: Color(0xFF2D2310), danger: Color(0xFFFF7B82), dangerSoft: Color(0xFF331519),
    ink: Color(0xFF060919), ink2: Color(0xFF0E1431), inkText: Color(0xFF8E99C9), isDark: true,
  );

  // Gradients
  LinearGradient get brand => const LinearGradient(colors: [Color(0xFF3558FA), Color(0xFF7B4DFF)], begin: Alignment.topLeft, end: Alignment.bottomRight);
  LinearGradient get hero => const LinearGradient(colors: [Color(0xFF1B2CC1), Color(0xFF4A37E8), Color(0xFF8B4DFF)], begin: Alignment.topLeft, end: Alignment.bottomRight);
  LinearGradient get sidebar => LinearGradient(colors: [ink2, ink], begin: Alignment.topCenter, end: Alignment.bottomCenter);
  LinearGradient get spark => const LinearGradient(colors: [Color(0xFFFFC53D), Color(0xFFFF8A3D)], begin: Alignment.topLeft, end: Alignment.bottomRight);

  List<BoxShadow> get shadow => isDark
      ? [BoxShadow(color: Colors.black.withValues(alpha: .35), blurRadius: 24, offset: const Offset(0, 10), spreadRadius: -8)]
      : [
          BoxShadow(color: const Color(0xFF0D1230).withValues(alpha: .04), blurRadius: 2, offset: const Offset(0, 1)),
          BoxShadow(color: const Color(0xFF1A2766).withValues(alpha: .08), blurRadius: 28, offset: const Offset(0, 12), spreadRadius: -10),
        ];
  List<BoxShadow> get lift => isDark
      ? [BoxShadow(color: Colors.black.withValues(alpha: .5), blurRadius: 40, offset: const Offset(0, 20), spreadRadius: -12)]
      : [BoxShadow(color: const Color(0xFF1A2766).withValues(alpha: .18), blurRadius: 44, offset: const Offset(0, 22), spreadRadius: -14)];

  @override
  DK copyWith() => this;
  @override
  DK lerp(ThemeExtension<DK>? other, double t) => t < .5 ? this : (other as DK? ?? this);
}

extension DKContext on BuildContext {
  DK get c => Theme.of(this).extension<DK>()!;
  bool get isDark => c.isDark;
}

/// Type scale. Display = Bricolage Grotesque, UI = Figtree, Bangla falls back to Hind Siliguri.
class TypeX {
  static const _bn = ['Hind Siliguri', 'Noto Sans Bengali'];

  static TextStyle display(double size, {FontWeight w = FontWeight.w700, Color? color, double? h, double ls = -.02}) =>
      GoogleFonts.bricolageGrotesque(fontSize: size, fontWeight: w, color: color, height: h ?? 1.1, letterSpacing: size * ls)
          .copyWith(fontFamilyFallback: _bn);

  static TextStyle ui(double size, {FontWeight w = FontWeight.w500, Color? color, double? h, double ls = 0}) =>
      GoogleFonts.figtree(fontSize: size, fontWeight: w, color: color, height: h ?? 1.4, letterSpacing: ls).copyWith(fontFamilyFallback: _bn);

  static TextStyle mono(double size, {FontWeight w = FontWeight.w500, Color? color}) =>
      GoogleFonts.jetBrainsMono(fontSize: size, fontWeight: w, color: color, height: 1.35);

  /// Bangla gets more line height so matras never clip.
  static TextStyle bn(double size, {FontWeight w = FontWeight.w500, Color? color}) =>
      GoogleFonts.hindSiliguri(fontSize: size, fontWeight: w, color: color, height: 1.7).copyWith(fontFamilyFallback: const ['Noto Sans Bengali']);
}

ThemeData buildTheme(DK c) {
  final base = ThemeData(
    useMaterial3: true,
    brightness: c.isDark ? Brightness.dark : Brightness.light,
    scaffoldBackgroundColor: c.bg,
    colorScheme: ColorScheme.fromSeed(seedColor: c.primary, brightness: c.isDark ? Brightness.dark : Brightness.light).copyWith(
      primary: c.primary, surface: c.surface, onSurface: c.text, error: c.danger,
    ),
    splashFactory: NoSplash.splashFactory,
    highlightColor: Colors.transparent,
    hoverColor: Colors.transparent,
    dividerColor: c.line,
    extensions: [c],
  );
  return base.copyWith(
    textTheme: base.textTheme.apply(fontFamily: GoogleFonts.figtree().fontFamily, bodyColor: c.text, displayColor: c.text),
    scrollbarTheme: ScrollbarThemeData(thumbColor: WidgetStatePropertyAll(c.line2), radius: const Radius.circular(8), thickness: const WidgetStatePropertyAll(6)),
    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(color: c.ink, borderRadius: BorderRadius.circular(8)),
      textStyle: TypeX.ui(12, w: FontWeight.w600, color: Colors.white),
      waitDuration: const Duration(milliseconds: 350),
    ),
  );
}
