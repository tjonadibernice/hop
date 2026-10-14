/** Small wrapper around fetch for calling the Hop API through the Vite proxy. */

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type ValidationIssue = { msg: string };

/** Turn FastAPI's error body into one readable message. */
function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") {
      return detail;
    }
    // 422 validation errors: a list of problems, each with a message
    if (Array.isArray(detail) && detail.length > 0) {
      return (detail as ValidationIssue[])
        .map((issue) => issue.msg.replace(/^Value error, /, ""))
        .join(" ");
    }
  }
  return `Something went wrong (${status}). Please try again.`;
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: options.method ?? "GET",
    headers:
      options.body === undefined
        ? undefined
        : { "Content-Type": "application/json" },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  // 204 No Content has no body to parse
  const body: unknown =
    response.status === 204 ? null : await response.json().catch(() => null);

  if (!response.ok) {
    throw new ApiError(response.status, errorMessage(body, response.status));
  }
  return body as T;
}

/** The message to show the user for any error thrown by an API call. */
export function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  return "Can't reach the server. Check your connection and try again.";
}
