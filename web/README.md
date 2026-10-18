# TrendAtlas account connections

Hyperliquid connections are read-only. The server verifies and stores a user's normalized public account address, then requests only the Info API account state and open-order data. No wallet signing material is collected or stored.

## Rate-limit design

Apply rate limiting at the deployment edge before the server actions and pages execute:

- Connection verification: 5 attempts per authenticated user per hour, plus an IP-based abuse limit.
- Dashboard account refreshes: 60 requests per authenticated user per minute.
- Reject excess requests with a generic retry message; do not include upstream error details.

The limits must be backed by a shared production store so they apply across all application instances. The server action remains the only write path for read-only connections; browser clients receive no table insert or update grants.
