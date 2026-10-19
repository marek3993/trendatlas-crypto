/** Only this bounded string may cross the worker's diagnostic boundary. */
export function safeExecutionError(error: unknown, stage?: string, secrets: Array<string | undefined> = []): string {
  const describe = (value: unknown): string => {
    if (typeof value === "string") return `Error: ${value}`;
    if (!value || typeof value !== "object") return "Error: unknown failure";
    const e = value as {name?: unknown; message?: unknown; code?: unknown};
    const name = typeof e.name === "string" ? e.name : "Error";
    const code = typeof e.code === "string" && /^[A-Z0-9]{3,10}$/.test(e.code) ? ` [${e.code}]` : "";
    return `${name}${code}: ${typeof e.message === "string" ? e.message : "unknown failure"}`;
  };
  let text = `${stage ? `${stage}: ` : ""}${describe(error)}`;
  if (error instanceof Error && error.cause) text += `; ${describe(error.cause)}`;
  // Redact BEFORE truncation: truncation must not reveal a key prefix.
  for (const secret of secrets) if (secret) text = text.split(secret).join("[REDACTED]");
  return text
    .replace(/https?:\/\/[^\s"'<>]+/gi, "[URL]")
    .replace(/\b(?:authorization|password|token|secret|(?:api|private)[_-]?key|TRENDATLAS_AGENT_KEK_B64)\s*[:=]\s*["']?[^\s,;"']+/gi, "[REDACTED]")
    .replace(/0x[0-9a-f]+/gi, "[HEX]")
    .replace(/\b[0-9a-f]{16,}\b/gi, "[HEX]")
    .replace(/[A-Za-z0-9+/_-]{32,}={0,2}/g, "[TOKEN]")
    .replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, " ")
    .replace(/\s+/g, " ").trim().slice(0, 200);
}
