"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, type ReactNode } from "react";

import { CSRF_HEADER, CSRF_VALUE } from "@/lib/bff-core";
import { useFetch } from "@/lib/hooks";
import type { Me } from "@/lib/types";
import { ErrorBox, Loading } from "./ui";

const MeContext = createContext<Me | null>(null);

export function useMe(): Me {
  const me = useContext(MeContext);
  if (!me) throw new Error("useMe must be used inside the app shell");
  return me;
}

/** True when the logged-in user holds the permission (the server still enforces it). */
export function useCan(): (permission: string) => boolean {
  const me = useMe();
  return (permission) => me.permissions.includes(permission);
}

const NAV: { href: string; label: string; permission?: string }[] = [
  { href: "/", label: "Dashboard" },
  { href: "/customers", label: "Customers", permission: "customer.view" },
  { href: "/import", label: "Import customers", permission: "import.upload" },
];

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const meState = useFetch<Me>("/auth/me");

  async function logout() {
    try {
      await fetch("/auth/logout", { method: "POST", headers: { [CSRF_HEADER]: CSRF_VALUE } });
    } finally {
      window.location.href = "/login";
    }
  }

  if (meState.loading && !meState.data) return <div className="main"><Loading /></div>;
  if (!meState.data) {
    return (
      <div className="main">
        <ErrorBox message={meState.error ?? "Could not load your account."} onRetry={meState.reload} />
      </div>
    );
  }
  const me = meState.data;
  const allowed = (p?: string) => !p || me.permissions.includes(p);

  return (
    <MeContext.Provider value={me}>
      <div className="shell">
        <nav className="side" aria-label="Main">
          <div className="brand">ISP Billing</div>
          {NAV.filter((n) => allowed(n.permission)).map((n) => {
            const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
            return (
              <Link key={n.href} href={n.href} className={active ? "active" : ""}>
                {n.label}
              </Link>
            );
          })}
          <div className="spacer" />
          <div className="who">{me.full_name}<br />{me.roles.join(", ")}</div>
          <a href="#" onClick={(e) => { e.preventDefault(); void logout(); }}>Log out</a>
        </nav>
        <main className="main">{children}</main>
      </div>
    </MeContext.Provider>
  );
}
