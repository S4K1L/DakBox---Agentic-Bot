import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../brand/icons.dart';
import 'package:provider/provider.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';
import '../widgets/page.dart' show SinglePane;
import 'new_order.dart';

bool hasBangla(String s) => RegExp(r'[ঀ-৿]').hasMatch(s);
TextStyle bubbleStyle(String text, Color color, {double size = 14.5}) => hasBangla(text) ? TypeX.bn(size, color: color) : TypeX.ui(size, color: color, h: 1.45);
String langLabel(String l) => l == 'bn' ? 'বাংলা' : (l == 'bl' ? 'Banglish' : 'English');

class InboxScreen extends StatefulWidget {
  const InboxScreen({super.key});
  @override
  State<InboxScreen> createState() => _InboxScreenState();
}

class _InboxScreenState extends State<InboxScreen> {
  bool details = false;
  bool showTr = true;

  @override
  void initState() {
    super.initState();
    // Open the first conversation that needs attention on first load.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final s = context.read<AppState>();
      if (s.convId == null && s.convs.isNotEmpty && MediaQuery.of(context).size.width >= 900) {
        final first = s.convs.firstWhere((c) => c['hasPending'] == true, orElse: () => s.convs.first);
        s.selectConversation(first['id'] as String, openThread: false);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    return LayoutBuilder(builder: (context, box) {
      final w = box.maxWidth;
      final list = _ConversationList(onPick: (id) => s.selectConversation(id));
      final thread = _Thread(showTr: showTr, onToggleTr: () => setState(() => showTr = !showTr), details: details, onToggleDetails: () => setState(() => details = !details));
      if (w >= 1320) {
        return SinglePane(single: false, child: Row(children: [
          SizedBox(width: 372, child: list),
          const SizedBox(width: 12),
          Expanded(child: thread),
          const SizedBox(width: 12),
          SizedBox(width: 332, child: _ContextPanel(conv: s.conv)),
        ]));
      }
      if (w >= 900) {
        return SinglePane(single: false, child: Row(children: [
          SizedBox(width: 352, child: list),
          const SizedBox(width: 12),
          Expanded(
            child: Stack(children: [
              Positioned.fill(child: thread),
              if (details) Positioned(top: 0, bottom: 0, right: 0, width: 332, child: Reveal(dy: 0, child: _ContextPanel(conv: s.conv, onClose: () => setState(() => details = false)))),
            ]),
          ),
        ]));
      }
      // phone: one pane at a time
      return SinglePane(single: true, child: AnimatedSwitcher(
        duration: const Duration(milliseconds: 220),
        child: s.showMobileThread && s.convId != null
            ? Stack(key: const ValueKey('t'), children: [
                Positioned.fill(child: thread),
                if (details) Positioned.fill(child: Container(color: Colors.black.withValues(alpha: .35), child: Align(alignment: Alignment.centerRight, child: SizedBox(width: w * .92, child: _ContextPanel(conv: s.conv, onClose: () => setState(() => details = false)))))),
              ])
            : KeyedSubtree(key: const ValueKey('l'), child: list),
      ));
    });
  }
}

// ====================================================================== LIST
class _ConversationList extends StatelessWidget {
  const _ConversationList({required this.onPick});
  final ValueChanged<String> onPick;

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final rows = s.visibleConvs;
    int count(String k) => s.convs.where((x) => x['channel']['kind'] == k && x['status'] != 'resolved').length;
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
          child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Inbox', style: TypeX.display(26, color: c.text)),
                const SizedBox(height: 3),
                Text('${s.convs.where((x) => x['status'] != 'resolved').length} open · ${s.needsCount} need you', style: TypeX.ui(13, color: c.text3)),
              ]),
            ),
            if (s.can('simulate')) DkIconButton(PhosphorIconsRegular.plus, tooltip: 'Simulate a customer message', onPressed: () => showSimulator(context)),
          ]),
        ),
        const Gap(14),
        SizedBox(
          height: 36,
          child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 20), children: [
            _ChanChip(label: 'All', kind: null, n: s.convs.where((x) => x['status'] != 'resolved').length, on: s.channelFilter == 'all', onTap: () => s.setChannelFilter('all')),
            for (final k in ['wa', 'ms', 'ig', 'web']) _ChanChip(label: channelName(k), kind: k, n: count(k), on: s.channelFilter == k, onTap: () => s.setChannelFilter(k)),
          ]),
        ),
        const Gap(14),
        Padding(padding: const EdgeInsets.symmetric(horizontal: 20), child: SearchBox(hint: 'Search customers or messages', onChanged: s.setQuery)),
        const Gap(6),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20),
          child: Row(children: [
            _Tab('All', s.convs.length, s.convTab == 'all', () => s.setConvTab('all')),
            _Tab('Needs you', s.needsCount, s.convTab == 'needs', () => s.setConvTab('needs'), hot: s.needsCount > 0),
            _Tab('Assistant', s.assistantCount, s.convTab == 'assistant', () => s.setConvTab('assistant')),
          ]),
        ),
        const Rule(),
        Expanded(
          child: rows.isEmpty
              ? const Empty('Nothing here', body: 'No conversations match this view.', icon: PhosphorIconsDuotone.chatsCircle)
              : ListView.builder(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  itemCount: rows.length,
                  itemBuilder: (_, i) => _Row(conv: rows[i], selected: rows[i]['id'] == s.convId, onTap: () => onPick(rows[i]['id'] as String), index: i),
                ),
        ),
      ]),
    );
  }
}

class _ChanChip extends StatelessWidget {
  const _ChanChip({required this.label, required this.kind, required this.n, required this.on, required this.onTap});
  final String label;
  final String? kind;
  final int n;
  final bool on;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Hover(
      onTap: onTap,
      pressScale: .96,
      builder: (_, h, __) => AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        margin: const EdgeInsets.only(right: 8),
        padding: EdgeInsets.fromLTRB(kind == null ? 12 : 7, 0, 11, 0),
        decoration: BoxDecoration(color: on ? c.primary : (h ? c.sunken : c.surface), borderRadius: BorderRadius.circular(99), border: Border.all(color: on ? c.primary : c.line)),
        child: Row(children: [
          if (kind != null) ...[ChannelIcon(kind: kind!, size: 22, circle: true), const SizedBox(width: 7)],
          Text(label, style: TypeX.ui(12.5, w: FontWeight.w700, color: on ? Colors.white : c.text2)),
          const SizedBox(width: 7),
          Text('$n', style: TypeX.ui(12, w: FontWeight.w700, color: on ? Colors.white70 : c.text3)),
        ]),
      ),
    );
  }
}

