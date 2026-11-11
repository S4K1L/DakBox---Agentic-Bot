import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

typedef J = Map<String, dynamic>;

class ApiError implements Exception {
  ApiError(this.message, {this.status});
  final String message;
  final int? status;
  @override
  String toString() => message;
}

/// Where the FastAPI backend lives. Override with --dart-define=API_BASE=https://...
String defaultApiBase() {
  const fromEnv = String.fromEnvironment('API_BASE');
  if (fromEnv.isNotEmpty) return fromEnv;
  if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android)
    return 'http://10.0.2.2:8000';
  if (kIsWeb) {
    // Dev: the app is served from another local port and the API is on :8000.
    // Deployed: the backend serves the app, so the API is the same origin.
    final u = Uri.base;
    final given = u.queryParameters['api'];   // e.g. http://localhost:4000/?api=http://localhost:4000
    if (given != null && RegExp(r'^https?://(localhost|127\.0\.0\.1)(:\d+)?$').hasMatch(given)) return given;
    final local = u.host == 'localhost' || u.host == '127.0.0.1';
    return local && u.port != 8000 ? '${u.scheme}://${u.host}:8000' : u.origin;
  }
  return 'http://localhost:8000';
}

class Api {
  Api([String? base])
    : base = base ?? defaultApiBase(),
      _d = Dio(
        BaseOptions(
          baseUrl: base ?? defaultApiBase(),
          connectTimeout: const Duration(seconds: 8),
          receiveTimeout: const Duration(seconds: 25),
        ),
      );

  final String base;
  final Dio _d;

  /// Bearer token for the signed-in user. Set by AppState after sign-in.
  String? token;

  /// Called when the server says the session is no longer valid (401 on anything but the sign-in calls).
  void Function()? onUnauthorized;

  Future<J> _wrap(Future<Response<dynamic>> f, {bool auth = true}) async {
    try {
      final r = await f;
      final d = r.data;
      return d is Map ? Map<String, dynamic>.from(d) : <String, dynamic>{};
    } on DioException catch (e) {
      final d = e.response?.data;
      final msg = d is Map
          ? (d['error'] ?? d['detail'] ?? 'Request failed').toString()
          : (e.type == DioExceptionType.connectionError
                ? 'Cannot reach the Dakbox server'
                : (e.message ?? 'Request failed'));
      if (e.response?.statusCode == 401 && auth && token != null)
        onUnauthorized?.call();
      throw ApiError(msg, status: e.response?.statusCode);
    }
  }

  Options get _opts => Options(
    headers: token == null ? null : {'Authorization': 'Bearer $token'},
  );

  Future<J> get(String path, {Map<String, dynamic>? q}) =>
      _wrap(_d.get(path, queryParameters: q, options: _opts));
  Future<J> post(String path, [Object? body]) =>
      _wrap(_d.post(path, data: body ?? <String, dynamic>{}, options: _opts));
  Future<J> put(String path, Object body) =>
      _wrap(_d.put(path, data: body, options: _opts));
  Future<J> delete(String path) => _wrap(_d.delete(path, options: _opts));
  Future<J> patch(String path, Object body) =>
      _wrap(_d.patch(path, data: body, options: _opts));

  /// Sign-in style calls: a 401 here means wrong credentials, not an expired session.
  Future<J> postPublic(String path, Object body) =>
      _wrap(_d.post(path, data: body), auth: false);
  Future<J> getPublic(String path) => _wrap(_d.get(path), auth: false);
}
