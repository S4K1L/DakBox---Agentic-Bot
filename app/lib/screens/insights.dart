import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../brand/icons.dart';
import 'package:provider/provider.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';
import '../widgets/page.dart' show StatTile;

class InsightsScreen extends StatefulWidget {
  const InsightsScreen({super.key});
  @override
  State<InsightsScreen> createState() => _InsightsScreenState();
}

class _InsightsScreenState extends State<InsightsScreen> {
  @override
  void initState() {
    super.initState();
    context.read<AppState>().loadInsights();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final d = s.insights;
    if (d == null) return Panel(child: Center(child: CircularProgressIndicator(color: c.primary, strokeWidth: 3)));
    final k = d['kpis'] as J;
    final series = (d['handledSeries'] as List).cast<num>();
    final live = d['live'] as J;
    final chans = (d['channels'] as List).cast<J>();
    final reasons = (d['reasons'] as List).map((e) => (e as List)).toList();
    final w = MediaQuery.of(context).size.width;
    final narrow = w < 900;

    final hero = Reveal(
      child: Container(
        decoration: BoxDecoration(gradient: c.hero, borderRadius: BorderRadius.circular(24), boxShadow: [BoxShadow(color: const Color(0xFF4A37E8).withValues(alpha: .35), blurRadius: 40, offset: const Offset(0, 20), spreadRadius: -16)]),
        clipBehavior: Clip.antiAlias,
        child: Stack(children: [
          Positioned(right: -60, top: -80, child: Container(width: 280, height: 280, decoration: BoxDecoration(shape: BoxShape.circle, color: Colors.white.withValues(alpha: .07)))),
          Positioned(right: 80, bottom: -120, child: Container(width: 260, height: 260, decoration: BoxDecoration(shape: BoxShape.circle, color: Colors.white.withValues(alpha: .05)))),
          Padding(
            padding: EdgeInsets.all(narrow ? 22 : 30),
            child: Flex(direction: narrow ? Axis.vertical : Axis.horizontal, crossAxisAlignment: narrow ? CrossAxisAlignment.start : CrossAxisAlignment.center, children: [
              Flexible(
                flex: narrow ? 0 : 5,
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [const Icon(PhosphorIconsFill.sparkle, size: 15, color: DK.saffron), const SizedBox(width: 7), Text('HANDLED WITHOUT A PERSON', style: TypeX.ui(11.5, w: FontWeight.w800, color: Colors.white70, ls: 1))]),
                  const SizedBox(height: 10),
                  TweenAnimationBuilder<double>(tween: Tween(end: (k['handled'] as num).toDouble()), duration: const Duration(milliseconds: 1100), curve: Curves.easeOutCubic, builder: (_, v, __) => Text('${v.round()}%', style: TypeX.display(narrow ? 64 : 84, color: Colors.white, ls: -.04))),
                  const SizedBox(height: 4),
                  Text('Sample figure. The assistant closed more than half of all conversations on its own.', style: TypeX.ui(14, color: Colors.white.withValues(alpha: .8), h: 1.5)),
                ]),
              ),
              SizedBox(width: narrow ? 0 : 32, height: narrow ? 22 : 0),
              Flexible(flex: narrow ? 0 : 6, child: SizedBox(height: narrow ? 120 : 150, width: double.infinity, child: _Spark(values: series))),
            ]),
          ),
        ]),
      ),
    );

    Widget kpi(String label, String value, String delta, {bool bad = false, IconData? icon, int i = 0}) => Reveal(
          delay: 80 + i * 50,
          child: Panel(
            padding: const EdgeInsets.all(18),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [Container(width: 32, height: 32, decoration: BoxDecoration(color: c.primarySoft, borderRadius: BorderRadius.circular(10)), child: Icon(icon ?? PhosphorIconsRegular.chartLineUp, size: 17, color: c.primary)), const Spacer(), Tag(delta, small: true)]),
              const SizedBox(height: 14),
              Text(value, style: TypeX.display(30, color: c.text, ls: -.03)),
              const SizedBox(height: 3),
              Text(label, style: TypeX.ui(12.5, color: c.text3)),
            ]),
          ),
        );

    final kpis = [
      kpi('Median first reply', '${k['firstReply']} s', 'sample', icon: PhosphorIconsRegular.timer, i: 0),
      kpi('Customer rating', '${k['rating']} / 5', 'sample', icon: PhosphorIconsRegular.star, i: 1),
      kpi('Handed to a person', '${k['handoff']}%', 'sample', bad: true, icon: PhosphorIconsRegular.userSwitch, i: 2),
      kpi('Revenue from chat', taka(k['revenue'] as num), 'sample', icon: PhosphorIconsRegular.coins, i: 3),
      kpi('Orders started in chat', '${k['chatOrders']}', 'sample', icon: PhosphorIconsRegular.shoppingBag, i: 4),
      kpi('Chats that became orders', '${k['conversion']}%', 'sample', icon: PhosphorIconsRegular.funnel, i: 5),
    ];

    Widget section(String title, String sub, {Widget? tag}) => Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: TypeX.display(19, color: c.text, ls: -.01)), const SizedBox(height: 2), Text(sub, style: TypeX.ui(12.5, color: c.text3))])),
            if (tag != null) tag,
          ]),
        );

    return Panel(
      color: c.surface2,
      child: ListView(padding: EdgeInsets.all(narrow ? 16 : 24), children: [
        Text('Insights', style: TypeX.display(narrow ? 24 : 28, color: c.text)),
        const SizedBox(height: 4),
        Text('What is happening in this workspace right now, and how the assistant is performing.', style: TypeX.ui(13.5, color: c.text3)),
        const Gap(22),
        section('Right now', 'Real numbers from this workspace, updated live.', tag: const Tag('Live', tone: 'ok', dot: true, small: true)),
        Row(children: [
          StatTile(value: '${live['open']}', label: 'Open conversations', icon: PhosphorIconsRegular.chatCircleText),
          const SizedBox(width: 10),
          StatTile(value: '${live['needsYou']}', label: 'Waiting on you', icon: PhosphorIconsRegular.userSwitch, tone: (live['needsYou'] as num) > 0 ? 'warn' : 'ok'),
          const SizedBox(width: 10),
          StatTile(value: '${live['agentRuns']}', label: 'Assistant replies', icon: PhosphorIconsFill.sparkle),
          const SizedBox(width: 10),
          StatTile(value: '${live['avgAgentMs']} ms', label: 'Avg assistant time', icon: PhosphorIconsRegular.timer),
        ]),
        const Gap(10),
        Row(children: [
          StatTile(value: '${live['paidOrders']}', label: 'Paid orders', icon: PhosphorIconsRegular.creditCard, tone: 'ok'),
          const SizedBox(width: 10),
          StatTile(value: '${live['chatOrders'] ?? 0}', label: 'Orders placed in chat', icon: PhosphorIconsRegular.shoppingBag, tone: 'ok'),
          const SizedBox(width: 10),
          StatTile(value: taka((live['chatRevenue'] ?? 0) as num), label: 'Revenue from chat orders', icon: PhosphorIconsRegular.coins, tone: 'ok'),
          const SizedBox(width: 10),
          const Expanded(child: SizedBox.shrink()),
        ]),
        const Gap(30),
        section('Assistant performance', 'Trends over time need weeks of real history.', tag: const Tag('Sample data', tone: 'warn', small: true)),
        Container(
          margin: const EdgeInsets.only(bottom: 14), padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: c.warnSoft, borderRadius: BorderRadius.circular(12), border: Border.all(color: c.warn.withValues(alpha: .25))),
          child: Row(children: [Icon(PhosphorIconsFill.warningCircle, size: 17, color: c.warn), const SizedBox(width: 10), Expanded(child: Text('Everything below is illustrative sample data so you can see the layout. It is not measured from your conversations yet.', style: TypeX.ui(12.5, w: FontWeight.w600, color: c.text, h: 1.4)))]),
        ),
        hero,
        const Gap(14),
        LayoutBuilder(builder: (context, box) {
          final cols = box.maxWidth > 1000 ? 3 : (box.maxWidth > 560 ? 2 : 1);
          final cw = (box.maxWidth - 14 * (cols - 1)) / cols;
          return Wrap(spacing: 14, runSpacing: 14, children: [for (final x in kpis) SizedBox(width: cw, child: x)]);
        }),
        const Gap(14),
        Flex(direction: narrow ? Axis.vertical : Axis.horizontal, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Flexible(flex: narrow ? 0 : 3, child: Reveal(delay: 200, child: Panel(padding: const EdgeInsets.all(20), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Why conversations reach a person', style: TypeX.display(17, color: c.text)),
            const Gap(2),
            Text('Share of handoffs (sample)', style: TypeX.ui(12.5, color: c.text3)),
            const Gap(18),
            for (final r in reasons) _Bar(label: r[0] as String, pct: (r[1] as num).toInt(), color: c.primary),
          ])))),
          SizedBox(width: narrow ? 0 : 14, height: narrow ? 14 : 0),
          Flexible(flex: narrow ? 0 : 2, child: Reveal(delay: 260, child: Panel(padding: const EdgeInsets.all(20), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('By channel', style: TypeX.display(17, color: c.text)),
            const Gap(2),
            Text('Share of your real conversations', style: TypeX.ui(12.5, color: c.text3)),
            const Gap(18),
            for (final ch in chans) _Bar(label: ch['name'] as String, pct: (ch['pct'] as num).toInt(), kind: ch['kind'] as String, color: c.primary),
          ])))),
        ]),
      ]),
    );
  }
}