class _Tab extends StatelessWidget {
  const _Tab(this.label, this.n, this.on, this.onTap, {this.hot = false});
  final String label;
  final int n;
  final bool on, hot;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Hover(
      onTap: onTap,
      builder: (_, h, __) => Container(
        margin: const EdgeInsets.only(right: 20),
        padding: const EdgeInsets.only(top: 10, bottom: 11),
        decoration: BoxDecoration(border: Border(bottom: BorderSide(color: on ? c.primary : Colors.transparent, width: 2.5))),
        child: Row(children: [
          Text(label, style: TypeX.ui(13.5, w: FontWeight.w700, color: on ? c.text : (h ? c.text2 : c.text3))),
          const SizedBox(width: 6),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
            decoration: BoxDecoration(color: hot && !on ? c.warnSoft : (on ? c.primarySoft : c.sunken), borderRadius: BorderRadius.circular(8)),
            child: Text('$n', style: TypeX.ui(11, w: FontWeight.w800, color: hot && !on ? c.warn : (on ? c.primary : c.text3))),
          ),
        ]),
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.conv, required this.selected, required this.onTap, required this.index});
  final J conv;
  final bool selected;
  final VoidCallback onTap;
  final int index;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final cust = conv['customer'] as J;
    final unread = (conv['unread'] as int) > 0;
    final preview = conv['preview'] as String;
    final (tagText, tone, icon) = _status(conv);
    return Hover(
      onTap: onTap,
      builder: (_, h, __) => AnimatedContainer(
        duration: const Duration(milliseconds: 140),
        margin: const EdgeInsets.symmetric(horizontal: 10, vertical: 1.5),
        padding: const EdgeInsets.fromLTRB(10, 12, 12, 12),
        decoration: BoxDecoration(color: selected ? c.primarySoft : (h ? c.surface2 : c.surface2.withValues(alpha: 0)), borderRadius: BorderRadius.circular(14), border: Border.all(color: selected ? c.primaryLine : c.primaryLine.withValues(alpha: 0))),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Avatar(name: cust['name'] as String, hue: cust['hue'] as num, size: 44, channel: conv['channel']['kind'] as String),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(child: Text(cust['name'] as String, maxLines: 1, overflow: TextOverflow.ellipsis, style: TypeX.ui(14.5, w: unread ? FontWeight.w800 : FontWeight.w700, color: c.text))),
                Text(listTime(conv['lastMessageAt'] as String?), style: TypeX.ui(11.5, w: FontWeight.w600, color: unread ? c.primary : c.text3)),
              ]),
              const SizedBox(height: 2),
              Text(preview.isEmpty ? '—' : preview, maxLines: 1, overflow: TextOverflow.ellipsis, style: (hasBangla(preview) ? TypeX.bn(13.5, w: unread ? FontWeight.w600 : FontWeight.w500, color: unread ? c.text : c.text2) : TypeX.ui(13.5, w: unread ? FontWeight.w600 : FontWeight.w500, color: unread ? c.text : c.text2)).copyWith(height: hasBangla(preview) ? 1.55 : 1.4)),
              const SizedBox(height: 7),
              Row(children: [
                Tag(tagText, tone: tone, icon: icon, small: true),
                const Spacer(),
                if (unread) Container(constraints: const BoxConstraints(minWidth: 20), height: 20, padding: const EdgeInsets.symmetric(horizontal: 6), alignment: Alignment.center, decoration: BoxDecoration(color: c.primary, borderRadius: BorderRadius.circular(10)), child: Text('${conv['unread']}', style: TypeX.ui(11, w: FontWeight.w800, color: Colors.white))),
              ]),
            ]),
          ),
        ]),
      ),
    );
  }

  (String, String, IconData?) _status(J c) {
    if (c['status'] == 'resolved') return ('Resolved', 'ok', PhosphorIconsBold.check);
    if (c['handoffReason'] != null && c['window']['open'] == false) return ('Window closed', 'danger', PhosphorIconsBold.clock);
    if (c['hasPending'] == true) return ('Draft to approve', 'warn', PhosphorIconsFill.sparkle);
    if (c['mode'] == 'human') return ('With you', 'accent', PhosphorIconsBold.user);
    if (c['mode'] == 'hybrid') return ('Review mode', 'warn', null);
    return ('Assistant', 'ai', PhosphorIconsFill.sparkle);
  }
}

// ====================================================================== THREAD
class _Thread extends StatefulWidget {
  const _Thread({required this.showTr, required this.onToggleTr, required this.details, required this.onToggleDetails});
  final bool showTr, details;
  final VoidCallback onToggleTr, onToggleDetails;
  @override
  State<_Thread> createState() => _ThreadState();
}

class _ThreadState extends State<_Thread> {
  final _scroll = ScrollController();
  String? _lastId;
  int _lastCount = 0;

  @override
  void dispose() { _scroll.dispose(); super.dispose(); }

  void _maybeScroll(String id, int count) {
    if (_lastId != id || _lastCount != count) {
      final jump = _lastId != id;
      _lastId = id;
      _lastCount = count;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!_scroll.hasClients) return;
        final to = _scroll.position.maxScrollExtent;
        if (jump) { _scroll.jumpTo(to); } else { _scroll.animateTo(to, duration: const Duration(milliseconds: 280), curve: Curves.easeOutCubic); }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final conv = s.conv;
    if (s.convId == null) {
      return const Panel(child: Empty('Pick a conversation', body: 'Messages from WhatsApp, Messenger, Instagram and your website all land here.', icon: PhosphorIconsDuotone.chatsCircle));
    }
    if (conv == null) return Panel(child: Center(child: SizedBox(width: 26, height: 26, child: CircularProgressIndicator(strokeWidth: 3, color: c.primary))));

    final msgs = (conv['messages'] as List).cast<J>();
    final pending = conv['pending'] as J?;
    final real = msgs.where((m) => m['role'] != 'event').toList();
    final typing = real.isNotEmpty && real.last['role'] == 'customer' && conv['mode'] != 'human' && conv['status'] != 'resolved' && pending == null;
    _maybeScroll(conv['id'] as String, msgs.length + (pending != null ? 1 : 0) + (typing ? 1 : 0));

    final items = <(Widget, double)>[];
    String? lastDay;
    final cust = (conv['customer'] as J);
    DateTime? at(J m) => DateTime.tryParse((m['at'] ?? '') as String);
    bool sameGroup(J a, J? b) {
      if (b == null || a['role'] == 'event' || b['role'] == 'event' || a['role'] != b['role'] || a['author'] != b['author']) return false;
      final x = at(a), y = at(b);
      return x != null && y != null && x.difference(y).abs().inMinutes < 5 && dayLabel(a['at'] as String?) == dayLabel(b['at'] as String?);
    }
    for (var i = 0; i < msgs.length; i++) {
      final m = msgs[i];
      final day = dayLabel(m['at'] as String?);
      if (day != lastDay) {
        items.add((_DaySep(day), 14));
        lastDay = day;
      }
      if (m['role'] == 'event') {
        items.add((_EventChip(m: m), 10));
        continue;
      }
      final prev = i > 0 ? msgs[i - 1] : null;
      final next = i + 1 < msgs.length ? msgs[i + 1] : null;
      final first = !sameGroup(m, prev);
      final last = next == null || !sameGroup(next, m);
      items.add((_Bubble(m: m, customer: cust, first: first, last: last, showTr: widget.showTr), last ? 16 : 3));
    }
    if (pending != null) items.add((_DraftCard(key: ValueKey('draft-${conv['id']}-${pending['createdAt']}'), pending: pending, showTr: widget.showTr), 12));
    if (typing) items.add((const _Typing(), 12));

    return Panel(
      color: c.surface2,
      child: Column(children: [
        _ThreadHeader(conv: conv, showTr: widget.showTr, onToggleTr: widget.onToggleTr, details: widget.details, onToggleDetails: widget.onToggleDetails),
        if (conv['handoffReason'] != null && conv['status'] != 'resolved') _HandoffBanner(conv: conv),
        Expanded(
          child: Scrollbar(
            controller: _scroll,
            child: ListView.builder(
              controller: _scroll,
              padding: const EdgeInsets.fromLTRB(24, 20, 24, 12),
              itemCount: items.length,
              itemBuilder: (_, i) => Padding(padding: EdgeInsets.only(bottom: items[i].$2), child: Align(alignment: Alignment.topCenter, child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 780), child: items[i].$1))),
            ),
          ),
        ),
        _Composer(conv: conv),
      ]),
    );
  }
}

