/**
 * Node.js test suite for Frontend PKCE and OAuth 2.0 Helpers.
 * Run directly via: node --test tests/test_frontend_pkce.mjs
 */

import assert from "node:assert/strict";
import test, { describe } from "node:test";

function cleanDomain(domain) {
  return domain.replace(/^https?:\/\//, "").replace(/\/+$/, "");
}

function generateRandomString(length = 64) {
  const charset =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";
  const randomValues = new Uint8Array(length);
  crypto.getRandomValues(randomValues);
  let result = "";
  for (let i = 0; i < length; i++) {
    result += charset[randomValues[i] % charset.length];
  }
  return result;
}

function base64UrlEncode(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

async function generateCodeChallenge(verifier) {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return base64UrlEncode(digest);
}

function parseJwtPayload(token) {
  try {
    const parts = token.split(".");
    if (parts.length < 2) return null;
    let base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    while (base64.length % 4 !== 0) {
      base64 += "=";
    }
    const jsonStr = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join(""),
    );
    return JSON.parse(jsonStr);
  } catch {
    return null;
  }
}

function extractUserFromClaims(claims) {
  const email = String(claims.email ?? "");
  const name = String(claims.name ?? (email ? email.split("@")[0] : "User"));
  const isGoogle =
    Boolean(claims.identities) ||
    (typeof claims.sub === "string" && claims.sub.includes("Google")) ||
    (Array.isArray(claims.identities) && claims.identities.length > 0);
  return {
    name,
    email,
    provider: isGoogle ? "google" : "password",
    sub: claims.sub ? String(claims.sub) : undefined,
  };
}

describe("Frontend PKCE & OAuth Algorithms", () => {
  test("matches RFC 7636 Appendix B test vector", async () => {
    const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
    const expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM";
    const challenge = await generateCodeChallenge(verifier);
    assert.strictEqual(challenge, expected);
  });

  test("generateRandomString produces valid RFC 7636 unreserved characters", () => {
    const randomStr = generateRandomString(64);
    assert.strictEqual(randomStr.length, 64);
    const validCharset = /^[A-Za-z0-9\-._~]+$/;
    assert.match(randomStr, validCharset);
  });

  test("cleanDomain normalizes protocols and trailing slashes", () => {
    assert.strictEqual(
      cleanDomain("https://auth.example.com"),
      "auth.example.com",
    );
    assert.strictEqual(
      cleanDomain("http://auth.example.com/"),
      "auth.example.com",
    );
    assert.strictEqual(
      cleanDomain("https://auth.example.com///"),
      "auth.example.com",
    );
    assert.strictEqual(cleanDomain("auth.example.com"), "auth.example.com");
  });

  test("parseJwtPayload decodes standard claims and handles padding", () => {
    const payload = {
      sub: "user-123",
      email: "test@example.com",
      name: "Test User",
    };
    const base64UrlPayload = btoa(JSON.stringify(payload))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
    const fakeToken = `header.${base64UrlPayload}.signature`;

    const parsed = parseJwtPayload(fakeToken);
    assert.deepStrictEqual(parsed, payload);
  });

  test("parseJwtPayload safely handles invalid tokens", () => {
    assert.strictEqual(parseJwtPayload(""), null);
    assert.strictEqual(parseJwtPayload("single-part-token"), null);
    assert.strictEqual(
      parseJwtPayload("header.invalid-base64!@#.signature"),
      null,
    );
  });

  test("extractUserFromClaims identifies Google provider via identities array", () => {
    const claims = {
      sub: "google-sub-id",
      email: "alex@gmail.com",
      identities: [{ providerName: "Google", providerType: "Google" }],
    };
    const user = extractUserFromClaims(claims);
    assert.strictEqual(user.provider, "google");
    assert.strictEqual(user.email, "alex@gmail.com");
    assert.strictEqual(user.name, "alex");
  });

  test("extractUserFromClaims defaults to password provider when not Google", () => {
    const claims = {
      sub: "cognito-sub-uuid",
      email: "jane@example.com",
      name: "Jane Doe",
    };
    const user = extractUserFromClaims(claims);
    assert.strictEqual(user.provider, "password");
    assert.strictEqual(user.name, "Jane Doe");
  });
});
