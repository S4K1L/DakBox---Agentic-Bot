import 'dart:async';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'api.dart';
import 'download.dart';

enum Section { inbox, approvals, orders, products, customers, insights, connections, assistant, team, setup, business }

/// Where the app is in the sign-in flow.
enum Phase { loading, setup, login, mustChange, pickBusiness, ready }

extension SectionX on Section {
  String get label => switch (this) {
        Section.inbox => 'Inbox',
        Section.approvals => 'Approvals',
        Section.orders => 'Orders',
        Section.products => 'Products',
        Section.customers => 'Customers',
        Section.insights => 'Insights',
        Section.connections => 'Connections',
        Section.assistant => 'Assistant',
        Section.team => 'Team',
        Section.setup => 'Get started',
        Section.business => 'My business',
      };
}

class AppState extends ChangeNotifier {
  AppState({Api? api}) : api = api ?? Api() {
    _boot();
  }

  final Api api;
  Timer? _timer;
  bool _disposed = false;

  // session
  J me = {};
  bool offline = false; // backend unreachable
  bool booted = false;
  ThemeMode themeMode = ThemeMode.light;
  Section section = Section.inbox;

  // toast
  String? toastText;
  bool toastError = false;
  int _toastId = 0;

  // inbox
  List<J> convs = [];
  String? convId;
  J? conv;
  String convTab = 'all'; // all | needs | assistant
  String channelFilter = 'all'; // all | wa | ms | ig | web
  String query = '';
  bool showMobileThread = false;

  // approvals
  List<J> approvals = [];
  int pendingApprovals = 0;
  int draftsWaiting = 0;
  String apprStatus = 'pending';
  int? apprId;

  // commerce
  List<J> orders = [];
  String? orderNo;
  String orderTab = 'all';
  String orderQuery = '';
  List<J> products = [];
  String productTab = 'all';
  String productQuery = '';
  List<J> customers = [];
  String customerQuery = '';

  // more
  J? insights;
  List<J> channels = [];
  J channelsMeta = {};
  List<J> integrations = [];
  List<J> notifications = [];
  J? settings;

  // ---------------------------------------------------------------- lifecycle
  Future<void> _boot() async {
    api.onUnauthorized = _sessionEnded;
    try {
      final prefs = await SharedPreferences.getInstance();
      api.token = prefs.getString(_tokenKey);
    } catch (_) {/* storage unavailable: sign in each time */}
    await _resolveAuth();
    booted = true;
    notifyListeners();
  }

  // ---------------------------------------------------------------- auth
  static const _tokenKey = 'dakbox_token';
  Phase phase = Phase.loading;
  J user = {};
  String? authError;
  bool authBusy = false;

  bool can(String perm) => ((user['permissions'] as List?) ?? const []).contains(perm);
  String get role => (user['role'] as String?) ?? '';

  Future<void> _saveToken(String? t) async {
    api.token = t;
    try {
      final prefs = await SharedPreferences.getInstance();
      if (t == null) { await prefs.remove(_tokenKey); } else { await prefs.setString(_tokenKey, t); }
    } catch (_) {}
  }

  Future<void> _resolveAuth() async {
    if (api.token != null) {
      try {
        final m = await api.get('/api/me');
        _enter(m);
        return;
      } on ApiError catch (e) {
        if (e.status == null) { authError = 'Cannot reach the Dakbox server.'; phase = Phase.login; offline = true; return; }
        if (e.message == 'password_change_required') { /* /api/me is allowed, so this is not expected */ }
        await _saveToken(null);
      }
    }
    try {
      final st = await api.getPublic('/api/auth/status');
      offline = false;
      hostedServer = st['hosted'] == true;
      phase = st['setupRequired'] == true ? Phase.setup : Phase.login;
    } on ApiError {
      offline = true;
      authError = 'Cannot reach the Dakbox server.';
      phase = Phase.login;
    }
  }

  bool hostedServer = false;                      // a server that hosts other people's businesses: its first account is the super administrator only

  /// Which panel the app shows: the business panel (a business's owner and staff) or the super admin panel (platform administrators).
  String panel = 'business';
  bool get inAdmin => isPlatformAdmin && panel == 'admin';

  void openAdminPanel() { panel = 'admin'; _timer?.cancel(); notifyListeners(); loadPlatform(); }