class _ThreadHeader extends StatelessWidget {
  const _ThreadHeader({required this.conv, required this.showTr, required this.onToggleTr, required this.details, required this.onToggleDetails});
  final J conv;
  final bool showTr, details;
  final VoidCallback onToggleTr, onToggleDetails;
  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    final cust = conv['customer'] as J;
    final ch = conv['channel'] as J;
    final win = conv['window'] as J;
    final phone = SinglePane.of(context);
    final resolved = conv['status'] == 'resolved';
    final canReply = s.can('conv.reply');
    final winOpen = win['open'] == true;
    final showWin = ch['kind'] != 'web';
    Widget dot() => Padding(padding: const EdgeInsets.symmetric(horizontal: 8), child: Container(width: 3, height: 3, decoration: BoxDecoration(color: c.text3.withValues(alpha: .6), shape: BoxShape.circle)));
    return Container(
      height: 68,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: BoxDecoration(color: c.surface, border: Border(bottom: BorderSide(color: c.line))),
      child: Row(children: [
        if (phone) ...[DkIconButton(PhosphorIconsBold.arrowLeft, onPressed: s.closeThread), const SizedBox(width: 4)],
        Avatar(name: cust['name'] as String, hue: cust['hue'] as num, size: 40),
        const SizedBox(width: 12),
        Expanded(
          child: LayoutBuilder(builder: (context, box) {
            final w = box.maxWidth;
            return Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Flexible(child: Text(cust['name'] as String, maxLines: 1, overflow: TextOverflow.ellipsis, style: TypeX.display(16, color: c.text, ls: -.01))),
                if (showWin && w > 250) ...[
                  const SizedBox(width: 10),
                  Container(width: 6, height: 6, decoration: BoxDecoration(color: winOpen ? c.ok : c.danger, shape: BoxShape.circle)),
                  const SizedBox(width: 5),
                  Text(winOpen ? windowLeft(win['expiresAt'] as String?) : 'Window closed', maxLines: 1, style: TypeX.ui(12, w: FontWeight.w600, color: winOpen ? c.ok : c.danger)),
                ],
              ]),
              const SizedBox(height: 2),
              Row(children: [
                ChannelIcon(kind: ch['kind'] as String, size: 14),
                const SizedBox(width: 6),
                Flexible(child: Text('${channelName(ch['kind'] as String)} · ${ch['handle']}', maxLines: 1, overflow: TextOverflow.ellipsis, style: TypeX.ui(12.5, color: c.text3))),
                if (!phone && w > 330) ...[dot(), Text(langLabel(cust['lang'] as String), maxLines: 1, style: TypeX.ui(12.5, color: c.text3))],
              ]),
            ]);
          }),
        ),
        const SizedBox(width: 12),
        if (!phone) ...[
          IgnorePointer(ignoring: !canReply, child: Opacity(opacity: canReply ? 1 : .5, child: Seg<String>(items: const [('agent', 'Assistant'), ('hybrid', 'Review'), ('human', 'Me')], value: conv['mode'] as String, onChanged: s.setMode, small: true))),
          const SizedBox(width: 12),
          DkButton(resolved ? 'Reopen' : 'Resolve', icon: resolved ? PhosphorIconsRegular.arrowCounterClockwise : PhosphorIconsBold.check, small: true, onPressed: canReply ? () => s.resolve(resolved) : null),
          Padding(padding: const EdgeInsets.symmetric(horizontal: 10), child: Container(width: 1, height: 24, color: c.line)),
        ],
        if (cust['lang'] != 'en') DkIconButton(PhosphorIconsRegular.translate, tooltip: 'Show English translation', active: showTr, size: 36, onPressed: onToggleTr),
        DkIconButton(PhosphorIconsRegular.sidebarSimple, tooltip: 'Customer details', active: details, size: 36, onPressed: onToggleDetails),
        if (phone) DkIconButton(PhosphorIconsRegular.dotsThreeVertical, size: 36, onPressed: () => _sheet(context, conv)),
      ]),
    );
  }

  void _sheet(BuildContext context, J conv) {
    final s = context.read<AppState>();
    final c = context.c;
    showModalBottomSheet<void>(
      context: context, backgroundColor: c.surface, showDragHandle: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Label('Who replies'),
            const Gap(10),
            Seg<String>(items: const [('agent', 'Assistant'), ('hybrid', 'Review'), ('human', 'Me')], value: conv['mode'] as String, onChanged: (m) { Navigator.pop(ctx); s.setMode(m); }),
            const Gap(18),
            DkButton(conv['status'] == 'resolved' ? 'Reopen' : 'Resolve conversation', icon: PhosphorIconsBold.check, expand: true, onPressed: () { Navigator.pop(ctx); s.resolve(conv['status'] == 'resolved'); }),
          ]),
        ),
      ),
    );
  }
}

class _HandoffBanner extends StatelessWidget {
  const _HandoffBanner({required this.conv});
  final J conv;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    return Container(
      margin: const EdgeInsets.fromLTRB(20, 14, 20, 0),
      padding: const EdgeInsets.fromLTRB(14, 12, 12, 12),
      decoration: BoxDecoration(color: c.warnSoft, borderRadius: BorderRadius.circular(14), border: Border.all(color: c.warn.withValues(alpha: .25))),
      child: Row(children: [
        Icon(PhosphorIconsFill.warningCircle, color: c.warn, size: 20),
        const SizedBox(width: 10),
        Expanded(child: Text.rich(TextSpan(children: [
          TextSpan(text: 'Handed to a person. ', style: TypeX.ui(13.5, w: FontWeight.w800, color: c.text)),
          TextSpan(text: '${(conv['customer']['name'] as String).split(' ').first}: ${conv['handoffReason']}.', style: TypeX.ui(13.5, color: c.text2)),
        ]))),
        if ((conv['handoffReason'] as String).contains('request') || (conv['handoffReason'] as String).contains('refund'))
          DkButton('Open approvals', small: true, onPressed: () => s.setSection(Section.approvals)),
      ]),
    );
  }
}

class _DaySep extends StatelessWidget {
  const _DaySep(this.text);
  final String text;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Row(children: [
      Expanded(child: Container(height: 1, color: c.line)),
      Padding(padding: const EdgeInsets.symmetric(horizontal: 14), child: Text(text.toUpperCase(), style: TypeX.ui(10.5, w: FontWeight.w800, color: c.text3, ls: .08))),
      Expanded(child: Container(height: 1, color: c.line)),
    ]);
  }
}

class _EventChip extends StatefulWidget {
  const _EventChip({required this.m});
  final J m;
  @override
  State<_EventChip> createState() => _EventChipState();
}

