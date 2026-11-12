import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:font_awesome_flutter/font_awesome_flutter.dart';
import '../brand/icons.dart';
import '../brand/theme.dart';

// ------------------------------------------------------------------ icon names from the API
IconData iconFor(String? name) => switch (name) {
      'search' => PhosphorIconsRegular.magnifyingGlass,
      'truck' => PhosphorIconsRegular.truck,
      'book' => PhosphorIconsRegular.bookOpenText,
      'alert' => PhosphorIconsRegular.warningCircle,
      'check' => PhosphorIconsBold.check,
      'bell' => PhosphorIconsRegular.bellRinging,
      'user' => PhosphorIconsRegular.userSwitch,
      'package' => PhosphorIconsRegular.package,
      'cart' => PhosphorIconsRegular.shoppingCart,
      'shield' => PhosphorIconsRegular.shieldCheck,
      'note' => PhosphorIconsRegular.notePencil,
      'spark' => PhosphorIconsFill.sparkle,
      'clock' => PhosphorIconsRegular.clock,
      _ => PhosphorIconsRegular.lightning,
    };

// ------------------------------------------------------------------ interaction helpers
class Hover extends StatefulWidget {
  const Hover({super.key, required this.builder, this.onTap, this.cursor = SystemMouseCursors.click, this.pressScale = 1});
  final Widget Function(BuildContext, bool hover, bool pressed) builder;
  final VoidCallback? onTap;
  final MouseCursor cursor;
  final double pressScale;
  @override
  State<Hover> createState() => _HoverState();
}

class _HoverState extends State<Hover> {
  bool h = false, p = false;
  @override
  Widget build(BuildContext context) {
    final child = widget.builder(context, h, p);
    return MouseRegion(
      cursor: widget.onTap == null ? MouseCursor.defer : widget.cursor,
      onEnter: (_) => setState(() => h = true),
      onHover: (_) { if (!h) setState(() => h = true); },   // re-assert after a rebuild or scroll moved a row under a still pointer
      onExit: (_) => setState(() { h = false; p = false; }),
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapDown: widget.onTap == null ? null : (_) => setState(() => p = true),
        onTapCancel: () => setState(() => p = false),
        onTapUp: (_) => setState(() => p = false),
        onTap: widget.onTap,
        child: widget.pressScale == 1 ? child : AnimatedScale(scale: p ? widget.pressScale : 1, duration: const Duration(milliseconds: 90), child: child),
      ),
    );
  }
}

/// Fade and rise on first build. Stagger with [delay].
class Reveal extends StatelessWidget {
  const Reveal({super.key, required this.child, this.delay = 0, this.dy = 10});
  final Widget child;
  final int delay;
  final double dy;
  @override
  Widget build(BuildContext context) {
    if (MediaQuery.of(context).disableAnimations) return child;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: Duration(milliseconds: 380 + delay),
      curve: Interval(delay / (380 + delay), 1, curve: Curves.easeOutCubic),
      builder: (_, t, c) => Opacity(opacity: t.clamp(0, 1), child: Transform.translate(offset: Offset(0, (1 - t) * dy), child: c)),
      child: child,
    );
  }
}

// ------------------------------------------------------------------ surfaces
class Panel extends StatelessWidget {
  const Panel({super.key, required this.child, this.padding, this.radius = DK.radius, this.color, this.border = true, this.clip = true, this.shadow = true});
  final Widget child;
  final EdgeInsetsGeometry? padding;
  final double radius;
  final Color? color;
  final bool border, clip, shadow;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      decoration: BoxDecoration(
        color: color ?? c.surface,
        borderRadius: BorderRadius.circular(radius),
        border: border ? Border.all(color: c.line) : null,
        boxShadow: shadow ? c.shadow : null,
      ),
      clipBehavior: clip ? Clip.antiAlias : Clip.none,
      padding: padding,
      child: child,
    );
  }
}

