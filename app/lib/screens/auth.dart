import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../brand/icons.dart';
import '../brand/theme.dart';
import '../core/state.dart';
import '../shell/shell.dart' show Brand;
import '../widgets/kit.dart';
import 'auth_hero.dart';

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
      Phase.pickBusiness => const _PickBusiness(),
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
        return Row(children: [Expanded(flex: 11, child: AuthHero(setup: s.phase == Phase.setup)), Expanded(flex: 9, child: formPane)]);
      }),
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
  final _focus = FocusNode();
  bool _focused = false;
  @override
  void initState() {
    super.initState();
    _focus.addListener(() { if (mounted) setState(() => _focused = _focus.hasFocus); });
  }

  @override
  void dispose() { _focus.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(widget.label, style: TypeX.ui(12.5, w: FontWeight.w700, color: _focused ? c.primary : c.text2)),
      const SizedBox(height: 6),
      AnimatedContainer(
        duration: const Duration(milliseconds: 180), curve: Curves.easeOut,
        decoration: BoxDecoration(borderRadius: BorderRadius.circular(16), boxShadow: [if (_focused) BoxShadow(color: c.primary.withValues(alpha: .18), blurRadius: 0, spreadRadius: 4)]),
        child: TextField(
        focusNode: _focus,
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
      )),
    ]);
  }
}

class _ErrorBox extends StatelessWidget {
  const _ErrorBox(this.text);
  final String text;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return TweenAnimationBuilder<double>(
      key: ValueKey(text), tween: Tween(begin: 0, end: 1), duration: const Duration(milliseconds: 520),
      builder: (_, t, child) => Opacity(opacity: t.clamp(0, 1), child: Transform.translate(offset: Offset(math.sin(t * math.pi * 5) * (1 - t) * 9, 0), child: child)),   // a short shake: the sign-in did not work
      child: Container(
        margin: const EdgeInsets.only(bottom: 16), padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(12), border: Border.all(color: c.danger.withValues(alpha: .25))),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(PhosphorIconsFill.warningCircle, size: 18, color: c.danger), const SizedBox(width: 10),
          Expanded(child: Text(text, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
        ]),
      ),
    );
  }
}

