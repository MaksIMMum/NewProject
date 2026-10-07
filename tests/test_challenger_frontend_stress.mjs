/**
 * Adversarial Frontend Stress Testing Harness (Challenger 2).
 * Exercises edge cases, malformed payloads, and fallback boundary conditions in JS/Node runtime.
 * Run directly via: node --test tests/test_challenger_frontend_stress.mjs
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

describe("Frontend Stress & Boundary Adversarial Harness", () => {
  test("PKCE challenge generation never generates forbidden URI characters in 500 iterations", async () => {
    // RFC 7636 unreserved: [A-Z] / [a-z] / [0-9] / "-" / "." / "_" / "~"
    // base64url: [A-Z] / [a-z] / [0-9] / "-" / "_"
    const base64UrlPattern = /^[A-Za-z0-9\-_]+$/;

    for (let i = 0; i < 500; i++) {
      const verifier = generateRandomString(43 + (i % 85)); // Length between 43 and 128 (RFC 7636 sec 4.1)
      const challenge = await generateCodeChallenge(verifier);
      assert.match(challenge, base64UrlPattern);
      assert.ok(challenge.length >= 43 && challenge.length <= 44);
      assert.ok(!challenge.includes("="));
      assert.ok(!challenge.includes("+"));
      assert.ok(!challenge.includes("/"));
    }
  });

  test("cleanDomain handles extreme adversarial inputs", () => {
    assert.strictEqual(cleanDomain("https://domain.com/"), "domain.com");
    assert.strictEqual(cleanDomain("http://domain.com/////"), "domain.com");
    assert.strictEqual(cleanDomain("https://domain.com"), "domain.com");
    assert.strictEqual(cleanDomain("domain.com/"), "domain.com");
    assert.strictEqual(cleanDomain("domain.com"), "domain.com");
  });

  test("parseJwtPayload handles adversarial malformed inputs gracefully", () => {
    // Empty & non-token strings
    assert.strictEqual(parseJwtPayload(""), null);
    assert.strictEqual(parseJwtPayload("   "), null);
    assert.strictEqual(parseJwtPayload("not-a-token"), null);
    assert.strictEqual(parseJwtPayload("a.b"), null); // Invalid base64
    assert.strictEqual(parseJwtPayload("a.b.c"), null);

    // Corrupted payload JSON
    const badJson = btoa("not valid json");
    assert.strictEqual(parseJwtPayload(`header.${badJson}.sig`), null);

    // Deeply nested / unicode payload
    const unicodeData = { name: "Владислав Müller 日本語", email: "test@domain.org" };
    const encodedUnicode = btoa(unescape(encodeURIComponent(JSON.stringify(unicodeData))))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
    const validJwt = `head.${encodedUnicode}.sig`;
    assert.deepStrictEqual(parseJwtPayload(validJwt), unicodeData);
  });

  test("extractUserFromClaims edge cases and missing fields", () => {
    // Minimal empty claims
    const emptyClaims = {};
    const u1 = extractUserFromClaims(emptyClaims);
    assert.strictEqual(u1.email, "");
    assert.strictEqual(u1.name, "User");
    assert.strictEqual(u1.provider, "password");
    assert.strictEqual(u1.sub, undefined);

    // Only email provided
    const emailOnly = { email: "charlie@example.com" };
    const u2 = extractUserFromClaims(emailOnly);
    assert.strictEqual(u2.email, "charlie@example.com");
    assert.strictEqual(u2.name, "charlie");
    assert.strictEqual(u2.provider, "password");

    // Google federated identities
    const googleIdp = {
      sub: "10928301923",
      email: "goog@gmail.com",
      identities: [{ providerName: "Google" }],
    };
    const u3 = extractUserFromClaims(googleIdp);
    assert.strictEqual(u3.provider, "google");
    assert.strictEqual(u3.name, "goog");

    // Sub contains Google
    const subGoogle = { sub: "Google_1029384756", email: "foo@gmail.com" };
    const u4 = extractUserFromClaims(subGoogle);
    assert.strictEqual(u4.provider, "google");
  });
});