class Gap extends StatelessWidget {
  const Gap(this.n, {super.key});
  final double n;
  @override
  Widget build(BuildContext context) => SizedBox(width: n, height: n);
}

class Rule extends StatelessWidget {
  const Rule({super.key, this.indent = 0});
  final double indent;
  @override
  Widget build(BuildContext context) => Container(height: 1, margin: EdgeInsets.symmetric(horizontal: indent), color: context.c.line);
}

// ------------------------------------------------------------------ identity
Color hueColor(num hue, {double s = .62, double l = .52}) => HSLColor.fromAHSL(1, (hue % 360).toDouble(), s, l).toColor();

class Avatar extends StatelessWidget {
  const Avatar({super.key, required this.name, this.hue = 210, this.size = 40, this.channel, this.initials});
  final String name;
  final num hue;
  final double size;
  final String? channel;
  final String? initials;
  @override
  Widget build(BuildContext context) {
    final ini = initials ?? _ini(name);
    return SizedBox(
      width: size, height: size,
      child: Stack(clipBehavior: Clip.none, children: [
        Container(
          width: size, height: size, alignment: Alignment.center,
          decoration: BoxDecoration(shape: BoxShape.circle, gradient: LinearGradient(colors: [hueColor(hue, l: .62), hueColor(hue + 28, s: .6, l: .44)], begin: Alignment.topLeft, end: Alignment.bottomRight)),
          child: Text(ini, style: TypeX.display(size * .36, w: FontWeight.w700, color: Colors.white, ls: 0)),
        ),
        if (channel != null) Positioned(right: -3, bottom: -3, child: Container(padding: const EdgeInsets.all(1.5), decoration: BoxDecoration(color: context.c.surface, shape: BoxShape.circle), child: ChannelIcon(kind: channel!, size: math.max(15, size * .38), circle: true))),
      ]),
    );
  }

  static String _ini(String n) {
    final p = n.trim().split(RegExp(r'\s+'));
    if (p.isEmpty || p.first.isEmpty) return '?';
    final a = p.first[0];
    final b = p.length > 1 ? p.last[0] : (p.first.length > 1 ? p.first[1] : '');
    return (a + b).toUpperCase();
  }
}

class ChannelIcon extends StatelessWidget {
  const ChannelIcon({super.key, required this.kind, this.size = 20, this.circle = false});
  final String kind;
  final double size;
  final bool circle;
  @override
  Widget build(BuildContext context) {
    final List<Color> grad = switch (kind) {
      'wa' => const [Color(0xFF3FE07A), Color(0xFF12A94F)],
      'ms' => const [Color(0xFF00B2FF), Color(0xFF7B3CFF)],
      'ig' => const [Color(0xFFFFB347), Color(0xFFE1306C), Color(0xFF7F2FD1)],
      _ => const [Color(0xFF2A3560), Color(0xFF0D1230)],
    };
    return Container(
      width: size, height: size, alignment: Alignment.center,
      decoration: BoxDecoration(
        gradient: LinearGradient(colors: grad, begin: Alignment.topLeft, end: Alignment.bottomRight),
        borderRadius: circle ? null : BorderRadius.circular(size * .3),
        shape: circle ? BoxShape.circle : BoxShape.rectangle,
      ),
      child: switch (kind) {
        'wa' => FaIcon(FontAwesomeIcons.whatsapp, size: size * .56, color: Colors.white),
        'ms' => FaIcon(FontAwesomeIcons.facebookMessenger, size: size * .56, color: Colors.white),
        'ig' => FaIcon(FontAwesomeIcons.instagram, size: size * .56, color: Colors.white),
        _ => Icon(PhosphorIconsFill.globeHemisphereEast, size: size * .56, color: Colors.white),
      },
    );
  }
}

String channelName(String? kind) => switch (kind) { 'wa' => 'WhatsApp', 'ms' => 'Messenger', 'ig' => 'Instagram', 'store' => 'In store', 'site' => 'Website', _ => 'Web chat' };

