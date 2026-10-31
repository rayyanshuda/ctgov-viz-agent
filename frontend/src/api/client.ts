// The one place that talks to the backend. Every call returns the parsed JSON, or throws
// an ApiError that carries the backend's error code, message and "what you can do" remedy.

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public remedy?: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, {
      ...init,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the server.", "Check your connection and try again.");
  }

  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);

  if (!res.ok) {
    // Our own errors look like {error, message, remedy}. FastAPI's validation errors look
    // like {detail: [{msg}]}, so those are turned into one readable sentence.
    const detail = Array.isArray(body?.detail) ? body.detail.map((d: { msg: string }) => d.msg).join("; ") : null;
    throw new ApiError(res.status, body?.error ?? "error", body?.message ?? detail ?? res.statusText, body?.remedy);
  }
  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  delete: (path: string) => request<void>(path, { method: "DELETE" }),
};
