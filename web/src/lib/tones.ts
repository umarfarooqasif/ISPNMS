export type Tone = "green" | "red" | "amber" | "blue" | "gray";

/** Colour for a status word anywhere in the app. Unknown words stay neutral. */
export function toneFor(status: string | null | undefined): Tone {
  switch ((status ?? "").toUpperCase()) {
    case "ACTIVE": case "PAID": case "COMPLETED": case "IMPORTED": case "SYNCED": case "MATCHED": case "NEW":
      return "green";
    case "DISCONNECTED": case "ERROR": case "FAILED": case "OVERDUE": case "REJECTED": case "ARCHIVED":
      return "red";
    case "DUE": case "PARTIAL": case "SUSPENDED": case "REVIEW": case "UPDATED": case "IN_REVIEW": case "IMPORTING":
      return "amber";
    case "FREE": case "TRIAL": case "PARSED": case "UPLOADED": case "APPROVED": case "DUPLICATE":
      return "blue";
    default:
      return "gray";
  }
}
