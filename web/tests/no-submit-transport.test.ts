import { describe, expect, it, vi } from "vitest";
import { readOnlyTransport } from "@/server/multi-account-executor/read-only-transport";

describe("no-submit persistence boundary", () => {
  it.each(["POST", "PATCH", "DELETE", "PUT"])("blocks %s before network access", async method => {
    const network = vi.fn();
    await expect(readOnlyTransport(network)("https://example.test/rest/v1/journal", { method })).rejects.toThrow("forbidden");
    expect(network).not.toHaveBeenCalled();
  });
  it("rejects nonce/lease RPC even via GET", async () => {
    const network = vi.fn();
    await expect(readOnlyTransport(network)("https://example.test/rest/v1/rpc/reserve_nonce")).rejects.toThrow("forbidden");
    expect(network).not.toHaveBeenCalled();
  });
  it("rejects a write embedded in Request", async () => {
    await expect(readOnlyTransport(vi.fn())(new Request("https://example.test/journal", { method: "POST" }))).rejects.toThrow("forbidden");
  });
  it("permits read-only snapshots", async () => {
    const network = vi.fn().mockResolvedValue(new Response("[]"));
    await readOnlyTransport(network)("https://example.test/rest/v1/journal");
    expect(network).toHaveBeenCalledOnce();
  });
});
