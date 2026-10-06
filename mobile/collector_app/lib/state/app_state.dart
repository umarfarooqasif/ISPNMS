import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../data/api_client.dart';
import '../data/local_db.dart';
import '../data/stores.dart';
import '../data/sync_service.dart';
import '../models/models.dart';
import '../models/money.dart';

class AppState extends ChangeNotifier {
  late final LocalDb db;
  late final SessionStore _sessions;
  late ApiClient api;
  late SyncService sync;

  String serverUrl = '';
  Session? session;
  bool ready = false;

  // Shown on the sync screen / home banner.
  bool syncing = false;
  String? lastSyncMessage;
  bool lastSyncProblem = false;
  DateTime? lastDownload;
  int customerCount = 0;
  int pending = 0;
  int rejected = 0;

  StreamSubscription<List<ConnectivityResult>>? _net;
  bool _wasOffline = false;

  Future<void> init({LocalDb? testDb}) async {
    final prefs = await SharedPreferences.getInstance();
    serverUrl = prefs.getString('server_url') ?? '';
    db = testDb ?? await LocalDb.open();
    _sessions = SessionStore();
    session = await _sessions.load();
    _rebuildApi();
    await refreshCounts();
    ready = true;
    notifyListeners();

    // When signal comes back, send what was collected offline (silently, nothing to confirm).
    _net = Connectivity().onConnectivityChanged.listen((r) {
      final offline = r.isEmpty || r.every((e) => e == ConnectivityResult.none);
      if (_wasOffline && !offline && loggedIn) {
        unawaited(syncNow(download: false));
      }
      _wasOffline = offline;
    });
  }

  bool get loggedIn => session != null;
  String get collectorCode => session?.collectorCode ?? '';

  void _rebuildApi() {
    api = ApiClient(baseUrl: serverUrl, sessions: _sessions, session: session);
    sync = SyncService(payments: db, customers: db, api: api);
  }

  Future<void> setServerUrl(String url) async {
    var u = url.trim();
    while (u.endsWith('/')) {
      u = u.substring(0, u.length - 1);
    }
    serverUrl = u;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('server_url', u);
    _rebuildApi();
    notifyListeners();
  }

  Future<void> login(String username, String password) async {
    if (serverUrl.isEmpty) throw ApiException(0, 'Enter the server address first');
    session = await api.login(username, password);
    _rebuildApi();
    notifyListeners();
    // First login on this phone: download the customers straight away if there is signal.
    if (await db.customerCount() == 0) {
      await syncNow();
    }
  }

  /// Logging out never deletes unsynced payments or the customer list.
  Future<void> logout() async {
    await _sessions.clearTokens();
    session = null;
    _rebuildApi();
    notifyListeners();
  }

  Future<void> refreshCounts() async {
    final c = await db.counts();
    pending = c[PaymentState.pending] ?? 0;
    rejected = c[PaymentState.rejected] ?? 0;
    customerCount = await db.customerCount();
    lastDownload = await db.lastDownload();
    notifyListeners();
  }

  /// Sends pending payments, then (optionally) refreshes the customer list.
  Future<void> syncNow({bool download = true}) async {
    if (syncing || !loggedIn) return;
    syncing = true;
    lastSyncProblem = false;
    notifyListeners();
    try {
      final report = download ? await sync.fullSync() : await sync.uploadPending();
      if (report.offline) {
        lastSyncMessage = 'No internet. Nothing was lost; ${await _pendingText()}';
        lastSyncProblem = true;
      } else {
        final parts = <String>[];
        if (report.uploaded > 0) parts.add('${report.uploaded} payment(s) uploaded');
        if (report.rejected > 0) {
          parts.add('${report.rejected} rejected: hand the cash to the office');
          lastSyncProblem = true;
        }
        if (report.retry > 0) {
          parts.add('${report.retry} will be retried');
          lastSyncProblem = true;
        }
        if (download) parts.add('customers updated');
        lastSyncMessage = parts.isEmpty ? 'Everything is up to date' : parts.join(', ');
      }
    } on OfflineException catch (e) {
      lastSyncMessage = '${e.message}. Nothing was lost.';
      lastSyncProblem = true;
    } on SessionExpiredException {
      lastSyncMessage = 'Your session expired. Log in again to sync (your payments are safe).';
      lastSyncProblem = true;
      session = null;
      _rebuildApi();
    } on ApiException catch (e) {
      lastSyncMessage = e.message;
      lastSyncProblem = true;
    } finally {
      syncing = false;
      await refreshCounts();
    }
  }

  Future<String> _pendingText() async {
    await refreshCounts();
    return '$pending payment(s) waiting to upload';
  }

  /// Records a collected payment on the phone (works with no signal) and returns it for the receipt.
  Future<QueuedPayment> collect({
    required Customer customer,
    required Money amount,
    required String method,
    String? connectionId,
    String? notes,
  }) async {
    final p = await db.addPayment(
      collectorCode: collectorCode,
      customer: customer,
      amount: amount,
      method: method,
      connectionId: connectionId,
      notes: notes,
    );
    await refreshCounts();
    // Try to upload right away; with no signal this quietly leaves it queued.
    unawaited(syncNow(download: false));
    return p;
  }

  @override
  void dispose() {
    _net?.cancel();
    super.dispose();
  }
}
