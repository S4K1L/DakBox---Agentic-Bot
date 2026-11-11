import 'package:intl/intl.dart';

/// Taka with lakh grouping: 1,450 and 8,43,160.
String taka(num n) {
  final neg = n < 0;
  final s = n.abs().round().toString();
  final last3 = s.length > 3 ? s.substring(s.length - 3) : s;
  var rest = s.length > 3 ? s.substring(0, s.length - 3) : '';
  if (rest.isNotEmpty) {
    rest = rest.replaceAllMapped(RegExp(r'\B(?=(\d{2})+(?!\d))'), (_) => ',');
    rest = '$rest,';
  }
  return '${neg ? '-' : ''}৳$rest$last3';
}

DateTime? ts(String? iso) => iso == null ? null : DateTime.tryParse(iso)?.toLocal();

bool _sameDay(DateTime a, DateTime b) => a.year == b.year && a.month == b.month && a.day == b.day;

String clock(String? iso) {
  final d = ts(iso);
  return d == null ? '' : DateFormat('HH:mm').format(d);
}

/// 10:43 today, Yesterday, Sun, or 8 Nov.
String listTime(String? iso) {
  final d = ts(iso);
  if (d == null) return '';
  final now = DateTime.now();
  if (_sameDay(d, now)) return DateFormat('HH:mm').format(d);
  if (_sameDay(d, now.subtract(const Duration(days: 1)))) return 'Yesterday';
  if (now.difference(d).inDays < 6) return DateFormat('EEE').format(d);
  return DateFormat('d MMM').format(d);
}

String dayLabel(String? iso) {
  final d = ts(iso);
  if (d == null) return '';
  final now = DateTime.now();
  if (_sameDay(d, now)) return 'Today';
  if (_sameDay(d, now.subtract(const Duration(days: 1)))) return 'Yesterday';
  return DateFormat('EEE d MMM').format(d);
}

String dateTime(String? iso) {
  final d = ts(iso);
  if (d == null) return '';
  final now = DateTime.now();
  final t = DateFormat('HH:mm').format(d);
  if (_sameDay(d, now)) return 'Today $t';
  return '${DateFormat('d MMM').format(d)} $t';
}

String shortDate(String? iso) {
  final d = ts(iso);
  return d == null ? '—' : DateFormat('d MMM').format(d);
}

String monthYear(String? iso) {
  final d = ts(iso);
  return d == null ? '' : DateFormat('MMM yyyy').format(d);
}

String relative(String? iso) {
  final d = ts(iso);
  if (d == null) return '';
  final diff = DateTime.now().difference(d);
  if (diff.inSeconds < 60) return 'just now';
  if (diff.inMinutes < 60) return '${diff.inMinutes} min ago';
  if (diff.inHours < 24) return '${diff.inHours}h ago';
  return '${diff.inDays}d ago';
}

/// "21h 14m left" for a messaging window.
String windowLeft(String? iso) {
  final d = ts(iso);
  if (d == null) return 'Window closed';
  final left = d.difference(DateTime.now());
  if (left.isNegative) return 'Window closed';
  return '${left.inHours}h ${left.inMinutes % 60}m left';
}

/// Deadline text and tone for approvals.
({String text, String tone}) due(String? iso) {
  final d = ts(iso);
  if (d == null) return (text: '', tone: '');
  final diff = d.difference(DateTime.now());
  if (diff.isNegative) {
    final h = diff.abs().inHours;
    return (text: h < 1 ? 'Overdue' : 'Overdue ${h}h', tone: 'danger');
  }
  if (diff.inHours < 12) return (text: 'Due in ${diff.inHours < 1 ? '<1' : diff.inHours}h', tone: 'warn');
  if (diff.inHours < 36) return (text: 'Due tomorrow', tone: '');
  return (text: 'Due in ${diff.inDays}d', tone: '');
}

String plural(int n, String one, [String? many]) => '$n ${n == 1 ? one : (many ?? '${one}s')}';
