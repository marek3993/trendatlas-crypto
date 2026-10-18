const DEFAULT_AUTHENTICATED_PATH = "/dashboard";

export function safeRedirectPath(candidate: string | null | undefined): string {
  if (!candidate || !candidate.startsWith("/") || candidate.startsWith("//")) {
    return DEFAULT_AUTHENTICATED_PATH;
  }
  try {
    const parsed = new URL(candidate, "https://trendatlas.local");
    return parsed.origin === "https://trendatlas.local" ? `${parsed.pathname}${parsed.search}` : DEFAULT_AUTHENTICATED_PATH;
  } catch {
    return DEFAULT_AUTHENTICATED_PATH;
  }
}

export function protectedRouteRedirect(pathname: string, hasUser: boolean): string | null {
  return hasUser ? null : `/login?next=${encodeURIComponent(pathname)}`;
}

export function publicRouteRedirect(hasUser: boolean): string | null {
  return hasUser ? DEFAULT_AUTHENTICATED_PATH : null;
}