class _EventChipState extends State<_EventChip> {
  bool open = false;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final ev = widget.m['event'] as J;
    final tone = ev['tone'] as String?;
    final (bg, fg, bd) = switch (tone) {
      'warn' => (c.warnSoft, c.warn, c.warn.withValues(alpha: .3)),
      'ok' => (c.okSoft, c.ok, c.ok.withValues(alpha: .28)),
      _ => (c.surface, c.text2, c.line),
    };
    final detail = ev['detail'] as String?;
    return Center(
      child: Hover(
        onTap: detail == null ? null : () => setState(() => open = !open),
        builder: (_, h, __) => Column(mainAxisSize: MainAxisSize.min, children: [
          AnimatedContainer(
            duration: const Duration(milliseconds: 140),
            padding: const EdgeInsets.fromLTRB(9, 5, 12, 5),
            decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(99), border: Border.all(color: h ? fg.withValues(alpha: .5) : bd)),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Container(width: 20, height: 20, decoration: BoxDecoration(color: tone == null ? c.sunken : Colors.transparent, shape: BoxShape.circle), child: Icon(iconFor(ev['icon'] as String?), size: 13, color: tone == null ? c.primary : fg)),
              const SizedBox(width: 7),
              Flexible(child: Text(widget.m['text'] as String, style: TypeX.ui(12.5, w: FontWeight.w600, color: fg), maxLines: 2)),
              if (detail != null) ...[const SizedBox(width: 6), Icon(open ? PhosphorIconsBold.caretUp : PhosphorIconsBold.caretDown, size: 11, color: c.text3)],
            ]),
          ),
          AnimatedSize(
            duration: const Duration(milliseconds: 180), curve: Curves.easeOutCubic,
            child: open && detail != null ? Padding(padding: const EdgeInsets.only(top: 6), child: Text(detail, textAlign: TextAlign.center, style: TypeX.mono(11.5, color: c.text3))) : const SizedBox(width: double.infinity),
          ),
        ]),
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.m, required this.customer, required this.first, required this.last, required this.showTr});
  final J m, customer;
  final bool first, last, showTr;

  Widget _mark(BuildContext context, String? d, Color base) {
    final c = context.c;
    if (d == null) return const SizedBox.shrink();
    if (d == 'Delivered' || d == 'Read') return Icon(PhosphorIconsBold.checks, size: 13, color: d == 'Read' ? const Color(0xFF7FE3FF) : base);
    if (d == 'Sent') return Icon(PhosphorIconsBold.check, size: 12, color: base);
    if (d.startsWith('Failed')) return Icon(PhosphorIconsFill.warningCircle, size: 13, color: c.danger);
    return Text(d, style: TypeX.ui(10.5, w: FontWeight.w600, color: base));
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final role = m['role'] as String;
    final inbound = role == 'customer';
    final human = role == 'human';
    final text = m['text'] as String;
    final tr = m['translation'] as String?;
    final product = m['product'] as J?;
    final delivery = m['delivery'] as String?;
    final fg = human ? Colors.white : c.text;
    final sub = human ? Colors.white.withValues(alpha: .72) : c.text3;
    const big = Radius.circular(18), small = Radius.circular(6), tail = Radius.circular(4);
    final radius = inbound
        ? BorderRadius.only(topLeft: first ? big : small, topRight: big, bottomRight: big, bottomLeft: last ? tail : small)
        : BorderRadius.only(topLeft: big, topRight: first ? big : small, bottomLeft: big, bottomRight: last ? tail : small);
    final bg = human ? (c.isDark ? const Color(0xFF4259E0) : c.primary) : (inbound ? c.surface : (c.isDark ? c.primarySoft : const Color(0xFFEFF2FF)));
    final bubble = Container(
      padding: const EdgeInsets.fromLTRB(14, 9, 12, 7),
      decoration: BoxDecoration(
        color: bg, borderRadius: radius,
        border: human ? null : Border.all(color: inbound ? c.line : c.primaryLine.withValues(alpha: .55)),
        boxShadow: human ? [BoxShadow(color: c.primary.withValues(alpha: .22), blurRadius: 14, offset: const Offset(0, 5), spreadRadius: -6)] : (inbound ? c.shadow : null),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        SelectableText(text, style: bubbleStyle(text, fg)),
        if (showTr && tr != null && tr.isNotEmpty) ...[
          const SizedBox(height: 7),
          Container(padding: const EdgeInsets.only(top: 7), decoration: BoxDecoration(border: Border(top: BorderSide(color: human ? Colors.white24 : c.line2))), child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(padding: const EdgeInsets.only(top: 2), child: Icon(PhosphorIconsRegular.translate, size: 12, color: sub)),
            const SizedBox(width: 6),
            Expanded(child: Text(tr, style: TypeX.ui(12.5, color: human ? Colors.white.withValues(alpha: .88) : c.text3, h: 1.4))),
          ])),
        ],
        if (product != null) ...[const SizedBox(height: 10), _ProductCard(p: product)],
        const SizedBox(height: 4),
        Align(alignment: Alignment.centerRight, child: Row(mainAxisSize: MainAxisSize.min, children: [
          Text(clock(m['at'] as String?), style: TypeX.ui(10.5, w: FontWeight.w600, color: sub)),
          if (!inbound && delivery != null) ...[const SizedBox(width: 5), _mark(context, delivery, sub)],
        ])),
      ]),
    );
    final cname = (customer['name'] as String);
    final who = inbound ? cname : (role == 'assistant' ? 'Dakbox Assistant' : '${m['author'] ?? 'You'}');
    final avatar = SizedBox(
      width: 30,
      child: !last ? null : (inbound ? Avatar(name: cname, hue: customer['hue'] as num, size: 30) : (role == 'assistant' ? const AiMark(size: 30) : Avatar(name: '${m['author'] ?? 'You'}', hue: 232, size: 30))),
    );
    final failed = !inbound && delivery != null && delivery.startsWith('Failed');
    return LayoutBuilder(builder: (context, box) {
      final maxW = (box.maxWidth - 40) * (box.maxWidth < 520 ? .92 : .74);
      return Row(
        mainAxisAlignment: inbound ? MainAxisAlignment.start : MainAxisAlignment.end,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (inbound) ...[avatar, const SizedBox(width: 8)],
          Flexible(
            child: ConstrainedBox(
              constraints: BoxConstraints(maxWidth: maxW.clamp(180.0, 600.0)),
              child: Column(crossAxisAlignment: inbound ? CrossAxisAlignment.start : CrossAxisAlignment.end, children: [
                if (first) Padding(padding: const EdgeInsets.fromLTRB(4, 0, 4, 4), child: Row(mainAxisSize: MainAxisSize.min, children: [
                  Text(who, style: TypeX.ui(11.5, w: FontWeight.w800, color: c.text2)),
                  if (human) Padding(padding: const EdgeInsets.only(left: 6), child: Text('Team', style: TypeX.ui(10.5, w: FontWeight.w700, color: c.text3))),
                  if (role == 'assistant') Padding(padding: const EdgeInsets.only(left: 6), child: Text('AI', style: TypeX.ui(10, w: FontWeight.w800, color: c.primary))),
                ])),
                bubble,
                if (failed) Padding(padding: const EdgeInsets.fromLTRB(4, 4, 4, 0), child: Text(delivery, style: TypeX.ui(11.5, color: c.danger))),
              ]),
            ),
          ),
          if (!inbound) ...[const SizedBox(width: 8), avatar],
        ],
      );
    });
  }
}

class _ProductCard extends StatelessWidget {
  const _ProductCard({required this.p});
  final J p;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final stock = p['stock'] as int;
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(14), border: Border.all(color: c.line)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        ProductArt(kind: p['art'] as String?, size: 58, radius: 11),
        const SizedBox(width: 12),
        Flexible(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(p['name'] as String, style: TypeX.ui(14, w: FontWeight.w800, color: c.text)),
            Text((p['variant'] ?? '') as String, style: TypeX.ui(12, color: c.text3)),
            const SizedBox(height: 5),
            Row(children: [
              Text(taka(p['price'] as num), style: TypeX.display(15, color: c.text, ls: 0)),
              const SizedBox(width: 8),
              Tag(stock == 0 ? 'Out of stock' : stock <= 10 ? '$stock left' : '$stock in stock', tone: stock == 0 ? 'danger' : (stock <= 10 ? 'warn' : 'ok'), small: true),
            ]),
          ]),
        ),
        const SizedBox(width: 6),
      ]),
    );
  }
}

class _Typing extends StatelessWidget {
  const _Typing();
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Row(mainAxisAlignment: MainAxisAlignment.end, crossAxisAlignment: CrossAxisAlignment.end, children: [
      Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Container(padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13), decoration: BoxDecoration(color: c.isDark ? c.primarySoft : const Color(0xFFEFF2FF), borderRadius: const BorderRadius.only(topLeft: Radius.circular(18), topRight: Radius.circular(18), bottomLeft: Radius.circular(18), bottomRight: Radius.circular(4)), border: Border.all(color: c.primaryLine.withValues(alpha: .55))), child: const TypingDots()),
        const SizedBox(height: 4),
        Text('Dakbox Assistant is typing…', style: TypeX.ui(11, color: c.text3)),
      ]),
      const SizedBox(width: 8),
      const AiMark(size: 30),
    ]);
  }
}

// ---------------------------------------------------------------- the draft the assistant wants approved
class _DraftCard extends StatefulWidget {
  const _DraftCard({super.key, required this.pending, required this.showTr});
  final J pending;
  final bool showTr;
  @override
  State<_DraftCard> createState() => _DraftCardState();
}

