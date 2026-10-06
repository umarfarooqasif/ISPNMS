import 'dart:convert';

import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';
import 'package:uuid/uuid.dart';

import '../logic/receipt_number.dart';
import '../logic/search.dart';
import '../models/models.dart';
import '../models/money.dart';
import 'stores.dart';

/// All data kept on the phone. Payments live in an append-only table: this class offers no way to
/// delete a payment or change its amount, method, customer or time. Only the sync fields move.
class LocalDb implements PaymentStore, CustomerStore {
  final Database _db;
  LocalDb._(this._db);

  static const _uuid = Uuid();

  static Future<LocalDb> open({String? path}) async {
    final dbPath = path ?? p.join(await getDatabasesPath(), 'collector.db');
    final db = await openDatabase(dbPath, version: 1, onCreate: (db, v) async {
      await db.execute('''
        CREATE TABLE customers (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          search TEXT NOT NULL,
          json TEXT NOT NULL
        )''');
      await db.execute('CREATE INDEX idx_customers_name ON customers(name)');
      await db.execute('''
        CREATE TABLE payments (
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          client_txn_id TEXT NOT NULL UNIQUE,
          client_receipt_no TEXT NOT NULL UNIQUE,
          customer_id TEXT NOT NULL,
          customer_name TEXT NOT NULL,
          customer_code TEXT NOT NULL,
          amount TEXT NOT NULL,
          method TEXT NOT NULL,
          collected_at TEXT NOT NULL,
          connection_id TEXT,
          notes TEXT,
          balance_after TEXT,
          state TEXT NOT NULL DEFAULT 'pending',
          server_receipt_no TEXT,
          server_payment_id TEXT,
          code TEXT,
          reason TEXT,
          attempts INTEGER NOT NULL DEFAULT 0,
          last_error TEXT
        )''');
      await db.execute('CREATE INDEX idx_payments_state ON payments(state, seq)');
      await db.execute('CREATE INDEX idx_payments_customer ON payments(customer_id)');
      // Belt and braces: even a bug cannot delete a payment or rewrite its money fields.
      await db.execute('''
        CREATE TRIGGER payments_no_delete BEFORE DELETE ON payments
        BEGIN SELECT RAISE(ABORT, 'payments cannot be deleted'); END''');
      await db.execute('''
        CREATE TRIGGER payments_immutable BEFORE UPDATE ON payments
        WHEN NEW.client_txn_id IS NOT OLD.client_txn_id
          OR NEW.client_receipt_no IS NOT OLD.client_receipt_no
          OR NEW.customer_id IS NOT OLD.customer_id
          OR NEW.amount IS NOT OLD.amount
          OR NEW.method IS NOT OLD.method
          OR NEW.collected_at IS NOT OLD.collected_at
          OR NEW.connection_id IS NOT OLD.connection_id
        BEGIN SELECT RAISE(ABORT, 'payment details cannot be changed'); END''');
      await db.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)');
    });
    return LocalDb._(db);
  }

  Future<void> close() => _db.close();

  // ------------------------------------------------------------------ meta

  Future<String?> getMeta(String key) async {
    final rows = await _db.query('meta', where: 'key = ?', whereArgs: [key]);
    return rows.isEmpty ? null : rows.first['value'] as String;
  }

  Future<void> setMeta(String key, String value) => _db.insert(
      'meta', {'key': key, 'value': value},
      conflictAlgorithm: ConflictAlgorithm.replace);

  Future<DateTime?> lastDownload() async {
    final v = await getMeta('snapshot_at');
    return v == null ? null : DateTime.tryParse(v);
  }

  // ------------------------------------------------------------------ customers

  @override
  Future<void> replaceCustomers(List<Customer> customers, DateTime generatedAt) async {
    await _db.transaction((txn) async {
      await txn.delete('customers');
      final batch = txn.batch();
      for (final c in customers) {
        batch.insert('customers', {
          'id': c.id,
          'name': c.name,
          'search': CustomerSearch.haystack(c),
          'json': jsonEncode(_customerToJson(c)),
        });
      }
      await batch.commit(noResult: true);
      await txn.insert('meta', {'key': 'snapshot_at', 'value': generatedAt.toUtc().toIso8601String()},
          conflictAlgorithm: ConflictAlgorithm.replace);
    });
  }

  Future<int> customerCount() async =>
      Sqflite.firstIntValue(await _db.rawQuery('SELECT COUNT(*) FROM customers')) ?? 0;

  Future<Customer?> customer(String id) async {
    final rows = await _db.query('customers', where: 'id = ?', whereArgs: [id]);
    return rows.isEmpty ? null : Customer.fromStored(rows.first['json'] as String);
  }

  /// Offline search. Filters in Dart over the stored haystack (a few thousand rows is instant).
  Future<List<Customer>> searchCustomers(String query, {int limit = 100}) async {
    final rows = await _db.query('customers', columns: ['search', 'json'], orderBy: 'name');
    final out = <Customer>[];
    for (final r in rows) {
      if (CustomerSearch.matches(r['search'] as String, query)) {
        out.add(Customer.fromStored(r['json'] as String));
        if (out.length >= limit) break;
      }
    }
    return out;
  }

  // ------------------------------------------------------------------ payments

  /// Stores a payment and issues its provisional receipt number in ONE transaction, so a crash can
  /// never leave a printed receipt without a stored payment, or reuse a number.
  Future<QueuedPayment> addPayment({
    required String collectorCode,
    required Customer customer,
    required Money amount,
    required String method,
    String? connectionId,
    String? notes,
    DateTime? now,
  }) async {
    if (!amount.isPositive) throw ArgumentError('amount must be greater than zero');
    return _db.transaction((txn) async {
      final rows = await txn.query('meta', where: 'key = ?', whereArgs: ['receipt_counter']);
      final next = (rows.isEmpty ? 0 : int.parse(rows.first['value'] as String)) + 1;
      await txn.insert('meta', {'key': 'receipt_counter', 'value': '$next'},
          conflictAlgorithm: ConflictAlgorithm.replace);

      // Running estimate: the snapshot balance minus what this phone already collected from them.
      final collected = await _notInSnapshot(txn, customer.id);
      final after = customer.balance - collected - amount;

      final payment = QueuedPayment(
        clientTxnId: _uuid.v4(),
        clientReceiptNo: formatOfflineReceipt(collectorCode, next),
        customerId: customer.id,
        customerName: customer.name,
        customerCode: customer.code,
        amount: amount,
        method: method,
        collectedAt: (now ?? DateTime.now()).toUtc().toIso8601String(),
        connectionId: connectionId,
        notes: notes,
        balanceAfter: after,
      );
      final seq = await txn.insert('payments', payment.toRow());
      return QueuedPayment.fromRow({...payment.toRow(), 'seq': seq});
    });
  }

  /// Money collected on this phone that the downloaded balance does NOT contain yet:
  /// every payment still waiting to sync, plus synced ones collected after the snapshot was made.
  /// (A snapshot downloaded after a sync already includes those payments, so they are not subtracted twice.)
  Future<Money> _notInSnapshot(DatabaseExecutor ex, String customerId) async {
    final meta = await ex.query('meta', where: 'key = ?', whereArgs: ['snapshot_at']);
    final since = meta.isEmpty ? '' : meta.first['value'] as String;
    final rows = await ex.query('payments',
        columns: ['amount'],
        where: "customer_id = ? AND (state = 'pending' OR (state = 'synced' AND collected_at > ?))",
        whereArgs: [customerId, since]);
    return rows.fold<Money>(Money.zero, (a, r) => a + Money.parse(r['amount'] as String));
  }

  /// Balance to show while offline: downloaded balance minus what this phone collected since.
  Future<Money> estimatedBalance(Customer c) async => c.balance - await _notInSnapshot(_db, c.id);

  Future<QueuedPayment?> payment(String clientTxnId) async {
    final rows = await _db.query('payments', where: 'client_txn_id = ?', whereArgs: [clientTxnId]);
    return rows.isEmpty ? null : QueuedPayment.fromRow(rows.first);
  }

  @override
  Future<List<QueuedPayment>> pendingPayments({int limit = 50}) async {
    final rows = await _db.query('payments',
        where: 'state = ?', whereArgs: ['pending'], orderBy: 'seq', limit: limit);
    return rows.map(QueuedPayment.fromRow).toList();
  }

  Future<List<QueuedPayment>> history({String? customerId, int limit = 500}) async {
    final rows = await _db.query('payments',
        where: customerId == null ? null : 'customer_id = ?',
        whereArgs: customerId == null ? null : [customerId],
        orderBy: 'seq DESC',
        limit: limit);
    return rows.map(QueuedPayment.fromRow).toList();
  }

  Future<List<QueuedPayment>> paymentsOn(DateTime localDay) async {
    final start = DateTime(localDay.year, localDay.month, localDay.day).toUtc().toIso8601String();
    final end = DateTime(localDay.year, localDay.month, localDay.day + 1).toUtc().toIso8601String();
    final rows = await _db.query('payments',
        where: 'collected_at >= ? AND collected_at < ? AND state != ?',
        whereArgs: [start, end, 'rejected'],
        orderBy: 'seq DESC');
    return rows.map(QueuedPayment.fromRow).toList();
  }

  Future<Map<PaymentState, int>> counts() async {
    final rows = await _db.rawQuery('SELECT state, COUNT(*) AS n FROM payments GROUP BY state');
    return {for (final r in rows) paymentStateFrom(r['state'] as String): r['n'] as int};
  }

  @override
  Future<void> markSynced(String clientTxnId, {String? serverReceiptNo, String? serverPaymentId}) =>
      _db.update(
          'payments',
          {
            'state': 'synced',
            'server_receipt_no': serverReceiptNo,
            'server_payment_id': serverPaymentId,
            'code': null,
            'reason': null,
            'last_error': null,
          },
          where: 'client_txn_id = ?',
          whereArgs: [clientTxnId]);

  @override
  Future<void> markRejected(String clientTxnId, {String? code, String? reason}) => _db.update(
      'payments', {'state': 'rejected', 'code': code, 'reason': reason},
      where: 'client_txn_id = ?', whereArgs: [clientTxnId]);

  @override
  Future<void> recordFailedAttempt(String clientTxnId, String error) => _db.rawUpdate(
      'UPDATE payments SET attempts = attempts + 1, last_error = ? WHERE client_txn_id = ?',
      [error, clientTxnId]);
}