class AiMark extends StatelessWidget {
  const AiMark({super.key, this.size = 22});
  final double size;
  @override
  Widget build(BuildContext context) => Container(
        width: size, height: size, alignment: Alignment.center,
        decoration: BoxDecoration(gradient: context.c.brand, borderRadius: BorderRadius.circular(size * .32), boxShadow: [BoxShadow(color: DK.violet.withValues(alpha: .35), blurRadius: 10, offset: const Offset(0, 3))]),
        child: Icon(PhosphorIconsFill.sparkle, size: size * .58, color: Colors.white),
      );
}

// ------------------------------------------------------------------ small controls
class Tag extends StatelessWidget {
  const Tag(this.text, {super.key, this.tone = '', this.icon, this.dot = false, this.small = false});
  final String text;
  final String tone; // '', ok, warn, danger, accent, ai
  final IconData? icon;
  final bool dot, small;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final (bg, fg) = switch (tone) {
      'ok' => (c.okSoft, c.ok),
      'warn' => (c.warnSoft, c.warn),
      'danger' => (c.dangerSoft, c.danger),
      'accent' => (c.primarySoft, c.primary),
      'ai' => (c.isDark ? const Color(0xFF2D2310) : const Color(0xFFFFF1D1), c.isDark ? DK.saffron : const Color(0xFF9A5B00)),
      _ => (c.sunken, c.text2),
    };
    return Container(
      height: small ? 20 : 24,
      padding: EdgeInsets.symmetric(horizontal: small ? 7 : 9),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(8)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        if (dot) ...[Container(width: 6, height: 6, decoration: BoxDecoration(color: fg, shape: BoxShape.circle)), const SizedBox(width: 6)],
        if (icon != null) ...[Icon(icon, size: 13, color: fg), const SizedBox(width: 5)],
        Text(text, style: TypeX.ui(small ? 11 : 12, w: FontWeight.w700, color: fg), maxLines: 1),
      ]),
    );
  }
}

enum BtnKind { primary, secondary, soft, ghost, danger }

class DkButton extends StatelessWidget {
  const DkButton(this.label, {super.key, this.icon, this.onPressed, this.kind = BtnKind.secondary, this.small = false, this.expand = false, this.trailing});
  final String label;
  final IconData? icon;
  final VoidCallback? onPressed;
  final BtnKind kind;
  final bool small, expand;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final disabled = onPressed == null;
    return Hover(
      onTap: onPressed,
      pressScale: .97,
      builder: (_, h, p) {
        Color bg, fg, bd = Colors.transparent;
        List<BoxShadow>? sh;
        Gradient? g;
        switch (kind) {
          case BtnKind.primary:
            bg = h ? c.primaryHover : c.primary; fg = Colors.white;
            g = h ? null : LinearGradient(colors: [c.primary, const Color(0xFF4A5CFF)], begin: Alignment.topLeft, end: Alignment.bottomRight);
            sh = [BoxShadow(color: c.primary.withValues(alpha: h ? .42 : .30), blurRadius: h ? 18 : 12, offset: const Offset(0, 6), spreadRadius: -4)];
          case BtnKind.secondary:
            bg = h ? c.surface2 : c.surface; fg = c.text; bd = h ? c.line2 : c.line;
          case BtnKind.soft:
            bg = h ? c.primaryLine.withValues(alpha: .6) : c.primarySoft; fg = c.primary;
          case BtnKind.ghost:
            bg = h ? c.sunken : c.sunken.withValues(alpha: 0); fg = c.text2;
          case BtnKind.danger:
            bg = h ? c.dangerSoft : c.dangerSoft.withValues(alpha: 0); fg = c.danger;
        }
        if (disabled) fg = fg.withValues(alpha: .45);
        return AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          height: small ? 32 : 40,
          padding: EdgeInsets.symmetric(horizontal: small ? 12 : 16),
          decoration: BoxDecoration(color: disabled && kind == BtnKind.primary ? c.primary.withValues(alpha: .35) : bg, gradient: disabled ? null : g, borderRadius: BorderRadius.circular(small ? 10 : 12), border: Border.all(color: bd), boxShadow: disabled ? null : sh),
          child: Row(mainAxisSize: expand ? MainAxisSize.max : MainAxisSize.min, mainAxisAlignment: MainAxisAlignment.center, children: [
            if (icon != null) ...[Icon(icon, size: small ? 15 : 17, color: fg), SizedBox(width: small ? 6 : 8)],
            Flexible(child: Text(label, style: TypeX.ui(small ? 12.5 : 13.5, w: FontWeight.w700, color: fg), maxLines: 1, overflow: TextOverflow.ellipsis)),
            if (trailing != null) ...[const SizedBox(width: 8), trailing!],
          ]),
        );
      },
    );
  }
}