class _DraftCardState extends State<_DraftCard> {
  bool editing = false;
  late final TextEditingController ctl = TextEditingController(text: widget.pending['text'] as String);
  @override
  void dispose() { ctl.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    final p = widget.pending;
    final text = p['text'] as String;
    final diff = (p['cartDiff'] as List).cast<J>();
    final tr = p['translation'] as String?;
    return Reveal(
      child: Align(
        alignment: Alignment.centerRight,
        child: Container(
          constraints: const BoxConstraints(maxWidth: 520),
          decoration: BoxDecoration(
            color: c.surface, borderRadius: BorderRadius.circular(20), boxShadow: c.lift,
            border: Border.all(color: c.primaryLine, width: 1.4),
          ),
          clipBehavior: Clip.antiAlias,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              padding: const EdgeInsets.fromLTRB(14, 11, 14, 11),
              decoration: BoxDecoration(gradient: LinearGradient(colors: [c.primarySoft, c.isDark ? c.surface2 : const Color(0xFFF3EEFF)])),
              child: Row(children: [
                const AiMark(size: 24),
                const SizedBox(width: 10),
                Expanded(child: Text('Assistant suggests this reply', style: TypeX.ui(13, w: FontWeight.w800, color: c.primary))),
                const Tag('Needs your approval', tone: 'warn', small: true),
              ]),
            ),
            Padding(
              padding: const EdgeInsets.all(14),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                if (editing)
                  DkField(controller: ctl, maxLines: 5, bangla: hasBangla(text))
                else
                  Container(
                    padding: const EdgeInsets.only(left: 12), decoration: BoxDecoration(border: Border(left: BorderSide(color: c.primary, width: 3))),
                    child: SelectableText(text, style: bubbleStyle(text, c.text)),
                  ),
                if (!editing && widget.showTr && tr != null) ...[
                  const Gap(8),
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Padding(padding: const EdgeInsets.only(top: 2), child: Icon(PhosphorIconsRegular.translate, size: 13, color: c.text3)), const SizedBox(width: 6), Expanded(child: Text(tr, style: TypeX.ui(12.5, color: c.text3)))]),
                ],
                if (p['orderPreview'] != null) ...[
                  const Gap(12),
                  _OrderPreview(o: (p['orderPreview'] as Map).cast<String, dynamic>()),
                ],
                if (diff.isNotEmpty) ...[
                  const Gap(12),
                  Container(
                    decoration: BoxDecoration(border: Border.all(color: c.line), borderRadius: BorderRadius.circular(12)),
                    clipBehavior: Clip.antiAlias,
                    child: Column(children: [
                      for (final d in diff)
                        Container(
                          color: c.okSoft, padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
                          child: Row(children: [
                            Icon(PhosphorIconsBold.plus, size: 13, color: c.ok), const SizedBox(width: 8),
                            Expanded(child: Text('${d['name']}${d['variant'] != null ? ' · ${d['variant']}' : ''} · Qty ${d['qty']}', style: TypeX.ui(12.5, w: FontWeight.w700, color: c.ok))),
                            Text(taka((d['price'] as num) * (d['qty'] as num)), style: TypeX.mono(12.5, color: c.ok)),
                          ]),
                        ),
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
                        child: Row(children: [
                          Text('Cart subtotal', style: TypeX.ui(12.5, color: c.text2)), const Spacer(),
                          Text('${taka(0)}  →  ', style: TypeX.mono(12.5, color: c.text3)),
                          Text(taka(diff.fold<num>(0, (a, d) => a + (d['price'] as num) * (d['qty'] as num))), style: TypeX.mono(13, w: FontWeight.w700, color: c.text)),
                        ]),
                      ),
                    ]),
                  ),
                ],
              ]),
            ),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: c.surface2, border: Border(top: BorderSide(color: c.line))),
              child: Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
                DkButton(editing ? 'Send edited reply' : 'Approve and send', icon: PhosphorIconsBold.check, kind: BtnKind.primary, small: true, onPressed: !s.can('draft.approve') ? null : () => s.approveDraft(text: editing ? ctl.text.trim() : null)),
                DkButton(editing ? 'Cancel edit' : 'Edit', small: true, onPressed: () => setState(() { editing = !editing; ctl.text = text; })),
                DkButton('Dismiss', kind: BtnKind.ghost, small: true, onPressed: s.can('draft.approve') ? s.dismissDraft : null),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------- composer
const _canned = [
  ('বাংলা', 'আপনার অর্ডারটি প্রস্তুত হচ্ছে। আজ বা কালকের মধ্যে কুরিয়ারে দেওয়া হবে।'),
  ('Banglish', 'Apnar order ta ready hocche. Ajke ba kal courier e dewa hobe.'),
  ('English', 'Your order is being prepared and will be handed to the courier today or tomorrow.'),
];

class _Composer extends StatefulWidget {
  const _Composer({required this.conv});
  final J conv;
  @override
  State<_Composer> createState() => _ComposerState();
}

class _ComposerState extends State<_Composer> {
  final ctl = TextEditingController();
  late final focus = FocusNode(onKeyEvent: _onKey);
  bool note = false, canned = false, busy = false;

  /// Enter sends, Shift+Enter makes a new line. Never fires while an IME (Bangla keyboard) is still composing a word.
  KeyEventResult _onKey(FocusNode node, KeyEvent ev) {
    if (ev is KeyDownEvent && ev.logicalKey == LogicalKeyboardKey.enter && !HardwareKeyboard.instance.isShiftPressed) {
      final comp = ctl.value.composing;
      if (comp.isValid && !comp.isCollapsed) return KeyEventResult.ignored;
      _send();
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }
  int tplIndex = 0;
  String? _id;

  @override
  void dispose() { ctl.dispose(); focus.dispose(); super.dispose(); }

  Future<void> _send() async {
    final v = ctl.text.trim();
    if (v.isEmpty || busy) return;
    setState(() => busy = true);
    await context.read<AppState>().sendMessage(v, internal: note);
    if (mounted) { ctl.clear(); setState(() => busy = false); focus.requestFocus(); }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    final conv = widget.conv;
    if (_id != conv['id']) { _id = conv['id'] as String; ctl.clear(); note = false; canned = false; }
    final cust = conv['customer'] as J;
    final first = (cust['name'] as String).split(' ').first;
    final lang = cust['lang'] as String;
    final ch = conv['channel'] as J;
    final pad = EdgeInsets.fromLTRB(MediaQuery.of(context).size.width < 700 ? 12 : 24, 6, MediaQuery.of(context).size.width < 700 ? 12 : 24, 18);

    Widget wrap(Widget child) => Padding(padding: pad, child: Center(child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 760), child: child)));

    if (!s.can('conv.reply')) {
      return wrap(const _Strip(icon: PhosphorIconsFill.eye, title: 'View-only access', body: 'Your role can read conversations but not reply. Ask an admin if you need to.', action: SizedBox.shrink()));
    }
    if (conv['status'] == 'resolved') {
      return wrap(_Strip(icon: PhosphorIconsFill.checkCircle, tone: c.ok, title: 'This conversation is resolved', body: 'A new message from the customer will reopen it.', action: DkButton('Reopen', onPressed: () => s.resolve(false))));
    }
    if (conv['mode'] == 'agent') {
      return wrap(_Strip(
        leading: const AiMark(size: 36), title: 'Dakbox Assistant is replying in ${langLabel(lang)}', body: 'Step in at any time. The assistant pauses as soon as you take over.',
        action: DkButton('Take over', icon: PhosphorIconsRegular.userSwitch, kind: BtnKind.primary, onPressed: () => s.setMode('human')),
      ));
    }
    if (conv['window']['open'] == false && ch['kind'] != 'web') {
      return wrap(_TemplateSender(key: ValueKey(conv['id']), conv: conv));
    }

    return wrap(Stack(clipBehavior: Clip.none, children: [
      AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        decoration: BoxDecoration(color: note ? c.warnSoft : c.surface, borderRadius: BorderRadius.circular(18), border: Border.all(color: note ? c.warn.withValues(alpha: .45) : c.line2, width: 1.2), boxShadow: c.lift),
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(10, 8, 10, 0),
            child: Row(children: [
              _CTab('Reply', !note, () => setState(() => note = false)),
              _CTab('Internal note', note, () => setState(() => note = true)),
              const Spacer(),
              if (conv['mode'] == 'hybrid') const Tag('Review mode', tone: 'warn', small: true),
            ]),
          ),
          TextField(
            controller: ctl, focusNode: focus, minLines: 1, maxLines: 6, cursorColor: c.primary, textInputAction: TextInputAction.newline,
            onChanged: (_) => setState(() {}),
            style: hasBangla(ctl.text) ? TypeX.bn(14.5, color: c.text) : TypeX.ui(14.5, color: c.text),
            decoration: InputDecoration(
              hintText: note ? 'Visible to your team only' : 'Reply to $first on ${channelName(ch['kind'] as String)} in ${langLabel(lang)}',
              hintStyle: TypeX.ui(14.5, color: c.text3), border: InputBorder.none, contentPadding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(8, 0, 10, 10),
            child: Row(children: [
              const DkIconButton(PhosphorIconsRegular.paperclip, tooltip: 'Attach file', size: 34),
              DkIconButton(PhosphorIconsRegular.lightning, tooltip: 'Canned replies', size: 34, active: canned, onPressed: () => setState(() => canned = !canned)),
              const DkIconButton(PhosphorIconsRegular.package, tooltip: 'Insert product', size: 34),
              const Spacer(),
              if (MediaQuery.of(context).size.width >= 700) Padding(padding: const EdgeInsets.only(right: 12), child: Text('Enter to send · Shift+Enter for a new line', style: TypeX.ui(11, color: c.text3))),
              Hover(
                onTap: ctl.text.trim().isEmpty || busy ? null : _send,
                pressScale: .94,
                builder: (_, h, __) {
                  final on = ctl.text.trim().isNotEmpty && !busy;
                  return AnimatedContainer(
                    duration: const Duration(milliseconds: 140), width: note ? 96 : 40, height: 40, alignment: Alignment.center,
                    decoration: BoxDecoration(color: on ? (h ? c.primaryHover : c.primary) : c.sunken, borderRadius: BorderRadius.circular(note ? 12 : 20), boxShadow: on ? [BoxShadow(color: c.primary.withValues(alpha: .35), blurRadius: 14, offset: const Offset(0, 5), spreadRadius: -4)] : null),
                    child: note
                        ? Text('Add note', style: TypeX.ui(13, w: FontWeight.w800, color: on ? Colors.white : c.text3))
                        : Icon(PhosphorIconsBold.paperPlaneTilt, size: 18, color: on ? Colors.white : c.text3),
                  );
                },
              ),
            ]),
          ),
        ]),
      ),
      if (canned)
        Positioned(
          left: 8, right: 8, bottom: 112,
          child: Reveal(
            dy: 6,
            child: Panel(
              radius: 16,
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                for (final (l, t) in _canned)
                  Hover(
                    onTap: () => setState(() { ctl.text = t; canned = false; focus.requestFocus(); }),
                    builder: (_, h, __) => Container(
                      color: h ? c.sunken : c.sunken.withValues(alpha: 0), padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
                      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [SizedBox(width: 78, child: Align(alignment: Alignment.centerLeft, child: Tag(l, small: true))), Expanded(child: Text(t, style: bubbleStyle(t, c.text2, size: 13.5)))]),
                    ),
                  ),
              ]),
            ),
          ),
        ),
    ]));
  }
}