class _Head extends StatelessWidget {
  const _Head({required this.title, required this.body, this.eyebrow});
  final String title, body;
  final String? eyebrow;                       // a small label above the title, e.g. the first-run step
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (MediaQuery.of(context).size.width < 960) ...[const Brand(light: false), const Gap(32)],
      if (eyebrow != null) Reveal(child: Padding(padding: const EdgeInsets.only(bottom: 14), child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(color: c.primarySoft, borderRadius: BorderRadius.circular(20)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [Icon(PhosphorIconsFill.sparkle, size: 12, color: c.primary), const SizedBox(width: 6), Text(eyebrow!, style: TypeX.ui(11, w: FontWeight.w800, color: c.primary, ls: .6))]),
      ))),
      Reveal(child: Text(title, style: TypeX.display(32, color: c.text, ls: -.03))),
      const Gap(8),
      Reveal(delay: 70, child: Text(body, style: TypeX.ui(14.5, color: c.text3, h: 1.5))),
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
      Reveal(delay: 120, child: _Field(label: 'Email', controller: email, hints: const [AutofillHints.username, AutofillHints.email], type: TextInputType.emailAddress, autofocus: true)),
      const Gap(16),
      Reveal(delay: 180, child: _Field(label: 'Password', controller: pw, password: true, hints: const [AutofillHints.password], action: TextInputAction.done, onSubmit: _go)),
      const Gap(24),
      Reveal(delay: 240, child: DkButton(s.authBusy ? 'Signing in…' : 'Sign in', icon: PhosphorIconsBold.arrowRight, kind: BtnKind.primary, expand: true, onPressed: s.authBusy ? null : _go)),
      if (s.offline) ...[const Gap(12), DkButton('Retry connection', kind: BtnKind.ghost, expand: true, onPressed: s.retryConnection)],
      const Gap(26),
      Reveal(delay: 300, child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(14), border: Border.all(color: c.line)),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(PhosphorIconsRegular.key, size: 17, color: c.text3),
          const SizedBox(width: 10),
          Expanded(child: Text('Forgot your password, or need access? Ask an owner or admin of your business: they can reset it or invite you.', style: TypeX.ui(12.5, color: c.text3, h: 1.5))),
        ]),
      )),
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
      _Head(eyebrow: s.hostedServer ? 'SUPER ADMIN SETUP' : 'FIRST-TIME SETUP', title: s.hostedServer ? 'Create the super admin' : 'Create your workspace', body: s.hostedServer ? 'This account runs the whole server: it creates businesses and their owners, sets plans and looks after everyone. Businesses are created afterwards from its panel.' : 'Make the owner account. You can invite teammates and choose what each of them can do afterwards.'),
      if (err != null) _ErrorBox(err),
      Reveal(delay: 100, child: _Field(label: 'Your name', controller: name, hints: const [AutofillHints.name], autofocus: true)),
      const Gap(14),
      Reveal(delay: 150, child: _Field(label: 'Work email', controller: email, hints: const [AutofillHints.username, AutofillHints.email], type: TextInputType.emailAddress)),
      const Gap(14),
      Reveal(delay: 200, child: ListenableBuilder(listenable: pw, builder: (_, __) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [_Field(label: 'Password', controller: pw, password: true, hints: const [AutofillHints.newPassword]), _Strength(pw.text)]))),
      const Gap(14),
      Reveal(delay: 250, child: ListenableBuilder(listenable: Listenable.merge([pw, pw2]), builder: (_, __) {
        final match = pw2.text.isNotEmpty && pw.text == pw2.text;
        final differs = pw2.text.isNotEmpty && pw.text != pw2.text;
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _Field(label: 'Confirm password', controller: pw2, password: true, hints: const [AutofillHints.newPassword], action: TextInputAction.done, onSubmit: _go),
          AnimatedSize(duration: const Duration(milliseconds: 180), child: pw2.text.isEmpty ? const SizedBox(width: double.infinity) : Padding(padding: const EdgeInsets.only(top: 8), child: Row(children: [
            Icon(match ? PhosphorIconsFill.checkCircle : PhosphorIconsFill.warningCircle, size: 14, color: match ? c.ok : c.danger),
            const SizedBox(width: 6),
            Text(match ? 'The passwords match' : (differs ? 'The passwords do not match yet' : ''), style: TypeX.ui(12, w: FontWeight.w600, color: match ? c.ok : c.danger)),
          ]))),
        ]);
      })),
      const Gap(24),
      Reveal(delay: 300, child: DkButton(s.authBusy ? 'Creating…' : (s.hostedServer ? 'Create super admin' : 'Create workspace'), icon: PhosphorIconsBold.arrowRight, kind: BtnKind.primary, expand: true, onPressed: s.authBusy ? null : _go)),
      const Gap(22),
      Reveal(delay: 350, child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(14), border: Border.all(color: c.line)),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(PhosphorIconsRegular.sealCheck, size: 17, color: c.text3),
          const SizedBox(width: 10),
          Expanded(child: Text('This screen appears only once. After the first owner exists, nobody can create another account without signing in.', style: TypeX.ui(12.5, color: c.text3, h: 1.5))),
        ]),
      )),
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


/// A platform administrator who belongs to no business yet (or has left them all): pick one to work in, or make a new one.
class _PickBusiness extends StatefulWidget {
  const _PickBusiness();
  @override
  State<_PickBusiness> createState() => _PickBusinessState();
}

class _PickBusinessState extends State<_PickBusiness> {
  String? error;
  bool busy = false;

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Choose a business', style: TypeX.display(30, color: c.text)),
      const Gap(6),
      Text(s.businesses.isEmpty ? 'You are not part of any business yet. Ask the owner of your business to add you, or contact the Dakbox administrator.' : 'You work in more than one business. Pick the one to open. You can switch at any time from the account menu.', style: TypeX.ui(14, color: c.text3, h: 1.5)),
      const Gap(20),
      for (final b in s.businesses)
        Padding(padding: const EdgeInsets.only(bottom: 8), child: DkButton('${b['name']}  ·  ${b['role']}', kind: BtnKind.soft, expand: true, onPressed: busy ? null : () async { setState(() => busy = true); final e = await s.switchBusiness(b['id'] as String); if (mounted) setState(() { busy = false; error = e; }); })),
      if (error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(error!, style: TypeX.ui(13, color: c.danger))),
      const Gap(20),
      DkButton('Sign out', kind: BtnKind.ghost, onPressed: s.signOut),
    ]);
  }
}
