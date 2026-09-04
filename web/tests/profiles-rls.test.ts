import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const migration = fs.readFileSync(
  path.join(process.cwd(), "supabase/migrations/202609040001_create_profiles.sql"),
  "utf8"
);

describe("profiles migration and cross-user isolation", () => {
  it("defines the required profile fields and hardened user trigger", () => {
    expect(migration).toMatch(/id uuid primary key references auth\.users\(id\)/);
    expect(migration).toContain("email text not null");
    expect(migration).toContain("display_name text not null");
    expect(migration).toContain("account_status text not null default 'active'");
    expect(migration).toContain("onboarding_status text not null default 'not_started'");
    expect(migration).toContain("security definer");
    expect(migration).toContain("set search_path = public, pg_temp");
    expect(migration).toContain("after insert on auth.users");
  });

  it("enforces database-owned cross-user isolation without client insert or delete", () => {
    expect(migration).toContain("enable row level security");
    expect(migration).toContain("force row level security");
    expect(migration).toContain("revoke all on table public.profiles from public, anon, authenticated");
    expect(migration).toContain("grant select on table public.profiles to authenticated");
    expect(migration).toMatch(/using \(\(select auth\.uid\(\)\) = id\)/);
    expect(migration).toMatch(/with check \(\(select auth\.uid\(\)\) = id\)/);
    expect(migration).not.toMatch(/create policy[^;]+for insert/i);
    expect(migration).not.toMatch(/create policy[^;]+for delete/i);
  });

  it("grants browser updates only for display_name and reserves system fields", () => {
    expect(migration).toContain("grant update (display_name) on table public.profiles to authenticated");
    expect(migration).not.toMatch(/grant update\s+on table public\.profiles to authenticated/i);
    expect(migration).not.toMatch(/grant update\s*\([^)]*(email|account_status|onboarding_status|created_at|updated_at|id)[^)]*\)/i);
  });
});
