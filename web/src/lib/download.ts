import { ApiError, detailOf } from "./api";

/**
 * Downloads a file from the API and saves it. Unlike a plain link, a refusal (no permission, too many
 * rows) is shown as a message instead of being saved as a broken file.
 */
export async function downloadFile(path: string, filename: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`/bff${path}`, { cache: "no-store" });
  } catch {
    throw new ApiError(0, "Could not reach the server. Check your internet connection.");
  }
  if (res.status === 401) {
    window.location.href = "/login";
    throw new ApiError(401, "Your session has ended. Please log in again.");
  }
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    const fallback = res.status === 403 ? "You do not have permission to download this." : `Could not download (error ${res.status}).`;
    throw new ApiError(res.status, detailOf(body, fallback));
  }
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
