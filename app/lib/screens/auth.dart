import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../brand/icons.dart';
import '../brand/theme.dart';
import '../core/state.dart';
import '../shell/shell.dart' show Brand;
import '../widgets/kit.dart';

/// Sign in, first-run owner setup and the forced password change share one layout.
class AuthScreen extends StatelessWidget {
  const AuthScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final form = switch (s.phase) {
      Phase.setup => const _SetupForm(),
      Phase.mustChange => const _ChangeForm(),
      _ => const _LoginForm(),
    };
    return Scaffold(
      backgroundColor: c.bg,
      body: LayoutBuilder(builder: (context, box) {
        final wide = box.maxWidth >= 960;
        final formPane = Container(
          color: c.surface,
          child: SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: EdgeInsets.symmetric(horizontal: wide ? 56 : 24, vertical: 32),
                child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 420), child: AutofillGroup(child: form)),
              ),
            ),
          ),
        );
        if (!wide) return formPane;
        return Row(children: [Expanded(flex: 11, child: const _Hero()), Expanded(flex: 9, child: formPane)]);
      }),
    );
  }
}

class _Hero extends StatelessWidget {
  const _Hero();
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      decoration: BoxDecoration(gradient: c.hero),
      clipBehavior: Clip.antiAlias,
      child: Stack(children: [
        Positioned(right: -120, top: -140, child: Container(width: 460, height: 460, decoration: BoxDecoration(shape: BoxShape.circle, color: Colors.white.withValues(alpha: .06)))),
        Positioned(left: -140, bottom: -180, child: Container(width: 520, height: 520, decoration: BoxDecoration(shape: BoxShape.circle, color: Colors.white.withValues(alpha: .05)))),
        Padding(
          padding: const EdgeInsets.fromLTRB(64, 56, 64, 48),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Brand(),
            const Spacer(),
            Reveal(child: Text('Every chat.\nOne inbox.', style: TypeX.display(60, color: Colors.white, h: 1.02, ls: -.04))),
            const Gap(18),
            Reveal(delay: 120, child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 460), child: Text('WhatsApp, Messenger, Instagram and your website, answered in Bangla, Banglish and English by an assistant that actually does the work, and hands over to your team when it should.', style: TypeX.ui(16, color: Colors.white.withValues(alpha: .82), h: 1.55)))),
            const Gap(36),
            const Reveal(delay: 240, child: _Bubble(kind: 'wa', who: 'Rakib', text: 'bhai amar order ta kothay? #1042', align: Alignment.centerLeft)),
            const Gap(10),
            const Reveal(delay: 340, child: _Bubble(kind: 'ai', who: 'Assistant', text: 'Apnar order Steadfast e ache, kal pouchabe. Tracking SF-26110841', align: Alignment.centerRight)),
            const Gap(10),
            const Reveal(delay: 440, child: _Bubble(kind: 'ms', who: 'Nusrat', text: 'একটা কার্টে দিয়ে দিন প্লিজ', align: Alignment.centerLeft)),
            const Spacer(),
            Row(children: [
              for (final k in ['wa', 'ms', 'ig', 'web']) Padding(padding: const EdgeInsets.only(right: 10), child: ChannelIcon(kind: k, size: 30)),
              const Gap(6),
              Text('and one assistant for all of them', style: TypeX.ui(13, color: Colors.white.withValues(alpha: .7))),
            ]),
          ]),
        ),
      ]),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.kind, required this.who, required this.text, required this.align});
  final String kind, who, text;
  final Alignment align;
  @override
  Widget build(BuildContext context) {
    final ai = kind == 'ai';
    final bn = RegExp(r'[ঀ-৿]').hasMatch(text);
    return Align(
      alignment: align,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 400),
        padding: const EdgeInsets.fromLTRB(12, 10, 16, 10),
        decoration: BoxDecoration(
          color: ai ? Colors.white : Colors.white.withValues(alpha: .13),
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: Colors.white.withValues(alpha: ai ? 0 : .18)),
          boxShadow: ai ? [BoxShadow(color: Colors.black.withValues(alpha: .25), blurRadius: 30, offset: const Offset(0, 14), spreadRadius: -10)] : null,
        ),
        child: Row(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          ai ? const AiMark(size: 26) : ChannelIcon(kind: kind, size: 26, circle: true),
          const SizedBox(width: 10),
          Flexible(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(who, style: TypeX.ui(11.5, w: FontWeight.w800, color: ai ? const Color(0xFF3558FA) : Colors.white70)),
              const SizedBox(height: 2),
              Text(text, style: bn ? TypeX.bn(14, color: Colors.white) : TypeX.ui(14, color: ai ? const Color(0xFF0D1230) : Colors.white)),
            ]),
          ),
        ]),
      ),
    );
  }
}

