import { AuthShell } from "@/components/auth-shell";
import { ForgotPasswordForm } from "@/components/forgot-password-form";

export default function ForgotPasswordPage() {
  return <AuthShell title="Reset your password"><ForgotPasswordForm /></AuthShell>;
}