Map<String, dynamic> _customerToJson(Customer c) => {
      'id': c.id,
      'customer_code': c.code,
      'full_name': c.name,
      'full_name_ur': c.nameUr,
      'mobile': c.mobile,
      'whatsapp': c.whatsapp,
      'address': c.address,
      'address_ur': c.addressUr,
      'house_no': c.houseNo,
      'area_name': c.areaName,
      'balance': c.balance.toApi(),
      'amount_due': c.amountDue.toApi(),
      'credit': c.credit.toApi(),
      'billing_status': c.billingStatus,
      'oldest_due_date': c.oldestDueDate,
      'connections': [
        for (final k in c.connections)
          {
            'id': k.id,
            'connection_code': k.code,
            'internet_id': k.internetId,
            'connection_type': k.type,
            'status': k.status,
            'package_name': k.packageName,
            'package_name_ur': k.packageNameUr,
            'monthly_charge': k.monthlyCharge?.toApi(),
            'next_due_date': k.nextDueDate,
          }
      ],
      'open_invoices': [
        for (final i in c.openInvoices)
          {
            'id': i.id,
            'invoice_number': i.number,
            'period': i.period,
            'due_date': i.dueDate,
            'total': i.total.toApi(),
            'outstanding': i.outstanding.toApi(),
            'status': i.status,
          }
      ],
    };
