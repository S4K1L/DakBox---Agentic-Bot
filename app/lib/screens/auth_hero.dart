import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../brand/icons.dart';
import '../brand/theme.dart';
import '../shell/shell.dart' show Brand;
import '../widgets/kit.dart';

/// The brand panel beside the sign-in form: a slowly moving aurora, a fine dot grid, the promise in one line, and a looping example conversation
/// (a customer writes, the assistant looks something up and answers). Nothing here names a real person: the customers are only "a WhatsApp customer" and so on.
class AuthHero extends StatefulWidget {
  const AuthHero({super.key, this.setup = false});
  final bool setup;                  // first-run account creation: the stage shows a setup checklist instead of the example conversation
  @override
  State<AuthHero> createState() => _AuthHeroState();
}

class _AuthHeroState extends State<AuthHero> with SingleTickerProviderStateMixin {
  late final AnimationController _drift = AnimationController(vsync: this, duration: const Duration(seconds: 36));
  bool _started = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_started) return;
    _started = true;
    if (!MediaQuery.of(context).disableAnimations) _drift.repeat();
  }

  @override
  void dispose() { _drift.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(gradient: LinearGradient(colors: [Color(0xFF0E1A8F), Color(0xFF3326C9), Color(0xFF6A3CF0)], begin: Alignment.topLeft, end: Alignment.bottomRight)),
      clipBehavior: Clip.antiAlias,
      child: Stack(children: [
        Positioned.fill(child: RepaintBoundary(child: CustomPaint(painter: _AuroraPainter(_drift)))),
        Positioned.fill(child: CustomPaint(painter: _DotGridPainter())),
        Positioned.fill(
          child: LayoutBuilder(builder: (context, box) {
            final h = box.maxHeight;
            final stage = h >= 640, features = h >= 780;
            return Padding(
              padding: EdgeInsets.fromLTRB(64, h >= 700 ? 56 : 40, 64, h >= 700 ? 44 : 32),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Reveal(child: Brand()),
                const Spacer(flex: 2),
                Reveal(delay: 80, child: Text(widget.setup ? 'Start with\none account.' : 'Every chat.\nOne inbox.', style: TypeX.display(h >= 700 ? 58 : 46, color: Colors.white, h: 1.02, ls: -.04))),
                const Gap(16),
                Reveal(delay: 180, child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 470), child: Text(widget.setup
                    ? 'Create the owner account, add your products and connect your channels. Your team then gets their own sign-ins, with exactly the access you give them.'
                    : 'WhatsApp, Messenger, Instagram and your website in one place. An assistant answers in Bangla, Banglish and English, does the lookups, and hands over to your team when it should.', style: TypeX.ui(15.5, color: Colors.white.withValues(alpha: .8), h: 1.55)))),
                if (stage) ...[const Gap(30), Reveal(delay: 300, dy: 16, child: widget.setup ? const _SetupStage() : const _Stage())],
                const Spacer(flex: 2),
                if (features) Reveal(delay: 460, child: widget.setup ? const _SetupFeatures() : const _Features()),
                if (!features) Reveal(delay: 460, child: Row(children: [for (final k in ['wa', 'ms', 'ig', 'web']) Padding(padding: const EdgeInsets.only(right: 10), child: ChannelIcon(kind: k, size: 28))])),
              ]),
            );
          }),
        ),
      ]),
    );
  }
}

// ------------------------------------------------------------------ background
class _AuroraPainter extends CustomPainter {
  _AuroraPainter(this.t) : super(repaint: t);
  final Animation<double> t;

  @override
  void paint(Canvas canvas, Size size) {
    final a = t.value * math.pi * 2;
    void orb(Offset c, double r, Color color) {
      final rect = Rect.fromCircle(center: c, radius: r);
      canvas.drawCircle(c, r, Paint()..shader = RadialGradient(colors: [color, color.withValues(alpha: 0)]).createShader(rect));
    }
    final w = size.width, h = size.height;
    orb(Offset(w * (.82 + .06 * math.sin(a)), h * (.10 + .06 * math.cos(a))), w * .62, const Color(0xFF9A5BFF).withValues(alpha: .55));
    orb(Offset(w * (.08 + .07 * math.cos(a * 1)), h * (.92 + .05 * math.sin(a))), w * .70, const Color(0xFF2A8CFF).withValues(alpha: .42));
    orb(Offset(w * (.55 + .10 * math.sin(a + 2)), h * (.55 + .08 * math.cos(a + 1))), w * .42, const Color(0xFFD14DFF).withValues(alpha: .20));
  }

  @override
  bool shouldRepaint(_AuroraPainter old) => false;
}

class _DotGridPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()..color = Colors.white.withValues(alpha: .07);
    for (double x = 18; x < size.width; x += 28) {
      for (double y = 18; y < size.height; y += 28) {
        canvas.drawCircle(Offset(x, y), 1, p);
      }
    }
  }

  @override
  bool shouldRepaint(_DotGridPainter old) => false;
}

