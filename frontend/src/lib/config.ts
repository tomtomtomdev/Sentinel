/**
 * Runtime configuration for the SPA.
 *
 * The API base URL comes from Vite env at build time. The S9a Bearer token is
 * read from localStorage first (set via the UI) with a Vite env fallback for
 * local dev — anything in Vite env ends up in the public bundle, so a real
 * deployment must use the localStorage path.
 */

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL || "/api/v1";

export const AUTH_TOKEN_STORAGE_KEY = "sentinel.auth_token";

export function getAuthToken(): string {
  return (
    localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) ||
    import.meta.env.VITE_AUTH_TOKEN ||
    ""
  );
}

export function setAuthToken(token: string): void {
  if (token) {
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
  } else {
    localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
  }
}