class DkIconButton extends StatelessWidget {
  const DkIconButton(this.icon, {super.key, this.onPressed, this.tooltip, this.active = false, this.size = 38, this.badge});
  final IconData icon;
  final VoidCallback? onPressed;
  final String? tooltip;
  final bool active;
  final double size;
  final int? badge;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final w = Hover(
      onTap: onPressed,
      pressScale: .94,
      builder: (_, h, __) => AnimatedContainer(
        duration: const Duration(milliseconds: 130),
        width: size, height: size,
        decoration: BoxDecoration(color: active ? c.primarySoft : (h ? c.sunken : c.sunken.withValues(alpha: 0)), borderRadius: BorderRadius.circular(11)),
        child: Stack(alignment: Alignment.center, children: [
          Icon(icon, size: 19, color: active ? c.primary : (h ? c.text : c.text2)),
          if (badge != null && badge! > 0) Positioned(top: 4, right: 4, child: Container(constraints: const BoxConstraints(minWidth: 15), height: 15, padding: const EdgeInsets.symmetric(horizontal: 4), decoration: BoxDecoration(color: c.danger, borderRadius: BorderRadius.circular(8)), alignment: Alignment.center, child: Text('$badge', style: TypeX.ui(9.5, w: FontWeight.w800, color: Colors.white)))),
        ]),
      ),
    );
    return tooltip == null ? w : Tooltip(message: tooltip!, child: w);
  }
}

class Seg<T> extends StatelessWidget {
  const Seg({super.key, required this.items, required this.value, required this.onChanged, this.small = false});
  final List<(T, String)> items;
  final T value;
  final ValueChanged<T> onChanged;
  final bool small;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(12)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        for (final (v, label) in items)
          Hover(
            onTap: () => onChanged(v),
            builder: (_, h, __) {
              final on = v == value;
              return AnimatedContainer(
                duration: const Duration(milliseconds: 160),
                height: small ? 28 : 32,
                padding: EdgeInsets.symmetric(horizontal: small ? 11 : 14),
                alignment: Alignment.center,
                decoration: BoxDecoration(color: on ? c.surface : c.surface.withValues(alpha: 0), borderRadius: BorderRadius.circular(9), boxShadow: on ? [BoxShadow(color: Colors.black.withValues(alpha: c.isDark ? .3 : .08), blurRadius: 6, offset: const Offset(0, 2))] : null),
                child: Text(label, style: TypeX.ui(small ? 12 : 12.5, w: FontWeight.w700, color: on ? c.text : (h ? c.text2 : c.text3))),
              );
            },
          ),
      ]),
    );
  }
}

