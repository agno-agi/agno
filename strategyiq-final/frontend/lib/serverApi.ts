/**
 * Base URL for server-side / Edge fetches to FastAPI.
 * Prefer FASTAPI_URL (Docker service name) over NEXT_PUBLIC_API_URL (browser/localhost).
 */
export function getServerApiUrl(): string {
  return (
    process.env.FASTAPI_URL ||
    process.env.API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "http://localhost:8000"
  );
}