// ------------------------------------------------------------------ fields
class _Field extends StatefulWidget {
  const _Field({required this.label, required this.controller, this.password = false, this.hints, this.onSubmit, this.action = TextInputAction.next, this.autofocus = false, this.type});
  final String label;
  final TextEditingController controller;
  final bool password, autofocus;
  final Iterable<String>? hints;
  final VoidCallback? onSubmit;
  final TextInputAction action;
  final TextInputType? type;
  @override
  State<_Field> createState() => _FieldState();
}

class _FieldState extends State<_Field> {
  bool hide = true;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(widget.label, style: TypeX.ui(12.5, w: FontWeight.w700, color: c.text2)),
      const SizedBox(height: 6),
      TextField(
        controller: widget.controller, obscureText: widget.password && hide, autofocus: widget.autofocus, autofillHints: widget.hints,
        textInputAction: widget.action, keyboardType: widget.type, enableSuggestions: !widget.password, autocorrect: !widget.password,
        onSubmitted: (_) => widget.onSubmit?.call(), style: TypeX.ui(15, color: c.text), cursorColor: c.primary,
        decoration: InputDecoration(
          filled: true, fillColor: c.surface2, isDense: true, contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
          suffixIcon: widget.password ? Hover(onTap: () => setState(() => hide = !hide), builder: (_, __, ___) => Icon(hide ? PhosphorIconsRegular.eye : PhosphorIconsRegular.eyeSlash, size: 19, color: c.text3)) : null,
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide(color: c.line2)),
          enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide(color: c.line2)),
          focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide(color: c.primary, width: 1.8)),
        ),
      ),
    ]);
  }
}

class _ErrorBox extends StatelessWidget {
  const _ErrorBox(this.text);
  final String text;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      margin: const EdgeInsets.only(bottom: 16), padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(12), border: Border.all(color: c.danger.withValues(alpha: .25))),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(PhosphorIconsFill.warningCircle, size: 18, color: c.danger), const SizedBox(width: 10),
        Expanded(child: Text(text, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
      ]),
    );
  }
}

class _Head extends StatelessWidget {
  const _Head({required this.title, required this.body});
  final String title, body;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (MediaQuery.of(context).size.width < 960) ...[const Brand(light: false), const Gap(32)],
      Text(title, style: TypeX.display(32, color: c.text, ls: -.03)),
      const Gap(8),
      Text(body, style: TypeX.ui(14.5, color: c.text3, h: 1.5)),
      const Gap(28),
    ]);
  }
}

/// Strength bar that never claims a weak password is fine.
class _Strength extends StatelessWidget {
  const _Strength(this.pw);
  final String pw;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    var score = 0;
    if (pw.length >= 10) score++;
    if (pw.length >= 14) score++;
    if (RegExp(r'[A-Z]').hasMatch(pw) && RegExp(r'[a-z]').hasMatch(pw)) score++;
    if (RegExp(r'\d').hasMatch(pw) || RegExp(r'[^A-Za-z0-9]').hasMatch(pw)) score++;
    if (pw.length < 10) score = score.clamp(0, 1);
    final col = [c.danger, c.danger, c.warn, c.ok, c.ok][score];
    final label = pw.isEmpty ? 'At least 10 characters' : (pw.length < 10 ? '${10 - pw.length} more characters' : ['Weak', 'Okay', 'Good', 'Strong', 'Strong'][score]);
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Row(children: [
        for (var i = 0; i < 4; i++) Expanded(child: AnimatedContainer(duration: const Duration(milliseconds: 200), height: 4, margin: EdgeInsets.only(right: i == 3 ? 0 : 5), decoration: BoxDecoration(color: pw.isNotEmpty && i < score.clamp(1, 4) ? col : c.line, borderRadius: BorderRadius.circular(9)))),
        const SizedBox(width: 12),
        Text(label, style: TypeX.ui(12, w: FontWeight.w600, color: pw.isEmpty ? c.text3 : col)),
      ]),
    );
  }
}

// ------------------------------------------------------------------ the three forms
class _LoginForm extends StatefulWidget {
  const _LoginForm();
  @override
  State<_LoginForm> createState() => _LoginFormState();
}

class _LoginFormState extends State<_LoginForm> {
  final email = TextEditingController();
  final pw = TextEditingController();
  @override
  void dispose() { email.dispose(); pw.dispose(); super.dispose(); }

  Future<void> _go() async {
    if (email.text.trim().isEmpty || pw.text.isEmpty) return;
    final ok = await context.read<AppState>().signIn(email.text, pw.text);
    if (!ok) pw.clear();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const _Head(title: 'Welcome back', body: 'Sign in to your team’s inbox.'),
      if (s.authError != null) _ErrorBox(s.authError!),
      _Field(label: 'Email', controller: email, hints: const [AutofillHints.username, AutofillHints.email], type: TextInputType.emailAddress, autofocus: true),
      const Gap(16),
      _Field(label: 'Password', controller: pw, password: true, hints: const [AutofillHints.password], action: TextInputAction.done, onSubmit: _go),
      const Gap(24),
      DkButton(s.authBusy ? 'Signing in…' : 'Sign in', icon: PhosphorIconsBold.arrowRight, kind: BtnKind.primary, expand: true, onPressed: s.authBusy ? null : _go),
      if (s.offline) ...[const Gap(12), DkButton('Retry connection', kind: BtnKind.ghost, expand: true, onPressed: s.retryConnection)],
      const Gap(24),
      Text('Forgot your password? Ask an owner or admin on your team to reset it for you.', style: TypeX.ui(12.5, color: c.text3, h: 1.5)),
    ]);
  }
}

