import 'package:flutter/material.dart';
import '../brand/theme.dart';
import 'kit.dart';

/// Title, subtitle and actions at the top of a screen.
class PageHeader extends StatelessWidget {
  const PageHeader({super.key, required this.title, this.subtitle, this.actions = const [], this.pad = 24});
  final String title;
  final Widget? subtitle;
  final List<Widget> actions;
  final double pad;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return LayoutBuilder(builder: (context, box) {
      // Judge by the room this header really has (a list beside a detail pane is narrow on a wide screen), not by the window.
      final narrow = box.maxWidth < 640;
      final head = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: TypeX.display(narrow ? 24 : 28, color: c.text)),
        if (subtitle != null) ...[const SizedBox(height: 5), subtitle!],
      ]);
      return Padding(
        padding: EdgeInsets.fromLTRB(pad, pad - 2, pad, 14),
        child: narrow || actions.isEmpty
            ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [head, if (actions.isNotEmpty) ...[const Gap(12), Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: actions)]])
            : Row(crossAxisAlignment: CrossAxisAlignment.end, children: [Expanded(child: head), const SizedBox(width: 16), ...actions.expand((a) => [a, const SizedBox(width: 8)]).toList()..removeLast()]),
      );
    });
  }
}

class UnderTabs extends StatelessWidget {
  const UnderTabs({super.key, required this.tabs, required this.value, required this.onChanged, this.pad = 24});
  final List<(String, String, int?)> tabs; // value, label, count
  final String value;
  final ValueChanged<String> onChanged;
  final double pad;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      padding: EdgeInsets.symmetric(horizontal: pad),
      decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.line))),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(children: [
          for (final (v, label, n) in tabs)
            Hover(
              onTap: () => onChanged(v),
              builder: (_, h, __) {
                final on = v == value;
                return Container(
                  margin: const EdgeInsets.only(right: 22), padding: const EdgeInsets.only(top: 10, bottom: 11),
                  decoration: BoxDecoration(border: Border(bottom: BorderSide(color: on ? c.primary : Colors.transparent, width: 2.5))),
                  child: Row(children: [
                    Text(label, style: TypeX.ui(13.5, w: FontWeight.w700, color: on ? c.text : (h ? c.text2 : c.text3))),
                    if (n != null) ...[
                      const SizedBox(width: 6),
                      Container(padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1), decoration: BoxDecoration(color: on ? c.primarySoft : c.sunken, borderRadius: BorderRadius.circular(8)), child: Text('$n', style: TypeX.ui(11, w: FontWeight.w800, color: on ? c.primary : c.text3))),
                    ],
                  ]),
                );
              },
            ),
        ]),
      ),
    );
  }
}

/// True when the screen below is showing one pane at a time (so a detail needs its own back button).
class SinglePane extends InheritedWidget {
  const SinglePane({super.key, required this.single, required super.child});
  final bool single;
  static bool of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<SinglePane>()?.single ?? false;
  @override
  bool updateShouldNotify(SinglePane old) => old.single != single;
}

/// Two panes on wide screens (list + detail); on phones the detail replaces the list.
class MasterDetail extends StatelessWidget {
  const MasterDetail({super.key, required this.master, required this.detail, required this.hasSelection, required this.onBack, this.masterFlex = 1, this.detailWidth = 420});
  final Widget master, detail;
  final bool hasSelection;
  final VoidCallback onBack;
  final int masterFlex;
  final double detailWidth;
  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, box) {
      if (box.maxWidth >= 980) {
        return SinglePane(single: false, child: Row(children: [Expanded(flex: masterFlex, child: master), const SizedBox(width: 12), SizedBox(width: detailWidth, child: detail)]));
      }
      return SinglePane(single: true, child: AnimatedSwitcher(duration: const Duration(milliseconds: 200), child: hasSelection ? KeyedSubtree(key: const ValueKey('d'), child: detail) : KeyedSubtree(key: const ValueKey('m'), child: master)));
    });
  }
}

