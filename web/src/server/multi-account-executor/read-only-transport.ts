/** Rehearsals cannot reserve nonces, leases, journal rows or account state. */
export function readOnlyTransport(delegate: typeof fetch = fetch): typeof fetch {
  return async (input, init) => {
    const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    const url = input instanceof Request ? input.url : String(input);
    if (!["GET", "HEAD"].includes(method) || new URL(url).pathname.includes("/rpc/")) {
      throw new Error("No-submit database mutation forbidden");
    }
    return delegate(input, init);
  };
}