/// WhatsApp, 24 hours after the customer's last message: only an approved template can be sent.
class _TemplateSender extends StatefulWidget {
  const _TemplateSender({super.key, required this.conv});
  final J conv;
  @override
  State<_TemplateSender> createState() => _TemplateSenderState();
}

class _TemplateSenderState extends State<_TemplateSender> {
  List<J>? items;
  int sel = 0;
  List<TextEditingController> ctl = [];
  bool busy = false;

  @override
  void initState() {
    super.initState();
    context.read<AppState>().templates().then((t) { if (mounted) setState(() { items = t; _pick(0); }); });
  }

  @override
  void dispose() { for (final c in ctl) { c.dispose(); } super.dispose(); }

  void _pick(int i) {
    for (final c in ctl) { c.dispose(); }
    sel = i;
    final t = items!.isEmpty ? null : items![i];
    final first = (widget.conv['customer']['name'] as String).split(' ').first;
    ctl = [for (var n = 0; n < ((t?['params'] as List?)?.length ?? 0); n++) TextEditingController(text: n == 0 ? first : '')];
  }

  String _preview(J t) {
    var out = t['body'] as String;
    final names = (t['params'] as List).cast<String>();
    for (var i = 0; i < names.length; i++) {
      final v = ctl[i].text.trim();
      out = out.replaceAll(RegExp('\\{\\{\\s*${RegExp.escape(names[i])}\\s*\\}\\}'), v.isEmpty ? '{{${names[i]}}}' : v);
    }
    return out;
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    final list = items;
    return Panel(
      radius: 16,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(padding: const EdgeInsets.all(12), color: c.warnSoft, child: Row(children: [Icon(PhosphorIconsFill.clock, size: 18, color: c.warn), const SizedBox(width: 10), Expanded(child: Text('The 24-hour window is closed. WhatsApp only allows an approved template now. Once the customer replies, you can type freely again.', style: TypeX.ui(12.5, color: c.text2, h: 1.4)))])),
        if (list == null) Padding(padding: const EdgeInsets.all(24), child: Center(child: SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5, color: c.primary))))
        else if (list.isEmpty) Padding(padding: const EdgeInsets.all(16), child: Text('No approved templates were found for this number. Create and submit one in Meta Business Manager; it can take minutes to be approved.', style: TypeX.ui(13, color: c.text2, h: 1.5)))
        else Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Wrap(spacing: 8, runSpacing: 8, children: [for (var i = 0; i < list.length; i++) Hover(onTap: () => setState(() => _pick(i)), builder: (_, h, __) => AnimatedContainer(duration: const Duration(milliseconds: 140), padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7), decoration: BoxDecoration(color: sel == i ? c.primary : (h ? c.sunken : c.surface), borderRadius: BorderRadius.circular(99), border: Border.all(color: sel == i ? c.primary : c.line)), child: Text(list[i]['label'] as String, style: TypeX.ui(12.5, w: FontWeight.w700, color: sel == i ? Colors.white : c.text2)))) ]),
            const Gap(12),
            for (var i = 0; i < ctl.length; i++) Padding(padding: const EdgeInsets.only(bottom: 8), child: DkField(controller: ctl[i], label: ((list[sel]['params'] as List)[i] as String).contains(RegExp(r'^\d+$')) ? 'Value for {{${(list[sel]['params'] as List)[i]}}}' : 'Value for ${(list[sel]['params'] as List)[i]}', bangla: true, onSubmitted: (_) => setState(() {}))),
            ListenableBuilder(listenable: Listenable.merge(ctl), builder: (_, __) => Container(width: double.infinity, padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(12)), child: Text(_preview(list[sel]), style: bubbleStyle(list[sel]['body'] as String, c.text2)))),
            const Gap(12),
            Row(children: [
              Text('${list[sel]['category'] ?? 'UTILITY'} template', style: TypeX.ui(12, color: c.text3)),
              const Spacer(),
              ListenableBuilder(listenable: Listenable.merge(ctl), builder: (_, __) {
                final ready = ctl.every((x) => x.text.trim().isNotEmpty) && !busy && s.can('conv.reply');
                return DkButton(busy ? 'Sending…' : 'Send template', icon: PhosphorIconsBold.paperPlaneTilt, kind: BtnKind.primary, small: true, onPressed: !ready ? null : () async {
                  setState(() => busy = true);
                  await s.sendTemplate(list[sel]['name'] as String, list[sel]['language'] as String, [for (final x in ctl) x.text.trim()]);
                  if (mounted) setState(() => busy = false);
                });
              }),
            ]),
          ]),
        ),
      ]),
    );
  }
}

class _CTab extends StatelessWidget {
  const _CTab(this.label, this.on, this.onTap);
  final String label;
  final bool on;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Hover(
      onTap: onTap,
      builder: (_, h, __) => Container(
        margin: const EdgeInsets.only(right: 4), padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 6),
        decoration: BoxDecoration(color: on ? c.sunken : c.sunken.withValues(alpha: 0), borderRadius: BorderRadius.circular(9)),
        child: Text(label, style: TypeX.ui(12.5, w: FontWeight.w700, color: on ? c.text : c.text3)),
      ),
    );
  }
}

class _Strip extends StatelessWidget {
  const _Strip({this.leading, this.icon, this.tone, required this.title, required this.body, required this.action});
  final Widget? leading;
  final IconData? icon;
  final Color? tone;
  final String title, body;
  final Widget action;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final narrow = MediaQuery.of(context).size.width < 700;
    final text = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: TypeX.ui(14, w: FontWeight.w800, color: c.text)), const SizedBox(height: 2), Text(body, style: TypeX.ui(12.5, color: c.text3))]);
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(18), border: Border.all(color: c.line2), boxShadow: c.shadow),
      child: narrow
          ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Row(children: [leading ?? Icon(icon, color: tone, size: 28), const SizedBox(width: 12), Expanded(child: text)]), const Gap(12), action])
          : Row(children: [leading ?? Icon(icon, color: tone, size: 30), const SizedBox(width: 14), Expanded(child: text), const SizedBox(width: 12), action]),
    );
  }
}

// ====================================================================== CONTEXT
class _ContextPanel extends StatelessWidget {
  const _ContextPanel({required this.conv, this.onClose});
  final J? conv;
  final VoidCallback? onClose;

  static String _tone(String f) => f == 'Delivered' ? 'ok' : (f == 'Unfulfilled' ? 'warn' : (f == 'Returned' ? 'danger' : (f == 'Cancelled' ? '' : 'accent')));

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    if (conv == null) return const Panel(child: Empty('Customer', body: 'Details appear here.', icon: PhosphorIconsDuotone.user));
    final cust = conv!['customer'] as J;
    final ctx = conv!['context'] as J;
    final cart = (conv!['cart'] as List).cast<J>();
    final pending = conv!['pending'] as J?;
    final orders = (ctx['orders'] as List).cast<J>();
    final verified = cust['verified'] as String;
    final phone = cust['phone'] as String?;
    final pendingLines = pending == null ? <J>[] : (pending['cartDiff'] as List).cast<J>();
    final cartTotal = cart.fold<num>(0, (a, l) => a + (l['price'] as num) * (l['qty'] as num)) + pendingLines.fold<num>(0, (a, d) => a + (d['price'] as num) * (d['qty'] as num));

