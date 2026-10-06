import 'dart:convert';

import 'money.dart';

Money _m(dynamic v) => Money.parse((v ?? '0').toString());

class Connection {
  final String id;
  final String code;
  final String? internetId;
  final String type;
  final String status;
  final String? packageName;
  final String? packageNameUr;
  final Money? monthlyCharge;
  final String? nextDueDate;

  const Connection({
    required this.id,
    required this.code,
    this.internetId,
    required this.type,
    required this.status,
    this.packageName,
    this.packageNameUr,
    this.monthlyCharge,
    this.nextDueDate,
  });

  factory Connection.fromJson(Map<String, dynamic> j) => Connection(
        id: j['id'] as String,
        code: j['connection_code'] as String,
        internetId: j['internet_id'] as String?,
        type: j['connection_type'] as String,
        status: j['status'] as String,
        packageName: j['package_name'] as String?,
        packageNameUr: j['package_name_ur'] as String?,
        monthlyCharge: j['monthly_charge'] == null ? null : _m(j['monthly_charge']),
        nextDueDate: j['next_due_date'] as String?,
      );
}

class OpenInvoice {
  final String id;
  final String number;
  final String? period;
  final String dueDate;
  final Money total;
  final Money outstanding;
  final String status;

  const OpenInvoice({
    required this.id,
    required this.number,
    this.period,
    required this.dueDate,
    required this.total,
    required this.outstanding,
    required this.status,
  });

  factory OpenInvoice.fromJson(Map<String, dynamic> j) => OpenInvoice(
        id: j['id'] as String,
        number: j['invoice_number'] as String,
        period: j['period'] as String?,
        dueDate: j['due_date'] as String,
        total: _m(j['total']),
        outstanding: _m(j['outstanding']),
        status: j['status'] as String,
      );
}

/// A customer as downloaded in the snapshot (read-only on the phone).
class Customer {
  final String id;
  final String code;
  final String name;
  final String? nameUr;
  final String? mobile;
  final String? whatsapp;
  final String? address;
  final String? addressUr;
  final String? houseNo;
  final String? areaName;
  final Money balance; // server balance at snapshot time (positive = owes)
  final Money amountDue;
  final Money credit;
  final String billingStatus;
  final String? oldestDueDate;
  final List<Connection> connections;
  final List<OpenInvoice> openInvoices;

  const Customer({
    required this.id,
    required this.code,
    required this.name,
    this.nameUr,
    this.mobile,
    this.whatsapp,
    this.address,
    this.addressUr,
    this.houseNo,
    this.areaName,
    required this.balance,
    required this.amountDue,
    required this.credit,
    required this.billingStatus,
    this.oldestDueDate,
    this.connections = const [],
    this.openInvoices = const [],
  });

  factory Customer.fromJson(Map<String, dynamic> j) => Customer(
        id: j['id'] as String,
        code: j['customer_code'] as String,
        name: j['full_name'] as String,
        nameUr: j['full_name_ur'] as String?,
        mobile: j['mobile'] as String?,
        whatsapp: j['whatsapp'] as String?,
        address: j['address'] as String?,
        addressUr: j['address_ur'] as String?,
        houseNo: j['house_no'] as String?,
        areaName: j['area_name'] as String?,
        balance: _m(j['balance']),
        amountDue: _m(j['amount_due']),
        credit: _m(j['credit']),
        billingStatus: j['billing_status'] as String,
        oldestDueDate: j['oldest_due_date'] as String?,
        connections: ((j['connections'] ?? []) as List)
            .map((e) => Connection.fromJson(e as Map<String, dynamic>))
            .toList(),
        openInvoices: ((j['open_invoices'] ?? []) as List)
            .map((e) => OpenInvoice.fromJson(e as Map<String, dynamic>))
            .toList(),
      );

  static Customer fromStored(String json) =>
      Customer.fromJson(jsonDecode(json) as Map<String, dynamic>);
}

enum PaymentState { pending, synced, rejected }

PaymentState paymentStateFrom(String s) =>
    PaymentState.values.firstWhere((e) => e.name == s, orElse: () => PaymentState.pending);

/// A payment collected on this phone. Rows are only ever added and their sync fields updated:
/// the app has no way to edit or delete one (collectors cannot alter financial history).
class QueuedPayment {
  final String clientTxnId; // unique id; the server uses it to reject duplicate syncs
  final String clientReceiptNo; // provisional receipt number printed on the paper
  final String customerId;
  final String customerName;
  final String customerCode;
  final Money amount;
  final String method;
  final String collectedAt; // UTC ISO-8601
  final String? connectionId;
  final String? notes;
  final Money? balanceAfter; // what the phone showed the customer (local estimate)
  final int seq;
  final PaymentState state;
  final String? serverReceiptNo;
  final String? serverPaymentId;
  final String? code;
  final String? reason;
  final int attempts;
  final String? lastError;

