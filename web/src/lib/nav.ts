/** The side menu: what exists, who sees it, and which item is lit for the current page. */

export interface NavItem {
  href: string;
  label: string;
  permission?: string; // shown only to people holding this permission
}

export const NAV: NavItem[] = [
  { href: "/", label: "Dashboard" },
  { href: "/customers", label: "Customers", permission: "customer.view" },
  { href: "/payments", label: "Payments", permission: "payment.view" },
  { href: "/billing/outstanding", label: "Who owes money", permission: "invoice.view" },
  { href: "/billing/run", label: "Bill run", permission: "billing.run" },
  { href: "/billing/runs", label: "Billing history", permission: "invoice.view" },
  { href: "/billing/late-fees", label: "Late fees", permission: "billing.run" },
  { href: "/billing/opening-balances", label: "Opening balances", permission: "billing.opening_balance" },
  { href: "/import", label: "Import customers", permission: "import.upload" },
];

/** Exact match, or a page below it. (So /billing/run does not light up for /billing/runs.) */
export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

export function visibleNav(permissions: readonly string[]): NavItem[] {
  return NAV.filter((n) => !n.permission || permissions.includes(n.permission));
}