// ------------------------------------------------------------------ the example conversation
class _Scene {
  const _Scene(this.kind, this.topic, this.ask, this.answer, this.did, this.icon, {this.bn = false});
  final String kind, topic, ask, answer, did;
  final IconData icon;
  final bool bn;
}

final _scenes = <_Scene>[
  _Scene('wa', 'Order status', 'bhai amar order ta kothay? #1042', 'Apnar order Steadfast e ache, kal pouchabe. Tracking SF-26110841.', 'Checked order #1042 and its parcel', PhosphorIconsFill.package),
  _Scene('ms', 'Product question', 'ট্রেইল বোতল ২ লিটার নেভি আছে?', 'জি, ২ লিটার নেভি রঙে আছে। এখন স্টকে ৬টি আছে। কার্টে দিয়ে দেব?', 'Searched the catalogue', PhosphorIconsFill.shoppingBag, bn: true),
  _Scene('ig', 'Delivery charge', 'How much is delivery to Chattogram?', 'Delivery to Chattogram is ৳120 and takes 2 to 3 days. Shall I add it to your order?', 'Worked out the delivery charge', PhosphorIconsFill.sealCheck),
];

class _Stage extends StatefulWidget {
  const _Stage();
  @override
  State<_Stage> createState() => _StageState();
}

class _StageState extends State<_Stage> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 11000));
  int _i = 0;
  bool _still = false;

  @override
  void initState() {
    super.initState();
    _c.addStatusListener((s) {
      if (s == AnimationStatus.completed && mounted && !_still) {
        setState(() => _i = (_i + 1) % _scenes.length);
        _c.forward(from: 0);
      }
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _still = MediaQuery.of(context).disableAnimations;
    if (_still) { _c.value = .72; } else if (!_c.isAnimating) { _c.forward(); }
  }

  @override
  void dispose() { _c.dispose(); super.dispose(); }

  static double _seg(double t, double a, double b) => Curves.easeOutCubic.transform(((t - a) / (b - a)).clamp(0.0, 1.0));

  @override
  Widget build(BuildContext context) {
    final sc = _scenes[_i];
    return Container(
      constraints: const BoxConstraints(maxWidth: 480),
      height: 268,
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: .09),
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: Colors.white.withValues(alpha: .18)),
        boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: .22), blurRadius: 40, offset: const Offset(0, 22), spreadRadius: -18)],
      ),
      child: AnimatedBuilder(
        animation: _c,
        builder: (context, _) {
          final t = _c.value;
          final out = 1 - _seg(t, .90, 1.0);                       // the whole scene fades before the next one
          final ask = _seg(t, .03, .12);
          final typing = _seg(t, .17, .21) * (1 - _seg(t, .38, .42));
          final answer = _seg(t, .38, .47);
          final did = _seg(t, .50, .58);
          return Opacity(
            opacity: out,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Container(width: 7, height: 7, decoration: const BoxDecoration(color: Color(0xFF3DD598), shape: BoxShape.circle)),
                const SizedBox(width: 8),
                Text('EXAMPLE CONVERSATION', style: TypeX.ui(10.5, w: FontWeight.w800, color: Colors.white.withValues(alpha: .65), ls: 1.1)),
                const Spacer(),
                for (var k = 0; k < _scenes.length; k++) AnimatedContainer(duration: const Duration(milliseconds: 250), width: k == _i ? 18 : 6, height: 6, margin: const EdgeInsets.only(left: 5), decoration: BoxDecoration(color: Colors.white.withValues(alpha: k == _i ? .9 : .3), borderRadius: BorderRadius.circular(3))),
              ]),
              const SizedBox(height: 14),
              _pop(ask, 14, Align(alignment: Alignment.centerLeft, child: _Ask(sc))),
              const SizedBox(height: 10),
              SizedBox(
                height: 78,
                child: Stack(children: [
                  if (typing > 0.01) Positioned(right: 0, top: 0, child: Opacity(opacity: typing, child: _Typing(t: t))),
                  if (answer > 0.01) Positioned(right: 0, top: 0, left: 36, child: _pop(answer, 14, Align(alignment: Alignment.centerRight, child: _Answer(sc)))),
                ]),
              ),
              const Spacer(),
              _pop(did, 8, Align(alignment: Alignment.centerRight, child: _Did(sc))),
            ]),
          );
        },
      ),
    );
  }

  Widget _pop(double v, double dy, Widget child) => Opacity(opacity: v.clamp(0, 1), child: Transform.translate(offset: Offset(0, (1 - v) * dy), child: child));
}