  const QueuedPayment({
    required this.clientTxnId,
    required this.clientReceiptNo,
    required this.customerId,
    required this.customerName,
    required this.customerCode,
    required this.amount,
    required this.method,
    required this.collectedAt,
    this.connectionId,
    this.notes,
    this.balanceAfter,
    this.seq = 0,
    this.state = PaymentState.pending,
    this.serverReceiptNo,
    this.serverPaymentId,
    this.code,
    this.reason,
    this.attempts = 0,
    this.lastError,
  });

  Map<String, Object?> toRow() => {
        'client_txn_id': clientTxnId,
        'client_receipt_no': clientReceiptNo,
        'customer_id': customerId,
        'customer_name': customerName,
        'customer_code': customerCode,
        'amount': amount.toApi(),
        'method': method,
        'collected_at': collectedAt,
        'connection_id': connectionId,
        'notes': notes,
        'balance_after': balanceAfter?.toApi(),
        'state': state.name,
        'server_receipt_no': serverReceiptNo,
        'server_payment_id': serverPaymentId,
        'code': code,
        'reason': reason,
        'attempts': attempts,
        'last_error': lastError,
      };

  factory QueuedPayment.fromRow(Map<String, Object?> r) => QueuedPayment(
        clientTxnId: r['client_txn_id'] as String,
        clientReceiptNo: r['client_receipt_no'] as String,
        customerId: r['customer_id'] as String,
        customerName: r['customer_name'] as String,
        customerCode: r['customer_code'] as String,
        amount: Money.parse(r['amount'] as String),
        method: r['method'] as String,
        collectedAt: r['collected_at'] as String,
        connectionId: r['connection_id'] as String?,
        notes: r['notes'] as String?,
        balanceAfter: r['balance_after'] == null ? null : Money.parse(r['balance_after'] as String),
        seq: (r['seq'] as int?) ?? 0,
        state: paymentStateFrom(r['state'] as String),
        serverReceiptNo: r['server_receipt_no'] as String?,
        serverPaymentId: r['server_payment_id'] as String?,
        code: r['code'] as String?,
        reason: r['reason'] as String?,
        attempts: (r['attempts'] as int?) ?? 0,
        lastError: r['last_error'] as String?,
      );

  /// Body item for POST /collector/payments/sync.
  Map<String, dynamic> toSyncJson() => {
        'client_txn_id': clientTxnId,
        'customer_id': customerId,
        'amount': amount.toApi(),
        'method': method,
        'collected_at': collectedAt,
        if (connectionId != null) 'connection_id': connectionId,
        if (notes != null) 'notes': notes,
        'client_receipt_no': clientReceiptNo,
      };

  /// The number to show a customer: the permanent server receipt once known, else the paper one.
  String get displayReceipt => serverReceiptNo ?? clientReceiptNo;
}

/// The server's answer for one payment of a sync call.
class SyncResult {
  final String clientTxnId;
  final String status; // SYNCED | DUPLICATE | REJECTED | ERROR
  final String? code;
  final String? reason;
  final String? paymentId;
  final String? receiptNumber;

  const SyncResult({
    required this.clientTxnId,
    required this.status,
    this.code,
    this.reason,
    this.paymentId,
    this.receiptNumber,
  });

  factory SyncResult.fromJson(Map<String, dynamic> j) => SyncResult(
        clientTxnId: j['client_txn_id'] as String,
        status: j['status'] as String,
        code: j['code'] as String?,
        reason: j['reason'] as String?,
        paymentId: j['payment_id'] as String?,
        receiptNumber: j['receipt_number'] as String?,
      );
}

class SnapshotPage {
  final DateTime generatedAt;
  final int total;
  final int offset;
  final List<Customer> customers;
  const SnapshotPage(this.generatedAt, this.total, this.offset, this.customers);

  factory SnapshotPage.fromJson(Map<String, dynamic> j) => SnapshotPage(
        DateTime.parse(j['generated_at'] as String),
        j['total'] as int,
        j['offset'] as int,
        (j['customers'] as List).map((e) => Customer.fromJson(e as Map<String, dynamic>)).toList(),
      );
}
