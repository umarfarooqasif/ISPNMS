import type { ReactNode } from "react";

/** Printed pages have no menu: just the document and a toolbar that never prints. */
export default function PrintLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