  void _enter(J me, {String? panel}) {
    user = me;
    this.me = me;
    authError = null;
    offline = false;
    if (me['mustChange'] == true) {
      phase = Phase.mustChange;
      _timer?.cancel();
      return;
    }
    final admin = me['platformAdmin'] == true;
    this.panel = admin ? (panel ?? 'admin') : 'business';     // a platform administrator lands in the super admin panel; everyone else in their business
    if (this.panel == 'admin') {
      phase = Phase.ready;
      _timer?.cancel();
      loadPlatform();
      _notify();
      return;
    }
    if (me['business'] == null) {          // someone with no business to work in yet: choose one
      phase = Phase.pickBusiness;
      _timer?.cancel();
      _notify();
      return;
    }
    phase = Phase.ready;
    if (!can('team.manage') && (section == Section.team || section == Section.business)) section = Section.inbox;
    refreshCore();
    loadOnboarding(entering: true);
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(milliseconds: 2200), (_) => _tick());
  }

  Future<void> retryConnection() async {
    authError = null;
    phase = Phase.loading;
    notifyListeners();
    await _resolveAuth();
    notifyListeners();
  }

  Future<bool> signIn(String email, String password) async {
    authBusy = true; authError = null; notifyListeners();
    try {
      final r = await api.postPublic('/api/auth/login', {'email': email.trim(), 'password': password});
      await _saveToken(r['token'] as String);
      final m = await api.get('/api/me');
      _enter(m);
      authBusy = false; notifyListeners();
      return true;
    } on ApiError catch (e) {
      authError = e.message; authBusy = false; notifyListeners();
      return false;
    }
  }

  Future<bool> createOwner(String name, String email, String password) async {
    authBusy = true; authError = null; notifyListeners();
    try {
      final r = await api.postPublic('/api/auth/setup', {'name': name.trim(), 'email': email.trim(), 'password': password});
      await _saveToken(r['token'] as String);
      final m = await api.get('/api/me');
      _enter(m);
      authBusy = false; notifyListeners();
      return true;
    } on ApiError catch (e) {
      authError = e.message; authBusy = false; notifyListeners();
      return false;
    }
  }

  Future<bool> changePassword(String current, String next) async {
    authBusy = true; authError = null; notifyListeners();
    try {
      await api.post('/api/auth/password', {'current': current, 'new': next});
      final m = await api.get('/api/me');
      _enter(m);
      authBusy = false; notifyListeners();
      toast('Password updated. Other devices were signed out');
      return true;
    } on ApiError catch (e) {
      authError = e.message; authBusy = false; notifyListeners();
      return false;
    }
  }

  // ---------------------------------------------------------------- businesses
  List<J> get businesses => ((me['businesses'] as List?) ?? const []).cast<J>();
  bool get isPlatformAdmin => me['platformAdmin'] == true;
  String? get businessId => (me['business'] as Map?)?['id'] as String?;

  /// Work in another business you belong to. Everything on screen belongs to the previous one, so it is dropped before the new one loads.
  Future<String?> switchBusiness(String ref) async {
    try {
      await api.post('/api/auth/switch', {'business': ref});
      _clearData();
      phase = Phase.loading;
      notifyListeners();
      _enter(await api.get('/api/me'), panel: 'business');
      notifyListeners();
      return null;
    } on ApiError catch (e) {
      if (phase == Phase.loading) { phase = Phase.ready; notifyListeners(); }
      return e.message;
    }
  }

  // ---------------------------------------------------------------- setup guide (a new business)
  J? onboarding;
  String? assistantTab;                          // set by the guide so the Assistant screen opens on the tab it points to

  bool get showSetup => onboarding?['show'] == true && can('settings.write');

  Future<void> loadOnboarding({bool entering = false}) async {
    try {
      onboarding = await api.get('/api/onboarding');
      if (entering && showSetup) section = Section.setup;
      _notify();
    } on ApiError catch (_) {}
  }

  Future<J> skipStep(String step) => _try(() async { onboarding = await api.post('/api/onboarding/skip', {'step': step}); _notify(); return onboarding!; });
  Future<J> dismissSetup() => _try(() async {
        onboarding = await api.post('/api/onboarding/dismiss');
        if (section == Section.setup) section = Section.inbox;
        _notify();
        return onboarding!;
      });

  void openAssistantTab(String tab) { assistantTab = tab; setSection(Section.assistant); }

  // ---------------------------------------------------------------- the business owner's panel
  J? business;                                   // this business as its owner sees it: details, plan and use

  Future<void> loadBusiness() async {
    try { business = await api.get('/api/business'); _notify(); } on ApiError catch (_) {}
  }

  Future<J> renameBusiness(String name) => _try(() async {
        business = await api.patch('/api/business', {'name': name});
        final m = await api.get('/api/me');
        me = m; user = m;
        _notify();
        return business!;
      });

  /// Ask for a copy of the business's data and hand it to the browser. Returns an error message, or null.
  Future<String?> exportMyData() async {
    final r = await _try(() => api.post('/api/business/export'));
    if (r['error'] != null) return r['error'] as String;
    return openDownload('${api.base}${r['url']}') ? null : 'Your browser could not start the download.';
  }

  // ---------------------------------------------------------------- platform administration
  J? pOverview;
  List<J> pBusinesses = [], pUsage = [], pPlans = [], pAccounts = [], pLog = [], pFeatures = [];

  Future<void> loadPlatform() async {
    if (!isPlatformAdmin) return;
    try {
      pOverview = await api.get('/api/platform/overview');
      pBusinesses = ((await api.get('/api/platform/businesses'))['items'] as List).cast<J>();
      final u = await api.get('/api/platform/usage');
      pUsage = (u['items'] as List).cast<J>();
      pPlans = ((await api.get('/api/platform/plans'))['items'] as List).cast<J>();
      pAccounts = ((await api.get('/api/platform/accounts'))['items'] as List).cast<J>();
      pLog = ((await api.get('/api/platform/log', q: {'limit': 60}))['items'] as List).cast<J>();
      pFeatures = ((await api.get('/api/platform/features'))['items'] as List).cast<J>();
      _notify();
    } on ApiError catch (_) {}
  }

  Future<J> _platformDo(Future<J> Function() f) => _try(() async { final r = await f(); await loadPlatform(); return r; });

  Future<J> patchBusiness(String slug, J body) => _platformDo(() => api.patch('/api/platform/businesses/$slug', body));
  Future<J> deleteBusiness(String slug, String confirm) => _platformDo(() => api.post('/api/platform/businesses/$slug/delete', {'confirm': confirm}));
  Future<J> joinBusiness(String slug) => _platformDo(() => api.post('/api/platform/businesses/$slug/join'));
  Future<J> leaveBusiness(String slug) => _platformDo(() => api.post('/api/platform/businesses/$slug/leave'));
  Future<J> businessDetail(String slug) => _try(() => api.get('/api/platform/businesses/$slug'));
  Future<J> accountDetail(String id) => _try(() => api.get('/api/platform/accounts/$id'));
  Future<J> createAccount(J body) => _platformDo(() => api.post('/api/platform/accounts', body));
  Future<J> resetAccountPassword(String id, String pw) => _try(() => api.post('/api/platform/accounts/$id/reset-password', {'password': pw}));
  Future<J> setMembership(String id, String slug, J body) => _platformDo(() => api.put('/api/platform/accounts/$id/memberships/$slug', body));
  Future<J> removeMembership(String id, String slug) => _platformDo(() => api.delete('/api/platform/accounts/$id/memberships/$slug'));
  Future<J> deleteAccount(String id) => _platformDo(() => api.post('/api/platform/accounts/$id/delete'));
  Future<J> platformHealth() => _try(() => api.get('/api/platform/health'));
  Future<J> platformBackups() => _try(() => api.get('/api/platform/backups'));
  Future<J> backupNow() => _try(() => api.post('/api/platform/backups'));
  Future<J> drillBackup(String name) => _try(() => api.post('/api/platform/backups/$name/drill'));
  Future<J> eraseCustomer(String id) => _try(() => api.post('/api/customers/$id/erase'));
  Future<J> savePlan(String id, J body) => _platformDo(() => api.put('/api/platform/plans/$id', body));
  Future<J> platformAi() => _try(() => api.get('/api/platform/ai'));
  Future<J> savePlatformAi(String provider, String key, {String? model, String? smallModel}) => _try(() => api.put('/api/platform/ai', {'provider': provider, 'key': key, 'model': model, 'smallModel': smallModel}));
  Future<J> removePlatformAi(String provider) => _try(() => api.delete('/api/platform/ai?provider=$provider'));
  Future<J> patchAccount(String id, J body) => _platformDo(() => api.patch('/api/platform/accounts/$id', body));

  /// Build the export and hand it to the browser. Returns an error message, or null.
  Future<String?> exportBusiness(String slug) async {
    final r = await _try(() => api.post('/api/platform/businesses/$slug/export'));
    if (r['error'] != null) return r['error'] as String;
    final url = '${api.base}${r['url']}';
    return openDownload(url) ? null : 'Your browser could not start the download.';
  }

  /// Create a business with its own owner (a new person with a temporary password, or an existing account by email).
  Future<J> createBusiness(String name, String? slug, {String? plan, String? ownerName, String? ownerEmail, String? ownerPassword}) =>
      _platformDo(() => api.post('/api/platform/businesses', {'name': name, if (slug != null && slug.isNotEmpty) 'slug': slug, if (plan != null) 'plan': plan, if (ownerEmail != null) 'owner': {'name': ownerName ?? '', 'email': ownerEmail, 'password': ownerPassword ?? ''}}));

  void _clearData() {
    _timer?.cancel();
    me = {}; user = {};
    convs = []; convId = null; conv = null; approvals = []; orders = []; products = []; customers = [];
    insights = null; channels = []; integrations = []; settings = null; team = []; audit = [];
    onboarding = null; assistantTab = null; pOverview = null; pBusinesses = []; pUsage = []; pPlans = []; pAccounts = []; pLog = []; pFeatures = []; business = null; panel = 'business';
    pendingApprovals = 0; draftsWaiting = 0; section = Section.inbox; showMobileThread = false;
  }

  Future<void> signOut() async {
    try { await api.post('/api/auth/logout'); } on ApiError catch (_) {}
    await _saveToken(null);
    _clearData();
    authError = null;
    phase = Phase.login;
    notifyListeners();
  }

  void _sessionEnded() {
    if (phase == Phase.login || phase == Phase.setup) return;
    _saveToken(null);
    _clearData();
    authError = 'Your session has ended. Sign in again.';
    phase = Phase.login;
    notifyListeners();
  }

  // ---------------------------------------------------------------- team
  List<J> team = [];
  List<J> roleGuide = [];
  bool canGrantOwner = false;
  List<J> audit = [];
  J? seats;                                      // {used, limit, left} for this business's plan

  Future<void> loadTeam() async {
    if (!can('team.manage')) return;
    try {
      final r = await api.get('/api/team');
      team = (r['items'] as List).cast<J>();
      roleGuide = (r['roles'] as List).cast<J>();
      canGrantOwner = r['canGrantOwner'] == true;
      seats = r['seats'] as J?;
      final a = await api.get('/api/audit', q: {'limit': 40});
      audit = (a['items'] as List).cast<J>();
      _notify();
    } on ApiError catch (_) {}
  }

  /// Returns an error message, or null on success.
  Future<String?> invite(String name, String email, String role, String password) async {
    try {
      final r = await api.post('/api/team', {'name': name, 'email': email, 'role': role, 'password': password});
      await loadTeam();
      toast('$name was added. They choose their own password at first sign-in. ${r['note'] ?? ''}'.trim());
      return null;
    } on ApiError catch (e) { return e.message; }
  }

  Future<String?> updateMember(String id, J patch) async {
    try {
      await api.patch('/api/team/$id', patch);
      await loadTeam();
      return null;
    } on ApiError catch (e) { return e.message; }
  }

  Future<String?> resetMemberPassword(String id, String password) async {
    try {
      await api.post('/api/team/$id/reset-password', {'password': password});
      await loadTeam();
      toast('Password reset. They were signed out everywhere');
      return null;
    } on ApiError catch (e) { return e.message; }
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    super.dispose();
  }

  void touch() => notifyListeners();

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  Future<void> _tick() async {
    await refreshCore();
    switch (section) {
      case Section.orders:
        await loadOrders();
      case Section.products:
        await loadProducts();
      case Section.approvals:
        await loadApprovals();
      case Section.connections:
        await loadConnections();
      case Section.team:
        await loadTeam();
      default:
        break;
    }
  }

  /// Data the nav badges and the inbox always need.
  Future<void> refreshCore() async {
    try {
      final r = await api.get('/api/conversations');
      convs = (r['items'] as List).cast<J>().map((e) => Map<String, dynamic>.from(e)).toList();
      if (convId != null) await loadConversation(convId!, silent: true);
      final a = await api.get('/api/approvals', q: {'status': apprStatus});
      approvals = (a['items'] as List).cast<J>();
      pendingApprovals = a['pending'] as int;
      draftsWaiting = a['drafts'] as int;
      final o = await api.get('/api/orders');
      orders = (o['items'] as List).cast<J>();
      offline = false;
    } on ApiError catch (e) {
      if (e.status == null) offline = true;
    }
    _notify();
  }

  // ---------------------------------------------------------------- ui state
  void setSection(Section s) {
    if (section == s) return;
    section = s;
    showMobileThread = false;
    notifyListeners();
    _loadFor(s);
  }

  Future<void> _loadFor(Section s) async {
    switch (s) {
      case Section.approvals:
        await loadApprovals();
      case Section.orders:
        await loadOrders();
      case Section.products:
        await loadProducts();
      case Section.customers:
        await loadCustomers();
      case Section.insights:
        await loadInsights();
      case Section.connections:
        await loadConnections();
      case Section.assistant:
        await loadSettings();
      case Section.team:
        await loadTeam();
      case Section.business:
        await loadBusiness();
      case Section.setup:
        await loadOnboarding();
      case Section.inbox:
        break;
    }
  }

  void toggleTheme() {
    themeMode = themeMode == ThemeMode.dark ? ThemeMode.light : ThemeMode.dark;
    notifyListeners();
  }

  Future<void> toast(String text, {bool error = false}) async {
    toastText = text;
    toastError = error;
    final id = ++_toastId;
    _notify();
    await Future<void>.delayed(const Duration(milliseconds: 2800));
    if (id == _toastId) {
      toastText = null;
      _notify();
    }
  }

  Future<T?> guard<T>(Future<T> Function() f) async {
    try {
      return await f();
    } on ApiError catch (e) {
      toast(e.message, error: true);
      return null;
    }
  }

  // ---------------------------------------------------------------- inbox
  List<J> get visibleConvs {
    return convs.where((c) {
      final needs = c['mode'] != 'agent' && c['status'] != 'resolved';
      final agent = c['mode'] == 'agent' && c['status'] != 'resolved';
      if (convTab == 'needs' && !needs) return false;
      if (convTab == 'assistant' && !agent) return false;
      if (channelFilter != 'all' && c['channel']['kind'] != channelFilter) return false;
      if (query.isNotEmpty) {
        final hay = '${c['customer']['name']} ${c['preview']} ${c['channel']['handle']}'.toLowerCase();
        if (!hay.contains(query.toLowerCase())) return false;
      }
      return true;
    }).toList();
  }

  int get needsCount => convs.where((c) => c['mode'] != 'agent' && c['status'] != 'resolved').length;
  int get assistantCount => convs.where((c) => c['mode'] == 'agent' && c['status'] != 'resolved').length;
  int get unreadCount => convs.where((c) => (c['unread'] as int) > 0).length;
  int get toShip => orders.where((o) => o['fulfillment'] == 'Unfulfilled' && o['payment']['status'] != 'Failed').length;

  void setConvTab(String t) { convTab = t; notifyListeners(); }
  void setChannelFilter(String t) { channelFilter = t; notifyListeners(); }
  void setQuery(String q) { query = q; notifyListeners(); }

  Future<void> selectConversation(String id, {bool openThread = true}) async {
    convId = id;
    if (openThread) showMobileThread = true;
    conv = null;
    notifyListeners();
    await loadConversation(id);
    final c = convs.where((x) => x['id'] == id);
    if (c.isNotEmpty && (c.first['unread'] as int) > 0) {
      api.post('/api/conversations/$id/read');
    }
  }

  void closeThread() { showMobileThread = false; notifyListeners(); }

  Future<void> loadConversation(String id, {bool silent = false}) async {
    try {
      final d = await api.get('/api/conversations/$id');
      if (convId == id) conv = d;
      if (!silent) _notify();
    } on ApiError catch (_) {}
  }

  Future<void> sendMessage(String text, {bool internal = false}) async {
    final id = convId;
    if (id == null) return;
    final r = await guard(() => api.post('/api/conversations/$id/messages', {'text': text, 'internal': internal}));
    if (r != null) {
      if (internal) toast('Note added');
      final d = r['delivery'] as String?;
      if (d != null && d.startsWith('Failed')) toast(d, error: true);
      await refreshCore();
    }
  }

  /// Approved WhatsApp templates for the open conversation (demo ones on a demo channel).
  Future<List<J>> templates() async {
    final id = convId;
    if (id == null) return [];
    try {
      final r = await api.get('/api/conversations/$id/templates');
      return (r['items'] as List).cast<J>();
    } on ApiError catch (e) {
      toast(e.message, error: true);
      return [];
    }
  }

  Future<bool> sendTemplate(String name, String language, List<String> params) async {
    final id = convId;
    if (id == null) return false;
    final r = await guard(() => api.post('/api/conversations/$id/template', {'name': name, 'language': language, 'params': params}));
    if (r != null) { toast('Template sent'); await refreshCore(); return true; }
    return false;
  }

  Future<void> setMode(String mode) async {
    final id = convId;
    if (id == null) return;
    await guard(() => api.post('/api/conversations/$id/mode', {'mode': mode}));
    toast(mode == 'agent' ? 'Assistant is replying again' : mode == 'hybrid' ? 'Assistant drafts, you approve' : 'You are replying. The assistant is paused');
    await refreshCore();
  }

  Future<void> resolve(bool on) async {
    final id = convId;
    if (id == null) return;
    await guard(() => api.post('/api/conversations/$id/resolve', {'on': on}));
    toast(on ? 'Conversation resolved' : 'Conversation reopened');
    await refreshCore();
  }

  Future<void> approveDraft({String? text}) async {
    final id = convId;
    if (id == null) return;
    final c = conv;
    final r = await guard(() => api.post('/api/conversations/$id/draft/approve', text == null ? {} : {'text': text}));
    if (r != null) {
      toast('Sent to ${(c?['customer']['name'] as String? ?? '').split(' ').first} on ${c?['channel']['name'] == 'Facebook Page' ? 'Messenger' : c?['channel']['name']}');
      await refreshCore();
    }
  }

  Future<void> dismissDraft() async {
    final id = convId;
    if (id == null) return;
    await guard(() => api.post('/api/conversations/$id/draft/dismiss'));
    toast('Draft dismissed');
    await refreshCore();
  }

  Future<String?> simulate({required String channel, required String name, required String text, String? phone}) async {
    final r = await guard(() => api.post('/api/simulate', {'channel': channel, 'name': name, 'text': text, if (phone != null && phone.isNotEmpty) 'phone': phone}));
    await refreshCore();
    return r?['conversationId'] as String?;
  }

  // ---------------------------------------------------------------- approvals
  Future<void> loadApprovals() async {
    try {
      final a = await api.get('/api/approvals', q: {'status': apprStatus});
      approvals = (a['items'] as List).cast<J>();
      pendingApprovals = a['pending'] as int;
      draftsWaiting = a['drafts'] as int;
      _notify();
    } on ApiError catch (_) {}
  }

  void setApprStatus(String s) { apprStatus = s; apprId = null; notifyListeners(); loadApprovals(); }
  void selectApproval(int? id) { apprId = id; notifyListeners(); }

  Future<void> decide(int id, String decision) async {
    final r = await guard(() => api.post('/api/approvals/$id/decide', {'decision': decision}));
    if (r != null) {
      toast(decision == 'approved' ? 'Approved. The customer has been notified' : 'Rejected. A reason was sent to the customer');
      apprId = null;
      await loadApprovals();
      await refreshCore();
    }
  }

  // ---------------------------------------------------------------- orders
  Future<void> loadOrders() async {
    try {
      final o = await api.get('/api/orders');
      orders = (o['items'] as List).cast<J>();
      _notify();
    } on ApiError catch (_) {}
  }

  Future<J> quoteOrder(List<J> lines, String zone, int? shipping) => _try(() => api.post('/api/orders/quote', {'lines': lines, 'zone': zone, 'shipping': shipping}));

  Future<J> createOrder(J body) => _try(() async {
        final r = await api.post('/api/orders', body);
        await Future.wait([loadOrders(), loadProducts(), loadCustomers(), refreshCore()]);
        return r;
      });

  void setOrderTab(String t) { orderTab = t; notifyListeners(); }
  void setOrderQuery(String q) { orderQuery = q; notifyListeners(); }
  void selectOrder(String? no) { orderNo = no; notifyListeners(); }

  List<J> get visibleOrders => orders.where((o) {
        final pay = o['payment']['status'];
        final issue = o['returnRequested'] == true || pay == 'Failed' || pay == 'Pending';
        switch (orderTab) {
          case 'unful': if (o['fulfillment'] != 'Unfulfilled') return false;
          case 'transit': if (o['fulfillment'] != 'In transit') return false;
          case 'done': if (o['fulfillment'] != 'Delivered') return false;
          case 'issue': if (!issue) return false;
        }
        if (orderQuery.isNotEmpty && !('${o['number']} ${o['customer']['name']} ${o['site']?['number'] ?? ''}'.toLowerCase().contains(orderQuery.toLowerCase()))) return false;
        return true;
      }).toList();

  Future<List<J>> rates(String no) async {
    final r = await api.get('/api/orders/${Uri.encodeComponent(no)}/rates');
    return (r['rates'] as List).cast<J>();
  }

  // ---------------------------------------------------------------- real couriers and payments
  Future<J> _try(Future<J> Function() f) async {
    try {
      return await f();
    } on ApiError catch (e) {
      return {'error': e.message};
    }
  }

  String _o(String no) => Uri.encodeComponent(no);

  Future<J> orderRates(String no) => _try(() => api.get('/api/orders/${_o(no)}/rates'));

  Future<J> shipOrder(String no, String courier, int? expectedCod) => _try(() async {
        final r = await api.post('/api/orders/${_o(no)}/ship', {'courier': courier, if (expectedCod != null) 'expectedCod': expectedCod});
        await loadOrders();
        return r;
      });

  Future<J> trackOrder(String no) => _try(() async {
        final r = await api.post('/api/orders/${_o(no)}/track');
        await loadOrders();
        return r;
      });

  Future<J> createPaymentLink(String no, String provider, bool sendInChat) => _try(() async {
        final r = await api.post('/api/orders/${_o(no)}/payment-link', {'provider': provider, 'sendInChat': sendInChat});
        await loadOrders();
        return r;
      });

  Future<J> refreshPayment(String id) => _try(() async {
        final r = await api.post('/api/payments/$id/refresh');
        await loadOrders();
        return r;
      });

  Future<J> refundOrder(String no, {int? amount, String reason = 'Refund', bool manual = false}) => _try(() async {
        final r = await api.post('/api/orders/${_o(no)}/refund', {if (amount != null) 'amount': amount, 'reason': reason, 'manual': manual});
        await loadOrders();
        return r;
      });

  Future<J> checkRefund(String id) => _try(() async {
        final r = await api.post('/api/refunds/$id/check');
        await loadOrders();
        return r;
      });

  // ---------------------------------------------------------------- websites that products are imported from
  List<J> catalogSources = [];

  Future<void> loadCatalogSources() async {
    try {
      final r = await api.get('/api/catalog/sources');
      catalogSources = (r['items'] as List).cast<J>();
      _notify();
    } on ApiError catch (_) {}
  }

  Future<J> discoverSite(String url) => _try(() => api.post('/api/catalog/discover', {'url': url}));

  Future<J> importSite(String url, int defaultStock, bool confirmCurrency) => _try(() async {
        final r = await api.post('/api/catalog/import', {'url': url, 'defaultStock': defaultStock, 'confirmCurrency': confirmCurrency});
        await Future.wait([loadProducts(), loadCatalogSources()]);
        return r;
      });

  Future<J> syncSite(String id) => _try(() async {
        final r = await api.post('/api/catalog/sources/$id/sync', {});
        await Future.wait([loadProducts(), loadCatalogSources()]);
        return r;
      });

  Future<J> ordersSetup(String id) => _try(() => api.get('/api/catalog/sources/$id/orders'));

  Future<J> saveOrdersSetup(String id, J body) => _try(() async {
        final r = await api.put('/api/catalog/sources/$id/orders', body);
        await loadCatalogSources();
        return r;
      });

  Future<J> newOrdersSecret(String id) => _try(() => api.post('/api/catalog/sources/$id/orders/secret', {}));

  Future<J> disconnectSite(String id) => _try(() async {
        final r = await api.delete('/api/catalog/sources/$id');
        await loadCatalogSources();
        return r;
      });

  // ---------------------------------------------------------------- courier and payment providers
  List<J> providers = [];

  Future<void> loadProviders() async {
    try {
      final r = await api.get('/api/providers');
      providers = (r['items'] as List).cast<J>();
      _notify();
    } on ApiError catch (_) {}
  }

  Future<J> connectProvider(String id, J body) => _try(() async {
        final r = await api.post('/api/providers/$id/connect', body);
        await loadProviders();
        return r;
      });

  Future<J> checkProvider(String id) => _try(() async {
        final r = await api.post('/api/providers/$id/check');
        await loadProviders();
        return r;
      });

  Future<J> disconnectProvider(String id) => _try(() async {
        final r = await api.delete('/api/providers/$id');
        await loadProviders();
        return r;
      });

  // ---------------------------------------------------------------- SMS
  J sms = {};

  Future<void> loadSms() async {
    try {
      sms = await api.get('/api/sms');
      _notify();
    } on ApiError catch (_) {}
  }

  Future<J> testSms(String id, String to) => _try(() async {
        final r = await api.post('/api/providers/$id/test-sms', {'to': to});
        await loadProviders();
        await loadSms();
        return r;
      });

  Future<J> saveSmsSettings(J body) => _try(() async {
        final r = await api.put('/api/sms/settings', body);
        await loadSms();
        return r;
      });

  Future<J> resendSms(String id) => _try(() async {
        final r = await api.post('/api/sms/$id/resend');
        await loadSms();
        await loadOrders();
        return r;
      });

  List<J> get liveProviders => providers.where((p) => p['live'] == true && p['kind'] == 'payment' && p['status'] == 'ok').toList();

  Future<void> orderAction(String no, String action, {String success = 'Done', Object? body}) async {
    final r = await guard(() => api.post('/api/orders/${Uri.encodeComponent(no)}/$action', body));
    if (r != null) { toast(success); await loadOrders(); }
  }

  // ---------------------------------------------------------------- products & customers
  Future<void> loadProducts() async {
    try {
      final r = await api.get('/api/products');
      products = (r['items'] as List).cast<J>();
      _notify();
    } on ApiError catch (_) {}
  }

  void setProductTab(String t) { productTab = t; notifyListeners(); }
  void setProductQuery(String q) { productQuery = q; notifyListeners(); }

  Future<J> saveProduct(J body, {String? sku}) => _try(() async {
        final r = sku == null ? await api.post('/api/products', body) : await api.put('/api/products/${Uri.encodeComponent(sku)}', body);
        await loadProducts();
        return r;
      });

  Future<J> deleteProduct(String sku) => _try(() async {
        final r = await api.delete('/api/products/${Uri.encodeComponent(sku)}');
        await loadProducts();
        return r;
      });

  Future<void> adjustStock(String sku, int delta) async {
    // optimistic
    final p = products.firstWhere((p) => p['sku'] == sku);
    p['stock'] = ((p['stock'] as int) + delta).clamp(0, 100000);
    notifyListeners();
    await guard(() => api.post('/api/products/$sku/stock', {'delta': delta}));
  }

  Future<void> loadCustomers() async {
    try {
      final r = await api.get('/api/customers');
      customers = (r['items'] as List).cast<J>();
      _notify();
    } on ApiError catch (_) {}
  }

  void setCustomerQuery(String q) { customerQuery = q; notifyListeners(); }

  // ---------------------------------------------------------------- insights, connections, assistant
  Future<void> loadInsights() async {
    try { insights = await api.get('/api/insights'); _notify(); } on ApiError catch (_) {}
  }

  Future<void> loadConnections() async {
    try {
      final c = await api.get('/api/channels');
      channels = (c['items'] as List).cast<J>();
      channelsMeta = c;
      if (can('connections.write') || metaApp.isEmpty) { loadMeta(); }
      loadProviders();
      loadCatalogSources();
      final i = await api.get('/api/integrations');
      integrations = (i['items'] as List).cast<J>();
      notifications = (i['notifications'] as List).cast<J>();
      _notify();
    } on ApiError catch (_) {}
  }

  // ---------------------------------------------------------------- Meta app and channels
  J metaApp = {};
  List<J> webhookLog = [];

  Future<void> loadMeta() async {
    try {
      metaApp = await api.get('/api/meta');
      if (can('connections.write')) {
        final d = await api.get('/api/meta/diagnostics');
        webhookLog = (d['items'] as List).cast<J>();
      }
      _notify();
    } on ApiError catch (_) {}
  }

  /// Returns an error message, or null on success.
  Future<String?> saveMetaApp(J body) async {
    try {
      metaApp = await api.put('/api/meta', body);
      _notify();
      return null;
    } on ApiError catch (e) { return e.message; }
  }

  Future<String?> newVerifyToken() async {
    try {
      final r = await api.post('/api/meta/verify-token');
      metaApp['verifyToken'] = r['verifyToken'];
      metaApp['verifyTokenSet'] = true;
      _notify();
      return r['verifyToken'] as String;
    } on ApiError catch (_) { return null; }
  }

  /// Connect a real account. Returns the server's answer, or {'error': message}.
  Future<J> connectChannel(J body) async {
    try {
      final r = await api.post('/api/channels', body);
      await loadConnections();
      return r;
    } on ApiError catch (e) { return {'error': e.message}; }
  }

  Future<J> channelAction(String id, String action) async {
    try {
      final r = await api.post('/api/channels/$id/$action');
      await loadConnections();
      return r;
    } on ApiError catch (e) { return {'error': e.message}; }
  }

  Future<J> updateChannel(String id, J patch) async {
    try {
      final r = await api.patch('/api/channels/$id', patch);
      await loadConnections();
      return r;
    } on ApiError catch (e) { return {'error': e.message}; }
  }

  Future<bool> disconnectChannel(String id) async {
    try {
      await api.delete('/api/channels/$id');
      await loadConnections();
      toast('Channel disconnected');
      return true;
    } on ApiError catch (e) { toast(e.message, error: true); return false; }
  }

  Future<void> setIntegration(String id, bool on) async {
    await guard(() => api.post('/api/integrations/$id', {'status': on ? 'ok' : 'off'}));
    await loadConnections();
  }

  Future<void> saveNotifications() async {
    await guard(() => api.put('/api/notifications', {'rows': notifications}));
  }

  // ---------------------------------------------------------------- the AI provider and its key (owner panel)
  void _engineChanged(J r) {
    if (r['engine'] != null) { me = {...me, 'engine': r['engine'], 'engineLabel': r['engineLabel'], 'model': r['engine'] != 'offline' ? r['model'] : null}; }
    if (settings != null) { settings = {...settings!, 'engine': r['engine'], 'engineLabel': r['engineLabel'], 'model': r['model'], 'keySource': r['source']}; }
    _notify();
  }

  Future<J> planInfo() => _try(() => api.get('/api/plan'));

  Future<J> aiKeyInfo() => _try(() => api.get('/api/assistant/key'));

  Future<J> saveAiKey(String provider, String key, {String? model, String? smallModel, String? baseUrl, bool skipCheck = false}) => _try(() async {
        final r = await api.put('/api/assistant/key', {'provider': provider, 'key': key, 'model': model, 'smallModel': smallModel, 'baseUrl': baseUrl, 'skipCheck': skipCheck});
        _engineChanged(r);
        return r;
      });

  Future<J> setAiProvider(String provider, {String? model, String? smallModel, String? baseUrl}) => _try(() async {
        final r = await api.put('/api/assistant/provider', {'provider': provider, 'model': model, 'smallModel': smallModel, 'baseUrl': baseUrl});
        _engineChanged(r);
        return r;
      });

  Future<J> checkAiKey(String provider) => _try(() => api.post('/api/assistant/key/check?provider=$provider', {}));

  Future<J> removeAiKey(String provider) => _try(() async {
        final r = await api.delete('/api/assistant/key?provider=$provider');
        _engineChanged(r);
        return r;
      });

  Future<void> loadSettings() async {
    try { settings = await api.get('/api/settings'); _notify(); } on ApiError catch (_) {}
  }

  Future<void> saveSettings(J patch) async {
    final cur = Map<String, dynamic>.from(settings!['agent'] as Map);
    patch.forEach((k, v) => cur[k] = v);
    settings!['agent'] = cur;
    notifyListeners();
    await guard(() => api.put('/api/settings', patch));
  }

  Future<void> savePolicy(String key, String title, String body) async {
    final r = await guard(() => api.put('/api/policies/$key', {'title': title, 'body': body}));
    if (r != null) { toast('Policy saved. The assistant uses it right away'); await loadSettings(); }
  }
}
