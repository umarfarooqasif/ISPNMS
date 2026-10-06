/// Collector-friendly names for payment methods (the API codes stay unchanged).
String methodLabel(String m) => switch (m) {
      'COLLECTOR_CASH' => 'Cash',
      'CASH' => 'Cash (office)',
      'JAZZCASH' => 'JazzCash',
      'EASYPAISA' => 'Easypaisa',
      'BANK' => 'Bank',
      'QR' => 'QR',
      _ => m,
    };

/// Methods a collector can choose in the field.
const collectorMethods = ['COLLECTOR_CASH', 'JAZZCASH', 'EASYPAISA', 'BANK', 'QR'];
