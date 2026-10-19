import {describe,expect,it} from "vitest";
import {safeExecutionError} from "@/server/multi-account-executor/safe-error";

describe("private execution diagnostics",()=>{
  it("redacts complete keys, addresses, hex, base64 and URLs before truncation",()=>{
    const key=`0x${"ab".repeat(32)}`, raw="fe".repeat(32), b64=Buffer.alloc(32,7).toString("base64");
    const error=new TypeError(`failed ${key} ${raw} ${b64} https://example.invalid/?key=secret\n${"x".repeat(300)}`);
    const result=safeExecutionError(error,"decryptAgent");
    expect(result).toContain("decryptAgent: TypeError: failed");
    for(const secret of [key,raw,b64,"example.invalid","abababab","\n"])expect(result).not.toContain(secret);
    expect(result.length).toBeLessThanOrEqual(200);
  });
  it("keeps a database error code and cause but never dumps request fields",()=>{
    const result=safeExecutionError(new Error("nonce unavailable",{cause:{code:"42501",message:"permission denied",request:{key:"MUST_NOT_PRINT"}}}),"reserveNonce");
    expect(result).toContain("42501");expect(result).toContain("permission denied");expect(result).not.toContain("MUST_NOT_PRINT");
  });
  it("redacts known short secrets and control characters",()=>{
    expect(safeExecutionError(new Error("token=abc\r\nknown tiny-secret\u001b"),undefined,["tiny-secret"]))
      .toBe("Error: [REDACTED] known [REDACTED]");
  });
});