class _Ask extends StatelessWidget {
  const _Ask(this.s);
  final _Scene s;
  @override
  Widget build(BuildContext context) => Container(
        constraints: const BoxConstraints(maxWidth: 340),
        padding: const EdgeInsets.fromLTRB(10, 9, 14, 9),
        decoration: BoxDecoration(color: Colors.white.withValues(alpha: .14), borderRadius: BorderRadius.circular(16), border: Border.all(color: Colors.white.withValues(alpha: .2))),
        child: Row(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          ChannelIcon(kind: s.kind, size: 26, circle: true),
          const SizedBox(width: 10),
          Flexible(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${channelName(s.kind)} customer · ${s.topic}', style: TypeX.ui(11, w: FontWeight.w700, color: Colors.white.withValues(alpha: .7))),
            const SizedBox(height: 2),
            Text(s.ask, style: s.bn ? TypeX.bn(14, color: Colors.white) : TypeX.ui(14, color: Colors.white)),
          ])),
        ]),
      );
}

class _Answer extends StatelessWidget {
  const _Answer(this.s);
  final _Scene s;
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.fromLTRB(10, 9, 14, 10),
        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16), boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: .25), blurRadius: 26, offset: const Offset(0, 12), spreadRadius: -10)]),
        child: Row(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          const AiMark(size: 26),
          const SizedBox(width: 10),
          Flexible(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Assistant', style: TypeX.ui(11, w: FontWeight.w800, color: const Color(0xFF3558FA))),
            const SizedBox(height: 2),
            Text(s.answer, style: s.bn ? TypeX.bn(13.5, color: const Color(0xFF0D1230)) : TypeX.ui(13.5, color: const Color(0xFF0D1230), h: 1.35)),
          ])),
        ]),
      );
}

class _Did extends StatelessWidget {
  const _Did(this.s);
  final _Scene s;
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(color: Colors.white.withValues(alpha: .12), borderRadius: BorderRadius.circular(20), border: Border.all(color: Colors.white.withValues(alpha: .18))),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(s.icon, size: 13, color: const Color(0xFF9DE8C5)),
          const SizedBox(width: 6),
          Text(s.did, style: TypeX.ui(11.5, w: FontWeight.w600, color: Colors.white.withValues(alpha: .85))),
        ]),
      );
}

class _Typing extends StatelessWidget {
  const _Typing({required this.t});
  final double t;
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          for (var d = 0; d < 3; d++) Container(width: 6, height: 6, margin: EdgeInsets.only(right: d == 2 ? 0 : 4), transform: Matrix4.translationValues(0, -3 * math.max(0, math.sin(t * 90 - d * 1.1)), 0), decoration: const BoxDecoration(color: Color(0xFF7B8AD6), shape: BoxShape.circle)),
        ]),
      );
}

// ------------------------------------------------------------------ what it does, in three lines
class _Features extends StatelessWidget {
  const _Features();
  @override
  Widget build(BuildContext context) {
    Widget f(IconData i, String t, String b) => Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(width: 34, height: 34, alignment: Alignment.center, decoration: BoxDecoration(color: Colors.white.withValues(alpha: .12), borderRadius: BorderRadius.circular(11)), child: Icon(i, size: 17, color: Colors.white)),
            const SizedBox(height: 10),
            Text(t, style: TypeX.ui(13.5, w: FontWeight.w700, color: Colors.white)),
            const SizedBox(height: 3),
            Text(b, style: TypeX.ui(12, color: Colors.white.withValues(alpha: .68), h: 1.4)),
          ]),
        );
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      f(PhosphorIconsRegular.translate, 'Their language', 'Bangla, Banglish and English, matched to the customer.'),
      const SizedBox(width: 20),
      f(PhosphorIconsRegular.shoppingBag, 'Real work', 'Prices, stock, orders, payments and couriers.'),
      const SizedBox(width: 20),
      f(PhosphorIconsRegular.userSwitch, 'Your team in control', 'Hands over when it is unsure; you approve what matters.'),
    ]);
  }
}


// ------------------------------------------------------------------ first-run setup: the checklist that fills in
class _SetupStage extends StatefulWidget {
  const _SetupStage();
  @override
  State<_SetupStage> createState() => _SetupStageState();
}