class _SetupForm extends StatefulWidget {
  const _SetupForm();
  @override
  State<_SetupForm> createState() => _SetupFormState();
}

class _SetupFormState extends State<_SetupForm> {
  final name = TextEditingController();
  final email = TextEditingController();
  final pw = TextEditingController();
  final pw2 = TextEditingController();
  String? localError;
  @override
  void dispose() { name.dispose(); email.dispose(); pw.dispose(); pw2.dispose(); super.dispose(); }

  Future<void> _go() async {
    final s = context.read<AppState>();
    setState(() => localError = null);
    if (name.text.trim().length < 2) return setState(() => localError = 'Enter your name.');
    if (!email.text.contains('@')) return setState(() => localError = 'Enter a valid email address.');
    if (pw.text.length < 10) return setState(() => localError = 'Use at least 10 characters for the password.');
    if (pw.text != pw2.text) return setState(() => localError = 'The two passwords do not match.');
    await s.createOwner(name.text, email.text, pw.text);
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final err = localError ?? s.authError;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const _Head(title: 'Set up your workspace', body: 'Create the owner account. You can add teammates and choose what each of them can do afterwards.'),
      if (err != null) _ErrorBox(err),
      _Field(label: 'Your name', controller: name, hints: const [AutofillHints.name], autofocus: true),
      const Gap(14),
      _Field(label: 'Work email', controller: email, hints: const [AutofillHints.username, AutofillHints.email], type: TextInputType.emailAddress),
      const Gap(14),
      ListenableBuilder(listenable: pw, builder: (_, __) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [_Field(label: 'Password', controller: pw, password: true, hints: const [AutofillHints.newPassword]), _Strength(pw.text)])),
      const Gap(14),
      _Field(label: 'Confirm password', controller: pw2, password: true, hints: const [AutofillHints.newPassword], action: TextInputAction.done, onSubmit: _go),
      const Gap(24),
      DkButton(s.authBusy ? 'Creating…' : 'Create workspace', icon: PhosphorIconsBold.arrowRight, kind: BtnKind.primary, expand: true, onPressed: s.authBusy ? null : _go),
      const Gap(20),
      Text('This screen only appears once. After the first owner exists, nobody can create another account without signing in.', style: TypeX.ui(12.5, color: c.text3, h: 1.5)),
    ]);
  }
}

class _ChangeForm extends StatefulWidget {
  const _ChangeForm();
  @override
  State<_ChangeForm> createState() => _ChangeFormState();
}

class _ChangeFormState extends State<_ChangeForm> {
  final cur = TextEditingController();
  final pw = TextEditingController();
  final pw2 = TextEditingController();
  String? localError;
  @override
  void dispose() { cur.dispose(); pw.dispose(); pw2.dispose(); super.dispose(); }

  Future<void> _go() async {
    final s = context.read<AppState>();
    setState(() => localError = null);
    if (cur.text.isEmpty) return setState(() => localError = 'Enter the temporary password you were given.');
    if (pw.text.length < 10) return setState(() => localError = 'Use at least 10 characters.');
    if (pw.text != pw2.text) return setState(() => localError = 'The two passwords do not match.');
    await s.changePassword(cur.text, pw.text);
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final err = localError ?? s.authError;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _Head(title: 'Choose your password', body: 'Hi ${(s.user['first'] ?? '')}. The password you were given is temporary. Pick one only you know.'),
      if (err != null) _ErrorBox(err),
      _Field(label: 'Temporary password', controller: cur, password: true, hints: const [AutofillHints.password], autofocus: true),
      const Gap(14),
      ListenableBuilder(listenable: pw, builder: (_, __) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [_Field(label: 'New password', controller: pw, password: true, hints: const [AutofillHints.newPassword]), _Strength(pw.text)])),
      const Gap(14),
      _Field(label: 'Confirm new password', controller: pw2, password: true, hints: const [AutofillHints.newPassword], action: TextInputAction.done, onSubmit: _go),
      const Gap(24),
      DkButton(s.authBusy ? 'Saving…' : 'Save and continue', icon: PhosphorIconsBold.arrowRight, kind: BtnKind.primary, expand: true, onPressed: s.authBusy ? null : _go),
      const Gap(8),
      DkButton('Sign out', kind: BtnKind.ghost, expand: true, onPressed: s.signOut),
    ]);
  }
}
