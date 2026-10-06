import '../models/models.dart';

/// Thrown when there is no usable network (airplane mode, no signal, server unreachable).
/// Nothing is lost: payments stay queued and everything is retried later.
class OfflineException implements Exception {
  final String message;
  OfflineException([this.message = 'No internet connection']);
  @override
  String toString() => message;
}

/// The server rejected our login (expired session). Local data is kept.
class SessionExpiredException implements Exception {
  @override
  String toString() => 'Session expired. Log in again to sync.';
}

class ApiException implements Exception {
  final int status;
  final String message;
  ApiException(this.status, this.message);
  @override
  String toString() => message;
}

/// Everything the sync logic needs from the server.
abstract class RemoteApi {
  Future<SnapshotPage> fetchSnapshot({required int offset, required int limit});
  Future<List<SyncResult>> syncPayments(List<QueuedPayment> batch);
}

/// Payment queue storage. Append-only by design: there is no delete and no edit of amounts.
abstract class PaymentStore {
  Future<List<QueuedPayment>> pendingPayments({int limit = 50});
  Future<void> markSynced(String clientTxnId, {String? serverReceiptNo, String? serverPaymentId});
  Future<void> markRejected(String clientTxnId, {String? code, String? reason});
  Future<void> recordFailedAttempt(String clientTxnId, String error);
}

abstract class CustomerStore {
  /// Replaces the whole downloaded customer list atomically (all or nothing).
  Future<void> replaceCustomers(List<Customer> customers, DateTime generatedAt);
}