    Widget stat(String v, String l, IconData icon) => Expanded(
          child: Container(
            padding: const EdgeInsets.fromLTRB(12, 11, 10, 11),
            decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(14), border: Border.all(color: c.line)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(icon, size: 15, color: c.primary),
              const SizedBox(height: 7),
              FittedBox(fit: BoxFit.scaleDown, alignment: Alignment.centerLeft, child: Text(v, style: TypeX.display(17, color: c.text, ls: -.01))),
              const SizedBox(height: 1),
              Text(l, style: TypeX.ui(11, w: FontWeight.w600, color: c.text3)),
            ]),
          ),
        );

    return Panel(
      color: c.surface2,
      child: ListView(padding: EdgeInsets.zero, children: [
        // ---- identity
        Container(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 18),
          decoration: BoxDecoration(color: c.surface, border: Border(bottom: BorderSide(color: c.line))),
          child: Column(children: [
            if (onClose != null) Align(alignment: Alignment.centerRight, child: DkIconButton(PhosphorIconsBold.x, onPressed: onClose, size: 32)),
            Avatar(name: cust['name'] as String, hue: cust['hue'] as num, size: 72, channel: conv!['channel']['kind'] as String),
            const Gap(12),
            Text(cust['name'] as String, textAlign: TextAlign.center, style: TypeX.display(20, color: c.text, ls: -.01)),
            const Gap(3),
            Text('${channelName(conv!['channel']['kind'] as String)} · ${conv!['channel']['handle']}', textAlign: TextAlign.center, style: TypeX.ui(12.5, color: c.text3)),
            const Gap(12),
            Wrap(spacing: 6, runSpacing: 6, alignment: WrapAlignment.center, children: [
              verified == 'none' ? const Tag('Not verified', tone: 'warn', icon: PhosphorIconsBold.shieldWarning, small: true) : Tag(verified == 'phone' ? 'Phone verified' : 'OTP verified', tone: 'ok', icon: PhosphorIconsFill.sealCheck, small: true),
              Tag(langLabel(cust['lang'] as String), tone: 'accent', small: true),
              for (final t in (cust['tags'] as List).cast<String>()) Tag(t, small: true),
            ]),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              stat(taka(ctx['ltv'] as num), 'Lifetime value', PhosphorIconsRegular.coins),
              const SizedBox(width: 8),
              stat('${orders.length}${orders.length >= 5 ? '+' : ''}', 'Orders', PhosphorIconsRegular.package),
              const SizedBox(width: 8),
              stat(monthYear(cust['since'] as String?), 'Since', PhosphorIconsRegular.clock),
            ]),
            const Gap(14),

            // ---- assistant summary
            _Card(
              title: 'Summary', icon: PhosphorIconsFill.sparkle, iconColor: const Color(0xFFD98200), trailing: Text('by the assistant', style: TypeX.ui(10.5, w: FontWeight.w700, color: c.text3)),
              tint: c.isDark ? null : const Color(0xFFFFFBEF), border: DK.saffron.withValues(alpha: .32),
              child: Text((conv!['summary'] as String?) ?? 'A summary appears after the first reply.', style: TypeX.ui(13, color: c.text2, h: 1.55)),
            ),

            // ---- contact
            _Card(title: 'Contact', icon: PhosphorIconsRegular.user, child: Column(children: [
              _Line(PhosphorIconsRegular.whatsappLogo, 'Phone', phone ?? 'Not shared yet', mono: phone != null, muted: phone == null, action: phone == null ? null : DkIconButton(PhosphorIconsRegular.copy, tooltip: 'Copy phone', size: 28, onPressed: () { Clipboard.setData(ClipboardData(text: phone)); s.toast('Phone copied'); })),
              _Line(PhosphorIconsRegular.mapPin, 'Area', (cust['area'] ?? '—') as String),
              _Line(PhosphorIconsRegular.translate, 'Writes in', langLabel(cust['lang'] as String)),
              _Line(PhosphorIconsRegular.shieldCheck, 'Identity', verified == 'none' ? 'Not verified yet. The assistant asks for the last 4 digits of the phone before sharing order details.' : (verified == 'phone' ? 'Matched to the phone on file' : 'Confirmed by a one-time code'), last: true),
            ])),

            // ---- cart
            _Card(
              title: 'Cart', icon: PhosphorIconsRegular.shoppingCart,
              trailing: cart.isEmpty && pendingLines.isEmpty ? null : Text(taka(cartTotal), style: TypeX.mono(12.5, w: FontWeight.w700, color: c.text)),
              child: cart.isEmpty && pendingLines.isEmpty
                  ? Text('Nothing in the cart.', style: TypeX.ui(13, color: c.text3))
                  : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      for (final l in cart)
                        Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: Row(children: [
                          Container(width: 26, height: 26, alignment: Alignment.center, decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(8)), child: Text('${l['qty']}', style: TypeX.ui(12, w: FontWeight.w800, color: c.text2))),
                          const SizedBox(width: 10),
                          Expanded(child: Text('${l['name']}${l['variant'] != null ? ' · ${l['variant']}' : ''}', maxLines: 1, overflow: TextOverflow.ellipsis, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
                          Text(taka((l['price'] as num) * (l['qty'] as num)), style: TypeX.mono(12.5, color: c.text)),
                        ])),
                      for (final d in pendingLines)
                        Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: Row(children: [
                          Container(width: 26, height: 26, alignment: Alignment.center, decoration: BoxDecoration(color: c.warnSoft, borderRadius: BorderRadius.circular(8)), child: Text('${d['qty']}', style: TypeX.ui(12, w: FontWeight.w800, color: c.warn))),
                          const SizedBox(width: 10),
                          Expanded(child: Text('${d['name']} · awaiting approval', maxLines: 1, overflow: TextOverflow.ellipsis, style: TypeX.ui(13, w: FontWeight.w600, color: c.warn))),
                          Text(taka((d['price'] as num) * (d['qty'] as num)), style: TypeX.mono(12.5, color: c.warn)),
                        ])),
                      if (cart.isNotEmpty && s.can('orders.manage')) Padding(padding: const EdgeInsets.only(top: 8), child: DkButton('Create order from cart', icon: PhosphorIconsBold.shoppingCartSimple, kind: BtnKind.soft, small: true, expand: true, onPressed: () => showNewOrder(context, conv: conv))),
                    ]),
            ),

            // ---- orders
            _Card(
              title: 'Orders', icon: PhosphorIconsRegular.package, last: true, trailing: orders.isEmpty ? null : Text('${orders.length}', style: TypeX.ui(12, w: FontWeight.w800, color: c.text3)),
              child: orders.isEmpty
                  ? Text('No orders yet.', style: TypeX.ui(13, color: c.text3))
                  : Column(children: [
                      for (var i = 0; i < orders.length; i++)
                        Hover(
                          onTap: () { s.selectOrder(orders[i]['number'] as String); s.setSection(Section.orders); },
                          builder: (_, h, __) => Container(
                            margin: EdgeInsets.only(bottom: i == orders.length - 1 ? 0 : 6), padding: const EdgeInsets.fromLTRB(10, 9, 8, 9),
                            decoration: BoxDecoration(color: h ? c.sunken : c.surface2, borderRadius: BorderRadius.circular(12), border: Border.all(color: h ? c.line2 : c.line)),
                            child: Row(children: [
                              Container(width: 34, height: 34, decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(10), border: Border.all(color: c.line)), child: Icon(orders[i]['fulfillment'] == 'In transit' ? PhosphorIconsRegular.truck : PhosphorIconsRegular.package, size: 17, color: c.text2)),
                              const SizedBox(width: 10),
                              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                Row(children: [Text(orders[i]['number'] as String, style: TypeX.mono(13, w: FontWeight.w800, color: c.text)), if (orders[i]['source'] == 'chat') ...[const SizedBox(width: 6), Icon(PhosphorIconsFill.sparkle, size: 11, color: c.primary)]]),
                                const SizedBox(height: 4),
                                Wrap(spacing: 5, runSpacing: 4, children: [Tag('${orders[i]['fulfillment']}', tone: _tone(orders[i]['fulfillment'] as String), small: true), Tag('${(orders[i]['payment'] as Map)['status']}', tone: (orders[i]['payment'] as Map)['status'] == 'Paid' ? 'ok' : ((orders[i]['payment'] as Map)['status'] == 'Failed' ? 'danger' : 'warn'), small: true)]),
                              ])),
                              Text(taka(orders[i]['total'] as num), style: TypeX.mono(12.5, w: FontWeight.w700, color: c.text)),
                            ]),
                          ),
                        ),
                    ]),
            ),
          ]),
        ),
      ]),
    );
  }
}

