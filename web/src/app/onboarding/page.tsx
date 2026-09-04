import Link from "next/link";
import { requireUser } from "@/lib/auth/require-user";

export default async function OnboardingPage() {
  await requireUser();
  return <main><div className="card">
    <h1>Trading account</h1>
    <p className="muted">Account connections are not available yet.</p>
    <Link className="button" href="/dashboard">Back to dashboard</Link>
  </div></main>;
}
