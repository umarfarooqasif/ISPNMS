/// Money as whole paisa (integer). No floating point ever touches an amount.
class Money implements Comparable<Money> {
  final int paisa;
  const Money(this.paisa);

  static const zero = Money(0);

  static final _re = RegExp(r'^-?\d{1,10}(\.\d{1,2})?$');

  /// Parses "1000", "1000.5", "1000.50". Returns null for anything else (more than 2 decimals,
  /// letters, commas, empty).
  static Money? tryParse(String? input) {
    final s = (input ?? '').trim();
    if (!_re.hasMatch(s)) return null;
    final neg = s.startsWith('-');
    final body = neg ? s.substring(1) : s;
    final parts = body.split('.');
    final whole = int.parse(parts[0]);
    final frac = parts.length == 2 ? int.parse(parts[1].padRight(2, '0')) : 0;
    final total = whole * 100 + frac;
    return Money(neg ? -total : total);
  }

  factory Money.parse(String s) {
    final m = tryParse(s);
    if (m == null) throw FormatException('Not a valid amount: "$s"');
    return m;
  }

  bool get isPositive => paisa > 0;
  bool get isNegative => paisa < 0;
  bool get isZero => paisa == 0;

  Money operator +(Money o) => Money(paisa + o.paisa);
  Money operator -(Money o) => Money(paisa - o.paisa);
  Money max(Money o) => paisa >= o.paisa ? this : o;
  bool operator >(Money o) => paisa > o.paisa;
  bool operator <(Money o) => paisa < o.paisa;

  /// Exactly what the server expects: "500.00".
  String toApi() {
    final a = paisa.abs();
    return '${paisa < 0 ? '-' : ''}${a ~/ 100}.${(a % 100).toString().padLeft(2, '0')}';
  }

  /// For screens: "Rs 12,500" (paisa shown only when non-zero).
  String format() {
    final a = paisa.abs();
    final whole = (a ~/ 100).toString();
    final grouped = whole.replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => ',');
    final frac = a % 100;
    final tail = frac == 0 ? '' : '.${frac.toString().padLeft(2, '0')}';
    return '${paisa < 0 ? '-' : ''}Rs $grouped$tail';
  }

  @override
  int compareTo(Money other) => paisa.compareTo(other.paisa);

  @override
  bool operator ==(Object other) => other is Money && other.paisa == paisa;

  @override
  int get hashCode => paisa.hashCode;

  @override
  String toString() => toApi();
}