class DkSwitch extends StatelessWidget {
  const DkSwitch({super.key, required this.value, this.onChanged});
  final bool value;
  final ValueChanged<bool>? onChanged;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final off = onChanged == null;
    return Hover(
      onTap: off ? null : () => onChanged!(!value),
      builder: (_, __, ___) => AnimatedContainer(
        duration: const Duration(milliseconds: 170), curve: Curves.easeOutCubic,
        width: 42, height: 24, padding: const EdgeInsets.all(3),
        decoration: BoxDecoration(color: value ? c.primary : c.line2, borderRadius: BorderRadius.circular(99), boxShadow: value ? [BoxShadow(color: c.primary.withValues(alpha: .35), blurRadius: 10, offset: const Offset(0, 3), spreadRadius: -3)] : null),
        child: AnimatedAlign(
          duration: const Duration(milliseconds: 170), curve: Curves.easeOutCubic,
          alignment: value ? Alignment.centerRight : Alignment.centerLeft,
          child: Opacity(opacity: off ? .55 : 1, child: Container(width: 18, height: 18, decoration: const BoxDecoration(color: Colors.white, shape: BoxShape.circle, boxShadow: [BoxShadow(color: Color(0x33000000), blurRadius: 3, offset: Offset(0, 1))]))),
        ),
      ),
    );
  }
}

class SearchBox extends StatelessWidget {
  const SearchBox({super.key, required this.hint, required this.onChanged, this.width, this.controller});
  final String hint;
  final ValueChanged<String> onChanged;
  final double? width;
  final TextEditingController? controller;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return SizedBox(
      width: width, height: 40,
      child: TextField(
        controller: controller,
        onChanged: onChanged,
        style: TypeX.ui(13.5, color: c.text),
        cursorColor: c.primary,
        decoration: InputDecoration(
          hintText: hint, hintStyle: TypeX.ui(13.5, color: c.text3),
          prefixIcon: Icon(PhosphorIconsRegular.magnifyingGlass, size: 18, color: c.text3),
          filled: true, fillColor: c.sunken, isDense: true,
          contentPadding: const EdgeInsets.symmetric(vertical: 11),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
          enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
          focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: c.primary, width: 1.5)),
        ),
      ),
    );
  }
}

class DkField extends StatelessWidget {
  const DkField({super.key, required this.controller, this.hint, this.maxLines = 1, this.mono = false, this.onSubmitted, this.label, this.obscure = false, this.bangla = false});
  final TextEditingController controller;
  final String? hint, label;
  final int maxLines;
  final bool mono, obscure, bangla;
  final ValueChanged<String>? onSubmitted;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final field = TextField(
      controller: controller, maxLines: maxLines, minLines: 1, obscureText: obscure, onSubmitted: onSubmitted,
      style: mono ? TypeX.mono(13, color: c.text) : (bangla ? TypeX.bn(14, color: c.text) : TypeX.ui(14, color: c.text)), cursorColor: c.primary,
      decoration: InputDecoration(
        hintText: hint, hintStyle: TypeX.ui(14, color: c.text3), filled: true, fillColor: c.surface, isDense: true,
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: c.line2)),
        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: c.line2)),
        focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: c.primary, width: 1.6)),
      ),
    );
    if (label == null) return field;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(label!, style: TypeX.ui(12.5, w: FontWeight.w700, color: c.text2)), const SizedBox(height: 6), field]);
  }
}

class Empty extends StatelessWidget {
  const Empty(this.title, {super.key, this.body, this.icon});
  final String title;
  final String? body;
  final IconData? icon;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Container(width: 56, height: 56, decoration: BoxDecoration(color: c.primarySoft, borderRadius: BorderRadius.circular(18)), child: Icon(icon ?? PhosphorIconsDuotone.tray, size: 26, color: c.primary)),
          const SizedBox(height: 14),
          Text(title, style: TypeX.display(17, color: c.text)),
          if (body != null) ...[const SizedBox(height: 6), Text(body!, textAlign: TextAlign.center, style: TypeX.ui(13.5, color: c.text3))],
        ]),
      ),
    );
  }
}

