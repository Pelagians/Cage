import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { isAllowedHost, route, json } from "@/lib/server/api";

describe("host allowlist (DNS-rebinding guard)", () => {
  it("accepts loopback and private LAN IPs", () => {
    for (const h of ["127.0.0.1:3000", "localhost:3000", "[::1]:3000", "192.168.1.20:3000", "10.0.0.5", "172.20.1.1:3000"]) {
      expect(isAllowedHost(h), h).toBe(true);
    }
  });
  it("rejects public or rebound hostnames", () => {
    for (const h of ["evil.test:3000", "127.0.0.1.nip.io:3000", "8.8.8.8", "172.32.0.1", null]) {
      expect(isAllowedHost(h), String(h)).toBe(false);
    }
  });
});

describe("route guard", () => {
  const handler = route(async () => json({ ok: true }));
  const call = (method: string, headers: Record<string, string>, body?: string) =>
    handler(new NextRequest("http://127.0.0.1:3000/api/x", { method, headers: { host: "127.0.0.1:3000", ...headers }, body }), {});

  it("allows a body-less DELETE (no content-type)", async () => {
    process.env.CLIPWISE_DB_PATH = ":memory:";
    expect((await call("DELETE", { origin: "http://127.0.0.1:3000" })).status).toBe(200);
  });
  it("rejects cross-origin and non-JSON mutations", async () => {
    expect((await call("POST", { origin: "https://evil.example", "content-type": "application/json" }, "{}")).status).toBe(403);
    expect((await call("POST", { "content-type": "text/plain", "content-length": "3" }, "x=1")).status).toBe(415);
  });
  it("rejects unknown hosts even for GET", async () => {
    const res = await handler(new NextRequest("http://evil.test:3000/api/x", { headers: { host: "evil.test:3000" } }), {});
    expect(res.status).toBe(403);
  });
});