class PageHeaderInline extends StatelessWidget {
  const PageHeaderInline({super.key, required this.title, required this.range, required this.onRange});
  final String title, range;
  final ValueChanged<String> onRange;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Wrap(spacing: 16, runSpacing: 10, crossAxisAlignment: WrapCrossAlignment.center, alignment: WrapAlignment.spaceBetween, children: [
      Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        Text(title, style: TypeX.display(28, color: c.text)),
        const SizedBox(height: 4),
        Row(mainAxisSize: MainAxisSize.min, children: [Text('Last 14 days', style: TypeX.ui(13.5, color: c.text3)), const SizedBox(width: 8), const Tag('Sample data', tone: 'warn', small: true)]),
      ]),
      Seg<String>(items: const [('7', '7 days'), ('14', '14 days'), ('30', '30 days')], value: range, onChanged: onRange),
    ]);
  }
}

class _Bar extends StatelessWidget {
  const _Bar({required this.label, required this.pct, required this.color, this.kind});
  final String label;
  final int pct;
  final Color color;
  final String? kind;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [if (kind != null) ...[ChannelIcon(kind: kind!, size: 20), const SizedBox(width: 9)], Expanded(child: Text(label, style: TypeX.ui(13.5, w: FontWeight.w600, color: c.text))), Text('$pct%', style: TypeX.mono(13, w: FontWeight.w700, color: c.text2))]),
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(99),
          child: TweenAnimationBuilder<double>(
            tween: Tween(end: pct / 100), duration: const Duration(milliseconds: 900), curve: Curves.easeOutCubic,
            builder: (_, v, __) => Container(height: 9, color: c.sunken, alignment: Alignment.centerLeft, child: FractionallySizedBox(widthFactor: v.clamp(0.0, 1.0), child: Container(decoration: BoxDecoration(gradient: c.brand)))),
          ),
        ),
      ]),
    );
  }
}