class Kv extends StatelessWidget {
  const Kv(this.k, this.v, {super.key, this.mono = false, this.child});
  final String k;
  final String? v;
  final bool mono;
  final Widget? child;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(k, style: TypeX.ui(13, color: c.text3)),
        const SizedBox(width: 16),
        Expanded(child: Align(alignment: Alignment.centerRight, child: child ?? Text(v ?? '—', textAlign: TextAlign.right, style: mono ? TypeX.mono(12.5, color: c.text) : TypeX.ui(13, w: FontWeight.w600, color: c.text)))),
      ]),
    );
  }
}

class Label extends StatelessWidget {
  const Label(this.text, {super.key});
  final String text;
  @override
  Widget build(BuildContext context) => Text(text.toUpperCase(), style: TypeX.ui(11, w: FontWeight.w800, color: context.c.text3, ls: .9));
}

// ------------------------------------------------------------------ product art, drawn
class ProductArt extends StatelessWidget {
  const ProductArt({super.key, required this.kind, this.size = 48, this.radius});
  final String? kind;
  final double size;
  final double? radius;
  @override
  Widget build(BuildContext context) => ClipRRect(
        borderRadius: BorderRadius.circular(radius ?? size * .22),
        child: SizedBox(width: size, height: size, child: CustomPaint(painter: _ArtPainter(kind ?? ''))),
      );
}

/// A product's photo when it has one (imported from a website), otherwise the drawn illustration. Photos live on other
/// websites, so on the web they fall back to a plain <img> when the site does not allow canvas access.
class ProductPhoto extends StatelessWidget {
  const ProductPhoto({super.key, required this.image, required this.kind, this.size = 48, this.radius});
  final String? image, kind;
  final double size;
  final double? radius;
  @override
  Widget build(BuildContext context) {
    final art = ProductArt(kind: kind, size: size, radius: radius);
    if (image == null || image!.isEmpty) return art;
    return ClipRRect(
      borderRadius: BorderRadius.circular(radius ?? size * .22),
      child: SizedBox(
        width: size, height: size,
        child: Image.network(image!, fit: BoxFit.cover, webHtmlElementStrategy: WebHtmlElementStrategy.fallback, gaplessPlayback: true,
            errorBuilder: (_, __, ___) => art, loadingBuilder: (_, child, p) => p == null ? child : art),
      ),
    );
  }
}

class _ArtPainter extends CustomPainter {
  _ArtPainter(this.kind);
  final String kind;

  static const _bg = {
    'bottle': [Color(0xFFDDE8FA), Color(0xFFC3D5F5)],
    'tent': [Color(0xFFFCEBD3), Color(0xFFF6D7B0)],
    'boot': [Color(0xFFEFE6D8), Color(0xFFE2D4BE)],
    'jacket': [Color(0xFFE2EEE5), Color(0xFFCADFD0)],
  };

