import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

import '../models/models.dart';
import 'stores.dart';

class Session {
  final String accessToken;
  final String refreshToken;
  final String username;
  final String fullName;
  final String collectorCode;
  const Session({
    required this.accessToken,
    required this.refreshToken,
    required this.username,
    required this.fullName,
    required this.collectorCode,
  });
}

/// Tokens are kept in the platform keystore, never in plain preferences.
class SessionStore {
  static const _s = FlutterSecureStorage();
  static const _keys = ['access', 'refresh', 'username', 'full_name', 'collector_code'];

  Future<Session?> load() async {
    final v = {for (final k in _keys) k: await _s.read(key: k)};
    if (v['access'] == null || v['refresh'] == null || v['collector_code'] == null) return null;
    return Session(
      accessToken: v['access']!,
      refreshToken: v['refresh']!,
      username: v['username'] ?? '',
      fullName: v['full_name'] ?? '',
      collectorCode: v['collector_code']!,
    );
  }

  Future<void> save(Session s) async {
    await _s.write(key: 'access', value: s.accessToken);
    await _s.write(key: 'refresh', value: s.refreshToken);
    await _s.write(key: 'username', value: s.username);
    await _s.write(key: 'full_name', value: s.fullName);
    await _s.write(key: 'collector_code', value: s.collectorCode);
  }

  Future<void> updateTokens(String access, String refresh) async {
    await _s.write(key: 'access', value: access);
    await _s.write(key: 'refresh', value: refresh);
  }

  /// Logging out removes tokens only. Unsynced payments and downloaded customers stay on the phone.
  Future<void> clearTokens() async {
    await _s.delete(key: 'access');
    await _s.delete(key: 'refresh');
  }
}

class ApiClient implements RemoteApi {
  final String baseUrl; // e.g. https://billing.example.com  (no trailing slash)
  final SessionStore sessions;
  final http.Client _http;
  Session? session;

  ApiClient({required this.baseUrl, required this.sessions, http.Client? client, this.session})
      : _http = client ?? http.Client();

  static const _timeout = Duration(seconds: 25);

  Uri _u(String path, [Map<String, String>? q]) =>
      Uri.parse('$baseUrl/api/v1$path').replace(queryParameters: q);

  Map<String, String> get _auth => {
        'Content-Type': 'application/json',
        if (session != null) 'Authorization': 'Bearer ${session!.accessToken}',
      };

  Future<http.Response> _send(Future<http.Response> Function() call) async {
    try {
      return await call().timeout(_timeout);
    } on SocketException {
      throw OfflineException();
    } on TimeoutException {
      throw OfflineException('The server did not answer in time');
    } on http.ClientException {
      throw OfflineException();
    } on HandshakeException {
      throw OfflineException('Could not make a secure connection');
    }
  }

  /// Calls the API; on 401 refreshes the token once and retries.
  Future<http.Response> _authed(Future<http.Response> Function() call) async {
    var r = await _send(call);
    if (r.statusCode == 401 && session != null) {
      if (await _refresh()) r = await _send(call);
      if (r.statusCode == 401) throw SessionExpiredException();
    }
    return r;
  }

  Future<bool> _refresh() async {
    final s = session;
    if (s == null) return false;
    try {
      final r = await _send(() => _http.post(_u('/auth/refresh'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'refresh_token': s.refreshToken})));
      if (r.statusCode != 200) return false;
      final j = jsonDecode(r.body) as Map<String, dynamic>;
      session = Session(
        accessToken: j['access_token'] as String,
        refreshToken: (j['refresh_token'] as String?) ?? s.refreshToken,
        username: s.username,
        fullName: s.fullName,
        collectorCode: s.collectorCode,
      );
      await sessions.updateTokens(session!.accessToken, session!.refreshToken);
      return true;
    } on OfflineException {
      rethrow;
    }
  }

  Never _fail(http.Response r) {
    var msg = 'Server error (${r.statusCode})';
    try {
      final j = jsonDecode(r.body);
      if (j is Map && j['detail'] is String) msg = j['detail'] as String;
    } catch (_) {}
    throw ApiException(r.statusCode, msg);
  }

  Future<Session> login(String username, String password) async {
    final r = await _send(() => _http.post(_u('/auth/login'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'username': username.trim(), 'password': password})));
    if (r.statusCode == 401 || r.statusCode == 403) {
      throw ApiException(r.statusCode, 'Wrong username or password');
    }
    if (r.statusCode != 200) _fail(r);
    final t = jsonDecode(r.body) as Map<String, dynamic>;
    session = Session(
        accessToken: t['access_token'] as String,
        refreshToken: t['refresh_token'] as String,
        username: username.trim(),
        fullName: '',
        collectorCode: '');

    final me = await _authed(() => _http.get(_u('/auth/me'), headers: _auth));
    if (me.statusCode != 200) _fail(me);
    final mj = jsonDecode(me.body) as Map<String, dynamic>;
    final col = await _authed(() => _http.get(_u('/collectors/me'), headers: _auth));
    if (col.statusCode == 404) {
      session = null;
      throw ApiException(403, 'This account is not a collector. Ask the office to set you up.');
    }
    if (col.statusCode != 200) _fail(col);
    final cj = jsonDecode(col.body) as Map<String, dynamic>;
    session = Session(
        accessToken: session!.accessToken,
        refreshToken: session!.refreshToken,
        username: mj['username'] as String,
        fullName: mj['full_name'] as String,
        collectorCode: cj['code'] as String);
    await sessions.save(session!);
    return session!;
  }

  @override
  Future<SnapshotPage> fetchSnapshot({required int offset, required int limit}) async {
    final r = await _authed(() => _http.get(
        _u('/collector/snapshot', {'offset': '$offset', 'limit': '$limit'}),
        headers: _auth));
    if (r.statusCode != 200) _fail(r);
    return SnapshotPage.fromJson(jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>);
  }

  @override
  Future<List<SyncResult>> syncPayments(List<QueuedPayment> batch) async {
    final body = jsonEncode({'payments': batch.map((p) => p.toSyncJson()).toList()});
    final r = await _authed(() => _http.post(_u('/collector/payments/sync'),
        headers: _auth, body: body));
    if (r.statusCode >= 500) {
      // The server may or may not have stored them. Nothing is marked: they are simply re-sent
      // later, and the server de-duplicates by client transaction id.
      throw OfflineException('Server is having a problem, will retry');
    }
    if (r.statusCode != 200) _fail(r);
    final j = jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
    return (j['results'] as List).map((e) => SyncResult.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Totals the server holds for a day (for comparing with the phone's own numbers).
  Future<Map<String, dynamic>> serverSummary(String isoDate) async {
    final r = await _authed(
        () => _http.get(_u('/collector/summary', {'day': isoDate}), headers: _auth));
    if (r.statusCode != 200) _fail(r);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }
}
