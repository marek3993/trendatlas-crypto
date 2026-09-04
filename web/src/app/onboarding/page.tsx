import Link from "next/link";
import { requireUser } from "@/lib/auth/require-user";
import { HyperliquidConnectForm } from "@/components/hyperliquid-connect-form";

export default async function OnboardingPage() {
  await requireUser();
  return <main><div className="card">
    <h1>Connect Hyperliquid</h1>
    <p className="muted">Connect your account to view its current balances, positions, and open orders.</p>
    <HyperliquidConnectForm />
    <Link className="button" href="/dashboard">Back to dashboard</Link>
  </div></main>;
}
