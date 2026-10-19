import { AuthShell } from "@/components/auth-shell";
import { UpdatePasswordForm } from "@/components/update-password-form";

export default function UpdatePasswordPage() {
  return <AuthShell title="Choose a new password"><UpdatePasswordForm /></AuthShell>;
}
