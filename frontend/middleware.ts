import { NextResponse, type NextRequest } from "next/server";

// "/" and "/platform" are public marketing pages.
const PUBLIC_PATHS = ["/", "/platform", "/login", "/register", "/forgot-password", "/privacy", "/terms"];

// Cheap gate only: the real auth check is the API answering 401 (lib/api.ts
// then redirects to /login). Here we just avoid rendering the dashboard shell
// for visitors that have no session cookie at all.
export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  if (PUBLIC_PATHS.includes(pathname)) return NextResponse.next();
  if (req.cookies.has("hf_session")) return NextResponse.next();
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = `?next=${encodeURIComponent(pathname + search)}`;
  return NextResponse.redirect(url);
}

export const config = {
  // Skip the API proxy, Next internals and static files (anything with a file extension, e.g. /landing/*.jpg).
  matcher: ["/((?!api/|_next/|.*\\.[a-zA-Z0-9]+$).*)"],
};