class _SetupStageState extends State<_SetupStage> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 9000));
  static const _steps = [
    (PhosphorIconsFill.users, 'Create the owner account', 'You, with full control'),
    (PhosphorIconsFill.package, 'Add your products', 'Import from your website, or add them by hand'),
    (PhosphorIconsFill.plugsConnected, 'Connect your channels', 'Messenger, Instagram, WhatsApp and website chat'),
    (PhosphorIconsFill.sparkle, 'Switch on the assistant', 'Pick the AI and send a test message'),
  ];
  bool _still = false;

  @override
  void initState() {
    super.initState();
    _c.addStatusListener((s) { if (s == AnimationStatus.completed && mounted && !_still) { _c.forward(from: 0); } });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _still = MediaQuery.of(context).disableAnimations;
    if (_still) { _c.value = .9; } else if (!_c.isAnimating) { _c.forward(); }
  }

  @override
  void dispose() { _c.dispose(); super.dispose(); }

  static double _seg(double t, double a, double b) => Curves.easeOutCubic.transform(((t - a) / (b - a)).clamp(0.0, 1.0));

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(maxWidth: 480),
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: .09), borderRadius: BorderRadius.circular(24), border: Border.all(color: Colors.white.withValues(alpha: .18)),
        boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: .22), blurRadius: 40, offset: const Offset(0, 22), spreadRadius: -18)],
      ),
      child: AnimatedBuilder(
        animation: _c,
        builder: (context, _) {
          final t = _c.value;
          final out = 1 - _seg(t, .94, 1.0);
          final done = [for (var i = 0; i < _steps.length; i++) _seg(t, .10 + i * .20, .22 + i * .20)];
          final progress = done.fold<double>(0, (a, b) => a + b) / _steps.length;
          return Opacity(
            opacity: out,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Text('YOUR WORKSPACE', style: TypeX.ui(10.5, w: FontWeight.w800, color: Colors.white.withValues(alpha: .65), ls: 1.1)),
                const Spacer(),
                Text('${(progress * 100).round()}%', style: TypeX.mono(12, w: FontWeight.w700, color: Colors.white.withValues(alpha: .9))),
              ]),
              const SizedBox(height: 10),
              ClipRRect(borderRadius: BorderRadius.circular(4), child: LinearProgressIndicator(value: progress, minHeight: 5, backgroundColor: Colors.white.withValues(alpha: .15), color: const Color(0xFF9DE8C5))),
              const SizedBox(height: 14),
              for (var i = 0; i < _steps.length; i++) _row(i, done[i], t),
              const SizedBox(height: 4),
              Opacity(opacity: _seg(t, .84, .92), child: Row(children: [
                const Icon(PhosphorIconsFill.checkCircle, size: 16, color: Color(0xFF9DE8C5)),
                const SizedBox(width: 8),
                Text('Ready to take messages', style: TypeX.ui(13, w: FontWeight.w700, color: Colors.white)),
              ])),
            ]),
          );
        },
      ),
    );
  }

  Widget _row(int i, double d, double t) {
    final (icon, title, sub) = _steps[i];
    final active = t >= .10 + i * .20 - .04 && d < 1;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(children: [
        Stack(alignment: Alignment.center, children: [
          Container(width: 34, height: 34, alignment: Alignment.center, decoration: BoxDecoration(color: Color.lerp(Colors.white.withValues(alpha: .12), const Color(0xFF3DD598), d), borderRadius: BorderRadius.circular(11)),
              child: d >= .98 ? const Icon(PhosphorIconsBold.check, size: 17, color: Colors.white) : Icon(icon, size: 17, color: Colors.white.withValues(alpha: .85))),
          if (active) SizedBox(width: 34, height: 34, child: CircularProgressIndicator(strokeWidth: 2, value: d.clamp(.08, 1), color: Colors.white, backgroundColor: Colors.transparent)),
        ]),
        const SizedBox(width: 12),
        Expanded(child: Opacity(opacity: .55 + .45 * math.max(d, active ? 1 : 0), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: TypeX.ui(13.5, w: FontWeight.w700, color: Colors.white)),
          Text(sub, style: TypeX.ui(11.5, color: Colors.white.withValues(alpha: .7))),
        ]))),
      ]),
    );
  }
}

class _SetupFeatures extends StatelessWidget {
  const _SetupFeatures();
  @override
  Widget build(BuildContext context) {
    Widget f(IconData i, String t, String b) => Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(width: 34, height: 34, alignment: Alignment.center, decoration: BoxDecoration(color: Colors.white.withValues(alpha: .12), borderRadius: BorderRadius.circular(11)), child: Icon(i, size: 17, color: Colors.white)),
            const SizedBox(height: 10),
            Text(t, style: TypeX.ui(13.5, w: FontWeight.w700, color: Colors.white)),
            const SizedBox(height: 3),
            Text(b, style: TypeX.ui(12, color: Colors.white.withValues(alpha: .68), h: 1.4)),
          ]),
        );
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      f(PhosphorIconsRegular.key, 'Owner access', 'Only you can add owners, change plans or remove people.'),
      const SizedBox(width: 20),
      f(PhosphorIconsRegular.usersThree, 'Roles for your team', 'Owner, admin, agent or viewer, each with set permissions.'),
      const SizedBox(width: 20),
      f(PhosphorIconsRegular.sealCheck, 'Safe by default', 'Stored keys are encrypted; money steps wait for approval.'),
    ]);
  }
}