  @override
  void paint(Canvas canvas, Size full) {
    final bg = _bg[kind] ?? const [Color(0xFFE6E9F4), Color(0xFFD5DAEC)];
    canvas.drawRect(Offset.zero & full, Paint()..shader = LinearGradient(colors: bg, begin: Alignment.topCenter, end: Alignment.bottomCenter).createShader(Offset.zero & full));
    // Draw the product in a centred square so it never stretches.
    final side = math.min(full.width, full.height);
    canvas.save();
    canvas.translate((full.width - side) / 2, (full.height - side) / 2);
    final w = side, h = side;
    Paint p(Color c) => Paint()..color = c;
    RRect rr(double x, double y, double ww, double hh, double r) => RRect.fromRectAndRadius(Rect.fromLTWH(x * w, y * h, ww * w, hh * h), Radius.circular(r * w));
    switch (kind) {
      case 'bottle':
        canvas.drawRRect(rr(.41, .12, .18, .14, .04), p(const Color(0xFF0E2038)));
        canvas.drawRRect(rr(.33, .24, .34, .62, .11), p(const Color(0xFF1D3A63)));
        canvas.drawRect(Rect.fromLTWH(.33 * w, .52 * h, .34 * w, .09 * h), p(const Color(0xFF2D5A96)));
        canvas.drawRRect(rr(.39, .31, .045, .45, .02), p(Colors.white.withValues(alpha: .25)));
      case 'tent':
        canvas.drawPath(Path()..moveTo(.12 * w, .78 * h)..lineTo(.5 * w, .2 * h)..lineTo(.88 * w, .78 * h)..close(), p(const Color(0xFFE2702F)));
        canvas.drawPath(Path()..moveTo(.5 * w, .2 * h)..lineTo(.12 * w, .78 * h)..lineTo(.28 * w, .78 * h)..close(), p(const Color(0xFFC85A21)));
        canvas.drawPath(Path()..moveTo(.5 * w, .4 * h)..lineTo(.38 * w, .78 * h)..lineTo(.62 * w, .78 * h)..close(), p(const Color(0xFF8C3C14)));
        canvas.drawRRect(rr(.06, .78, .88, .05, .02), p(const Color(0xFF7B6A58)));
      case 'boot':
        final b = Path()..moveTo(.28 * w, .18 * h)..lineTo(.5 * w, .18 * h)..lineTo(.5 * w, .5 * h)..lineTo(.74 * w, .6 * h)..quadraticBezierTo(.84 * w, .64 * h, .84 * w, .74 * h)..lineTo(.84 * w, .78 * h)..lineTo(.2 * w, .78 * h)..close();
        canvas.drawPath(b, p(const Color(0xFF7A4E2C)));
        canvas.drawRRect(rr(.16, .74, .72, .09, .03), p(const Color(0xFF2B2622)));
        final l = Paint()..color = const Color(0xFFE8D3B9)..strokeWidth = w * .035;
        canvas.drawLine(Offset(.32 * w, .3 * h), Offset(.48 * w, .3 * h), l);
        canvas.drawLine(Offset(.32 * w, .4 * h), Offset(.48 * w, .4 * h), l);
      case 'jacket':
        final j = Path()..moveTo(.34 * w, .2 * h)..lineTo(.5 * w, .27 * h)..lineTo(.66 * w, .2 * h)..lineTo(.84 * w, .33 * h)..lineTo(.74 * w, .44 * h)..lineTo(.74 * w, .82 * h)..lineTo(.26 * w, .82 * h)..lineTo(.26 * w, .44 * h)..lineTo(.16 * w, .33 * h)..close();
        canvas.drawPath(j, p(const Color(0xFF2F6B4A)));
        canvas.drawLine(Offset(.5 * w, .27 * h), Offset(.5 * w, .82 * h), Paint()..color = const Color(0xFF1F4A33)..strokeWidth = w * .03);
      default:
        canvas.drawRRect(rr(.3, .3, .4, .4, .08), p(const Color(0xFF9AA4C8)));
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _ArtPainter old) => old.kind != kind;
}

// ------------------------------------------------------------------ typing dots
class TypingDots extends StatefulWidget {
  const TypingDots({super.key, this.color});
  final Color? color;
  @override
  State<TypingDots> createState() => _TypingDotsState();
}

class _TypingDotsState extends State<TypingDots> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1200))..repeat();
  @override
  void dispose() { _c.dispose(); super.dispose(); }
  @override
  Widget build(BuildContext context) {
    final col = widget.color ?? context.c.text3;
    return AnimatedBuilder(
      animation: _c,
      builder: (_, __) => Row(mainAxisSize: MainAxisSize.min, children: [
        for (var i = 0; i < 3; i++)
          Container(
            width: 6, height: 6, margin: const EdgeInsets.symmetric(horizontal: 2),
            decoration: BoxDecoration(color: col.withValues(alpha: .25 + .75 * (math.sin((_c.value * 2 * math.pi) - i * .9) * .5 + .5)), shape: BoxShape.circle),
          ),
      ]),
    );
  }
}