class DetailSection extends StatelessWidget {
  const DetailSection(this.title, {super.key, required this.child});
  final String title;
  final Widget child;
  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Label(title), const SizedBox(height: 10), child]);
}

/// A compact figure with a small icon: the "at a glance" strip at the top of Orders and Approvals.
class StatTile extends StatelessWidget {
  const StatTile({super.key, required this.value, required this.label, required this.icon, this.tone = '', this.onTap, this.active = false});
  final String value, label, tone;
  final IconData icon;
  final VoidCallback? onTap;
  final bool active;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final (bg, fg) = switch (tone) {
      'ok' => (c.okSoft, c.ok),
      'warn' => (c.warnSoft, c.warn),
      'danger' => (c.dangerSoft, c.danger),
      _ => (c.primarySoft, c.primary),
    };
    return Expanded(
      child: Hover(
        onTap: onTap,
        builder: (_, h, __) => AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          padding: const EdgeInsets.fromLTRB(12, 11, 10, 11),
          decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(14), border: Border.all(color: active ? fg : (h && onTap != null ? c.line2 : c.line), width: active ? 1.4 : 1)),
          child: Row(children: [
            Container(width: 32, height: 32, decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(10)), child: Icon(icon, size: 16, color: fg)),
            const SizedBox(width: 10),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              FittedBox(fit: BoxFit.scaleDown, alignment: Alignment.centerLeft, child: Text(value, style: TypeX.display(18, color: c.text, ls: -.01))),
              Text(label, style: TypeX.ui(11, w: FontWeight.w600, color: c.text3), maxLines: 1, overflow: TextOverflow.ellipsis),
            ])),
          ]),
        ),
      ),
    );
  }
}

/// A bordered card with a small uppercase title; used for the sections of a detail pane.
class SectionCard extends StatelessWidget {
  const SectionCard(this.title, {super.key, required this.child, this.icon, this.trailing, this.margin = const EdgeInsets.only(bottom: 12)});
  final String title;
  final Widget child;
  final IconData? icon;
  final Widget? trailing;
  final EdgeInsets margin;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      margin: margin,
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
      decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(16), border: Border.all(color: c.line)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          if (icon != null) ...[Icon(icon, size: 14, color: c.text3), const SizedBox(width: 7)],
          Expanded(child: Text(title.toUpperCase(), style: TypeX.ui(10.5, w: FontWeight.w800, color: c.text3, ls: .9))),
          if (trailing != null) trailing!,
        ]),
        const SizedBox(height: 10),
        child,
      ]),
    );
  }
}

/// "What to do next": a one-line instruction with a coloured edge, so staff never have to guess the next step.
class NextStep extends StatelessWidget {
  const NextStep({super.key, required this.title, required this.body, required this.icon, this.tone = 'accent'});
  final String title, body, tone;
  final IconData icon;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final (bg, fg) = switch (tone) {
      'ok' => (c.okSoft, c.ok),
      'warn' => (c.warnSoft, c.warn),
      'danger' => (c.dangerSoft, c.danger),
      _ => (c.primarySoft, c.primary),
    };
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(16), border: Border.all(color: fg.withValues(alpha: .28))),
      child: Row(children: [
        Container(width: 4, height: 62, decoration: BoxDecoration(color: fg, borderRadius: const BorderRadius.horizontal(left: Radius.circular(16)))),
        Padding(padding: const EdgeInsets.symmetric(horizontal: 12), child: Icon(icon, size: 20, color: fg)),
        Expanded(child: Padding(padding: const EdgeInsets.symmetric(vertical: 12), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: TypeX.ui(13.5, w: FontWeight.w800, color: c.text)),
          const SizedBox(height: 2),
          Text(body, style: TypeX.ui(12.5, color: c.text2, h: 1.4)),
        ]))),
        const SizedBox(width: 14),
      ]),
    );
  }
}