/// Smooth area sparkline drawn on the hero card.
class _Spark extends StatelessWidget {
  const _Spark({required this.values});
  final List<num> values;
  @override
  Widget build(BuildContext context) => TweenAnimationBuilder<double>(
        tween: Tween(begin: 0, end: 1), duration: const Duration(milliseconds: 1300), curve: Curves.easeOutCubic,
        builder: (_, t, __) => CustomPaint(painter: _SparkPainter(values.map((e) => e.toDouble()).toList(), t), size: Size.infinite),
      );
}

class _SparkPainter extends CustomPainter {
  _SparkPainter(this.v, this.t);
  final List<double> v;
  final double t;
  @override
  void paint(Canvas canvas, Size s) {
    if (v.length < 2) return;
    final lo = v.reduce(math.min) - 6, hi = v.reduce(math.max) + 4;
    Offset pt(int i) => Offset(s.width * i / (v.length - 1), s.height - 10 - (s.height - 24) * (v[i] - lo) / (hi - lo));
    final path = Path()..moveTo(pt(0).dx, pt(0).dy);
    for (var i = 1; i < v.length; i++) {
      final a = pt(i - 1), b = pt(i), mx = (a.dx + b.dx) / 2;
      path.cubicTo(mx, a.dy, mx, b.dy, b.dx, b.dy);
    }
    canvas.save();
    canvas.clipRect(Rect.fromLTWH(0, 0, s.width * t, s.height));
    final area = Path.from(path)..lineTo(s.width, s.height)..lineTo(0, s.height)..close();
    canvas.drawPath(area, Paint()..shader = LinearGradient(colors: [Colors.white.withValues(alpha: .28), Colors.white.withValues(alpha: 0)], begin: Alignment.topCenter, end: Alignment.bottomCenter).createShader(Offset.zero & s));
    canvas.drawPath(path, Paint()..color = Colors.white..style = PaintingStyle.stroke..strokeWidth = 3..strokeCap = StrokeCap.round..strokeJoin = StrokeJoin.round);
    canvas.restore();
    if (t > .98) {
      final e = pt(v.length - 1);
      canvas.drawCircle(e, 9, Paint()..color = Colors.white.withValues(alpha: .25));
      canvas.drawCircle(e, 5.5, Paint()..color = Colors.white);
      canvas.drawCircle(e, 3, Paint()..color = const Color(0xFF4A37E8));
    }
  }

  @override
  bool shouldRepaint(covariant _SparkPainter old) => old.t != t || old.v != v;
}
