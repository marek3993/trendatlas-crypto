import { AuthShell } from "@/components/auth-shell";
import { LoginForm } from "@/components/login-form";
import { safeRedirectPath } from "@/lib/auth/redirects";

type LoginPageProps = {
  searchParams: Promise<{ next?: string | string[] }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const { next } = await searchParams;
  const destination = safeRedirectPath(typeof next === "string" ? next : null);
  return <AuthShell title="Welcome back"><LoginForm destination={destination} /></AuthShell>;
}
