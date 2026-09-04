import { AuthShell } from "@/components/auth-shell";
import { RegisterForm } from "@/components/register-form";

export default function RegisterPage() {
  return <AuthShell title="Create your account"><RegisterForm /></AuthShell>;
}
