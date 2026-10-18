const ethereumAddressPattern = /^0x[0-9a-fA-F]{40}$/;

export type AddressValidation =
  | { ok: true; address: string }
  | { ok: false; message: string };

/** Uses a lowercase canonical representation for case-insensitive Ethereum addresses. */
export function normalizeHyperliquidAddress(value: string): string {
  return value.trim().toLowerCase();
}

export function validateHyperliquidAddress(value: string): AddressValidation {
  const address = normalizeHyperliquidAddress(value);
  if (!ethereumAddressPattern.test(address)) {
    return { ok: false, message: "Enter a valid Hyperliquid account address." };
  }
  return { ok: true, address };
}

export function displayHyperliquidAddress(address: string): string {
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}
