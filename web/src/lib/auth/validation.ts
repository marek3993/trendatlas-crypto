export type RegistrationInput = {
  displayName: string;
  email: string;
  password: string;
  passwordConfirmation: string;
  termsAccepted: boolean;
};

export type ValidationResult =
  | { ok: true; email: string; displayName: string }
  | { ok: false; message: string };

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

export function validatePassword(password: string): ValidationResult {
  if (password.length < 8) {
    return { ok: false, message: "Use a password with at least 8 characters." };
  }
  return { ok: true, email: "", displayName: "" };
}

export function validateRegistration(input: RegistrationInput): ValidationResult {
  const displayName = input.displayName.trim();
  const email = normalizeEmail(input.email);

  if (!displayName) return { ok: false, message: "Enter your name." };
  if (!emailPattern.test(email)) return { ok: false, message: "Enter a valid email address." };
  if (!input.termsAccepted) return { ok: false, message: "Accept the terms to continue." };
  const passwordResult = validatePassword(input.password);
  if (!passwordResult.ok) return passwordResult;
  if (input.password !== input.passwordConfirmation) {
    return { ok: false, message: "Passwords do not match." };
  }
  return { ok: true, email, displayName };
}

export function validatePasswordUpdate(
  password: string,
  passwordConfirmation: string
): ValidationResult {
  const passwordResult = validatePassword(password);
  if (!passwordResult.ok) return passwordResult;
  if (password !== passwordConfirmation) {
    return { ok: false, message: "Passwords do not match." };
  }
  return { ok: true, email: "", displayName: "" };
}
