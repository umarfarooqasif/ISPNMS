/// Provisional receipt numbers printed before a payment reaches the server.
///
/// Format: OFF-<collector code>-<counter>, e.g. OFF-C01-0042. The counter only ever goes up, is
/// stored in the same database transaction as the payment, and is never reused, so two paper
/// receipts from one phone can never carry the same number. The server remembers the number next
/// to its own permanent receipt number so every paper receipt can be traced.
String formatOfflineReceipt(String collectorCode, int counter) {
  final code = collectorCode.replaceAll(RegExp(r'[^A-Za-z0-9]'), '').toUpperCase();
  final n = counter.toString().padLeft(4, '0');
  final value = 'OFF-${code.isEmpty ? 'X' : code}-$n';
  // The server stores at most 40 characters.
  return value.length <= 40 ? value : value.substring(value.length - 40);
}