/// A bordered card with a small icon title; the building block of the details panel.
class _Card extends StatelessWidget {
  const _Card({required this.title, required this.child, this.icon, this.iconColor, this.trailing, this.tint, this.border, this.last = false});
  final String title;
  final Widget child;
  final IconData? icon;
  final Color? iconColor, tint, border;
  final Widget? trailing;
  final bool last;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      margin: EdgeInsets.only(bottom: last ? 0 : 12),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
      decoration: BoxDecoration(color: tint ?? c.surface, borderRadius: BorderRadius.circular(16), border: Border.all(color: border ?? c.line)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          if (icon != null) ...[Icon(icon, size: 14, color: iconColor ?? c.text3), const SizedBox(width: 7)],
          Expanded(child: Text(title.toUpperCase(), style: TypeX.ui(10.5, w: FontWeight.w800, color: c.text3, ls: .9))),
          if (trailing != null) trailing!,
        ]),
        const SizedBox(height: 10),
        child,
      ]),
    );
  }
}

class _Line extends StatelessWidget {
  const _Line(this.icon, this.label, this.value, {this.mono = false, this.muted = false, this.action, this.last = false});
  final IconData icon;
  final String label, value;
  final bool mono, muted, last;
  final Widget? action;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Padding(
      padding: EdgeInsets.only(bottom: last ? 0 : 10),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(width: 28, height: 28, alignment: Alignment.center, decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(8)), child: Icon(icon, size: 14, color: c.text2)),
        const SizedBox(width: 10),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: TypeX.ui(11, w: FontWeight.w600, color: c.text3)),
          const SizedBox(height: 1),
          Text(value, style: mono ? TypeX.mono(13, w: FontWeight.w600, color: muted ? c.text3 : c.text) : TypeX.ui(13, w: FontWeight.w600, color: muted ? c.text3 : c.text, h: 1.4)),
        ])),
        if (action != null) action!,
      ]),
    );
  }
}

// ====================================================================== SIMULATOR
Future<void> showSimulator(BuildContext context) {
  return showDialog<void>(
    context: context,
    barrierColor: Colors.black.withValues(alpha: .45),
    builder: (_) => Theme(data: Theme.of(context), child: const _SimDialog()),
  );
}

class _SimDialog extends StatefulWidget {
  const _SimDialog();
  @override
  State<_SimDialog> createState() => _SimDialogState();
}

class _SimDialogState extends State<_SimDialog> {
  String channel = 'ms';
  final name = TextEditingController(text: 'Rubel Hossain');
  final text = TextEditingController(text: 'bhai Ridgeline tent ta ache? delivery koto din lagbe Khulna te?');
  final phone = TextEditingController();
  bool busy = false;
  @override
  void dispose() { name.dispose(); text.dispose(); phone.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 500),
        child: Panel(
          radius: 24, shadow: true,
          child: Padding(
            padding: const EdgeInsets.all(22),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [const AiMark(size: 32), const SizedBox(width: 12), Expanded(child: Text('Simulate a customer message', style: TypeX.display(20, color: c.text))), DkIconButton(PhosphorIconsBold.x, size: 32, onPressed: () => Navigator.pop(context))]),
              const Gap(6),
              Text('Pretend a customer wrote on a channel. The assistant answers the same way it would for a real message. Real WhatsApp, Messenger and Instagram messages arrive through the webhook once you connect them.', style: TypeX.ui(13, color: c.text3)),
              const Gap(18),
              const Label('Channel'),
              const Gap(8),
              Wrap(spacing: 8, runSpacing: 8, children: [for (final k in ['wa', 'ms', 'ig', 'web']) _ChanChip(label: channelName(k), kind: k, n: 0, on: channel == k, onTap: () => setState(() => channel = k)).wrapNoCount()]),
              const Gap(16),
              DkField(controller: name, label: 'Customer name'),
              const Gap(12),
              DkField(controller: text, label: 'Message', maxLines: 4),
              const Gap(12),
              DkField(controller: phone, label: 'Phone (optional, e.g. +8801712340042 matches Nusrat)', mono: true),
              const Gap(20),
              Row(mainAxisAlignment: MainAxisAlignment.end, children: [
                DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
                const Gap(8),
                DkButton(busy ? 'Sending…' : 'Send message', icon: PhosphorIconsBold.paperPlaneTilt, kind: BtnKind.primary, onPressed: busy ? null : () async {
                  setState(() => busy = true);
                  final id = await s.simulate(channel: channel, name: name.text.trim(), text: text.text.trim(), phone: phone.text.trim());
                  if (!context.mounted) return;
                  Navigator.pop(context);
                  if (id != null) { s.setSection(Section.inbox); s.selectConversation(id); }
                }),
              ]),
            ]),
          ),
        ),
      ),
    );
  }
}

extension on _ChanChip {
  Widget wrapNoCount() => _ChanChipNoCount(label: label, kind: kind, on: on, onTap: onTap);
}

class _ChanChipNoCount extends StatelessWidget {
  const _ChanChipNoCount({required this.label, required this.kind, required this.on, required this.onTap});
  final String label;
  final String? kind;
  final bool on;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Hover(
      onTap: onTap,
      builder: (_, h, __) => AnimatedContainer(
        duration: const Duration(milliseconds: 150), padding: const EdgeInsets.fromLTRB(7, 6, 12, 6),
        decoration: BoxDecoration(color: on ? c.primary : c.surface, borderRadius: BorderRadius.circular(99), border: Border.all(color: on ? c.primary : c.line)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [ChannelIcon(kind: kind!, size: 22, circle: true), const SizedBox(width: 7), Text(label, style: TypeX.ui(12.5, w: FontWeight.w700, color: on ? Colors.white : c.text2))]),
      ),
    );
  }
}


/// What approving the drafted reply will create: shown so a person checks the exact order, not just the wording.
class _OrderPreview extends StatelessWidget {
  const _OrderPreview({required this.o});
  final Map<String, dynamic> o;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final ready = o['ready'] == true;
    final lines = (o['lines'] as List).cast<Map>();
    Widget row(String k, String v, {bool bold = false}) => Padding(padding: const EdgeInsets.symmetric(vertical: 2), child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [SizedBox(width: 86, child: Text(k, style: TypeX.ui(12, color: c.text3))), Expanded(child: Text(v, style: TypeX.ui(12.5, w: bold ? FontWeight.w800 : FontWeight.w600, color: c.text)))]));
    return Container(
      decoration: BoxDecoration(border: Border.all(color: ready ? c.primaryLine : c.warn.withValues(alpha: .6)), borderRadius: BorderRadius.circular(12), color: c.surface2),
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Icon(PhosphorIconsFill.package, size: 15, color: c.primary), const SizedBox(width: 8), Expanded(child: Text('Approving creates this order', style: TypeX.ui(12.5, w: FontWeight.w800, color: c.primary))), Tag(ready ? 'Ready' : 'Not ready', tone: ready ? 'ok' : 'warn', small: true)]),
        const Gap(8),
        for (final l in lines) row('${l['qty']} ×', '${l['name']}${l['variant'] != null ? ' · ${l['variant']}' : ''}   ${taka((l['price'] as num) * (l['qty'] as num))}'),
        row('Delivery', o['delivery'] == null ? '—' : taka(o['delivery'] as num)),
        row('Total', taka(o['total'] as num), bold: true),
        row('Payment', '${o['payment_method'] ?? '—'}'),
        row('Recipient', '${o['name'] ?? '—'} · ${o['phone'] ?? '—'}'),
        row('Address', '${o['address'] ?? '—'}'),
        if (!ready) Padding(padding: const EdgeInsets.only(top: 6), child: Text('Something changed since the customer confirmed (stock, price or details). Approving will be refused; dismiss this draft.', style: TypeX.ui(12, color: c.warn, h: 1.4))),
      ]),
    );
  }
}
