/**
 * Empirical Adversarial Test Harness - Challenger 1
 * Stress tests:
 * 1. PKCE Random Entropy & Statistical Distribution (10,000 iterations, Shannon entropy, charset adherence, collision check)
 * 2. PKCE S256 Challenge Derivation Properties (1,000 iterations, exact 43-char URL-safe base64url)
 * 3. JWT Payload Parsing Under Adversarial Fuzzing (invalid UTF-8, malformed base64, JSON primitives, prototype pollution, large payloads)
 * 4. User Profile Extraction Edge Cases (missing fields, malformed types, Google identity heuristics)
 * 5. Network Error & Token Exchange Simulation (timeouts, HTTP 400/500, non-JSON bodies, missing tokens)
 * 6. Domain and Redirect URI Sanitization Edge Cases
 */

import assert from "node:assert/strict";
import test, { describe } from "node:test";

// --- Mirror implementations from frontend/src/lib/auth.ts ---

function cleanDomain(domain) {
  return domain
    .trim()
    .replace(/^https?:\/\//, "")
    .replace(/\/+$/, "");
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

// Token exchange simulation
async function simulateExchangeAuthCode({
  code,
  verifier,
  mockFetch,
  storage,
  domain = "auth.example.com",
  clientId = "test-client-id",
  redirectUri = "http://localhost:5173/login",
}) {
  const tokenUrl = `https://${cleanDomain(domain)}/oauth2/token`;
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: clientId,
    code,
    redirect_uri: redirectUri,
    code_verifier: verifier,
  });

  const response = await mockFetch(tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });

  if (!response.ok) {
    let errorDetail = "Token exchange failed";
    try {
      const errJson = await response.json();
      errorDetail = errJson.error_description || errJson.error || errorDetail;
    } catch {
      // response body not JSON
    }
    throw new Error(errorDetail);
  }

  const data = await response.json();
  if (data.id_token)
    storage.localStorage.setItem("meetings.id_token", data.id_token);
  if (data.access_token)
    storage.localStorage.setItem("meetings.access_token", data.access_token);
  if (data.refresh_token)
    storage.localStorage.setItem("meetings.refresh_token", data.refresh_token);
  storage.sessionStorage.removeItem("meetings.pkce_verifier");

  if (!data.id_token) {
    throw new Error("No ID token received from authentication server");
  }

  const claims = parseJwtPayload(data.id_token);
  if (!claims) {
    throw new Error("Failed to parse ID token claims");
  }

  return extractUserFromClaims(claims);
}

// =========================================================================
// TEST SUITES
// =========================================================================

describe("Adversarial Suite 1: PKCE Random Entropy & Statistical Distribution", () => {
  test("generates 10,000 verifiers with zero collisions and strict RFC 7636 charset", () => {
    const COUNT = 10000;
    const seen = new Set();
    const rfc7636Regex = /^[A-Za-z0-9\-._~]{64}$/;
    const charCounts = new Map();

    const charset =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";
    for (const c of charset) {
      charCounts.set(c, 0);
    }

    for (let i = 0; i < COUNT; i++) {
      const verifier = generateRandomString(64);
      assert.strictEqual(
        verifier.length,
        64,
        "Every verifier must be exactly 64 characters",
      );
      assert.match(
        verifier,
        rfc7636Regex,
        "Must strictly conform to RFC 7636 unreserved set",
      );

      assert.strictEqual(
        seen.has(verifier),
        false,
        `Collision detected at iteration ${i}`,
      );
      seen.add(verifier);

      for (const char of verifier) {
        charCounts.set(char, (charCounts.get(char) || 0) + 1);
      }
    }

    assert.strictEqual(
      seen.size,
      COUNT,
      "All 10,000 verifiers must be strictly unique",
    );

    // Check that every single character in the 66-character charset was generated
    for (const [char, count] of charCounts.entries()) {
      assert.ok(
        count > 0,
        `Character '${char}' was never generated in 640,000 characters! Generator is defective.`,
      );
    }

    // Compute empirical Shannon entropy: H = -sum(p * log2(p))
    const totalChars = COUNT * 64;
    let entropy = 0;
    for (const count of charCounts.values()) {
      const p = count / totalChars;
      entropy -= p * Math.log2(p);
    }

    // Theoretical maximum entropy for 66 uniform characters: log2(66) = 6.044394
    // Require empirical entropy > 6.0 bits/symbol
    assert.ok(
      entropy > 6.0,
      `Empirical Shannon entropy (${entropy.toFixed(4)}) is below threshold (6.0). Poor randomness!`,
    );
  });

  test("handles arbitrary lengths: minimum 43, maximum 128, and zero length", () => {
    assert.strictEqual(generateRandomString(43).length, 43);
    assert.strictEqual(generateRandomString(128).length, 128);
    assert.strictEqual(generateRandomString(0).length, 0);
    assert.strictEqual(generateRandomString(256).length, 256);
  });
});

describe("Adversarial Suite 2: PKCE S256 Challenge Derivation Invariance", () => {
  test("RFC 7636 Appendix B test vector validation", async () => {
    const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
    const expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM";
    const challenge = await generateCodeChallenge(verifier);
    assert.strictEqual(challenge, expected);
  });

  test("property test: 1,000 random verifiers yield strictly 43-char URL-safe challenges", async () => {
    const challengePattern = /^[A-Za-z0-9\-_]{43}$/;
    for (let i = 0; i < 1000; i++) {
      const verifier = generateRandomString(64);
      const challenge = await generateCodeChallenge(verifier);

      assert.strictEqual(
        challenge.length,
        43,
        "Base64URL SHA-256 digest must be exactly 43 chars",
      );
      assert.match(
        challenge,
        challengePattern,
        "Challenge must only contain URL-safe base64url characters",
      );
      assert.strictEqual(
        challenge.includes("="),
        false,
        "Must not contain padding equals",
      );
      assert.strictEqual(
        challenge.includes("+"),
        false,
        "Must not contain standard base64 '+'",
      );
      assert.strictEqual(
        challenge.includes("/"),
        false,
        "Must not contain standard base64 '/'",
      );
    }
  });

  test("determinism and collision resistance across distinct verifiers", async () => {
    const v1 = generateRandomString(64);
    const v2 = generateRandomString(64);
    const c1a = await generateCodeChallenge(v1);
    const c1b = await generateCodeChallenge(v1);
    const c2 = await generateCodeChallenge(v2);

    assert.strictEqual(
      c1a,
      c1b,
      "PKCE derivation must be strictly deterministic",
    );
    assert.notStrictEqual(
      c1a,
      c2,
      "Different verifiers must produce distinct challenges",
    );
  });
});

describe("Adversarial Suite 3: JWT Parsing Under Adversarial & Fuzzing Inputs", () => {
  test("gracefully returns null on malformed structures and empty inputs", () => {
    const malformedInputs = [
      "",
      "...",
      "header",
      "header.",
      ".payload",
      "part1.part2.part3.part4",
      "header.not-base64!@#.sig",
      "header.SGVsbG8.sig", // "Hello" is not JSON
      "header..sig", // empty payload
      null,
      undefined,
    ];

    for (const input of malformedInputs) {
      if (typeof input === "string") {
        assert.strictEqual(
          parseJwtPayload(input),
          null,
          `Expected null for: ${input}`,
        );
      }
    }
  });

  test("correctly decodes multi-byte UTF-8 in token payloads without truncation", () => {
    const payload = {
      sub: "user-unicode-1",
      name: "Максим René 田中 🚀✨",
      email: "max.rene@example.org",
      symbols: "∑(x² + y²) = 1 / π",
    };

    const json = JSON.stringify(payload);
    const bytes = new TextEncoder().encode(json);
    let binary = "";
    for (let i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    const base64Url = btoa(binary)
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
    const token = `eyJhbGciOiJSUzI1NiJ9.${base64Url}.fakeSignature`;

    const parsed = parseJwtPayload(token);
    assert.deepStrictEqual(parsed, payload);
    assert.strictEqual(parsed.name, "Максим René 田中 🚀✨");
  });

  test("handles invalid UTF-8 byte sequences gracefully without uncaught URIError", () => {
    // Construct base64 of bytes that form invalid UTF-8 (e.g. 0xFF 0xFE or truncated UTF-8 lead byte)
    const invalidUtf8Binary = String.fromCharCode(0xff, 0xfe, 0xc3); // 0xC3 with no continuation byte
    const base64Url = btoa(invalidUtf8Binary)
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
    const token = `header.${base64Url}.sig`;

    // Should catch URIError and return null without throwing
    const result = parseJwtPayload(token);
    assert.strictEqual(result, null);
  });

  test("base64url padding lengths (1, 2, 3 remainder bytes) are correctly handled", () => {
    for (const len of [10, 11, 12, 13, 14, 15, 16]) {
      const obj = { k: "x".repeat(len) };
      const b64 = Buffer.from(JSON.stringify(obj)).toString("base64url");
      const token = `head.${b64}.sig`;
      const parsed = parseJwtPayload(token);
      assert.deepStrictEqual(parsed, obj, `Failed for payload length ${len}`);
    }
  });

  test("resists prototype pollution attacks in claims", () => {
    const maliciousPayload = JSON.stringify({
      __proto__: { polluted: true },
      sub: "attacker",
    });
    const b64 = Buffer.from(maliciousPayload).toString("base64url");
    const token = `head.${b64}.sig`;
    const parsed = parseJwtPayload(token);

    assert.ok(parsed);
    assert.strictEqual(
      {}.polluted,
      undefined,
      "Object.prototype must not be polluted",
    );
  });

  test("handles oversized payload (100KB) within acceptable performance limits", () => {
    const bigString = "A".repeat(100 * 1024);
    const payload = { sub: "big-user", data: bigString };
    const b64 = Buffer.from(JSON.stringify(payload)).toString("base64url");
    const token = `head.${b64}.sig`;

    const start = performance.now();
    const parsed = parseJwtPayload(token);
    const duration = performance.now() - start;

    assert.ok(parsed);
    assert.strictEqual(parsed.data.length, 100 * 1024);
    assert.ok(
      duration < 200,
      `Parsing 100KB payload took too long: ${duration}ms`,
    );
  });
});

describe("Adversarial Suite 4: User Profile Extraction Edge Cases & Flaws", () => {
  test("handles missing or omitted claims with safe fallbacks", () => {
    const u1 = extractUserFromClaims({ sub: "u-1" });
    assert.strictEqual(u1.email, "");
    assert.strictEqual(u1.name, "User");
    assert.strictEqual(u1.provider, "password");

    const u2 = extractUserFromClaims({ email: "singleworduser" });
    assert.strictEqual(u2.name, "singleworduser");

    const u3 = extractUserFromClaims({ email: "user@domain.com" });
    assert.strictEqual(u3.name, "user");
  });

  test("behavior on empty name claim", () => {
    // When name is explicitly empty string, nullish coalescing keeps ''
    const u = extractUserFromClaims({ email: "user@domain.com", name: "" });
    assert.strictEqual(u.name, "");
    assert.strictEqual(u.email, "user@domain.com");
  });

  test("Google provider detection and empirical evaluation of Boolean([]) behavior", () => {
    // 1. Standard Cognito Google IdP identities claim
    const c1 = extractUserFromClaims({
      sub: "sub-1",
      email: "google@gmail.com",
      identities: [{ providerName: "Google", providerType: "Google" }],
    });
    assert.strictEqual(c1.provider, "google");

    // 2. Google prefixed sub
    const c2 = extractUserFromClaims({
      sub: "Google_1092837465",
      email: "google2@gmail.com",
    });
    assert.strictEqual(c2.provider, "google");

    // 3. Cognito native user pool without identities claim -> correctly evaluates to password
    const c3 = extractUserFromClaims({
      sub: "b2f67623-6401-70e1-6453-2bf576c6c747",
      email: "native@example.com",
    });
    assert.strictEqual(c3.provider, "password");

    // 4. Empirical demonstration of Boolean([]) quirk:
    // If an identities array is present but empty ([]), Boolean([]) is true in JS, so provider becomes 'google'
    const c4 = extractUserFromClaims({
      sub: "sub-4",
      email: "test@example.com",
      identities: [],
    });
    assert.strictEqual(
      c4.provider,
      "google",
      "Empirical confirmation: Boolean([]) causes empty array to evaluate as truthy",
    );
  });
});

describe("Adversarial Suite 5: Network Error & Token Exchange Simulation", () => {
  function createMockStorage() {
    const local = new Map();
    const session = new Map();
    return {
      localStorage: {
        getItem: (k) => local.get(k) ?? null,
        setItem: (k, v) => local.set(k, String(v)),
        removeItem: (k) => local.delete(k),
      },
      sessionStorage: {
        getItem: (k) => session.get(k) ?? null,
        setItem: (k, v) => session.set(k, String(v)),
        removeItem: (k) => session.delete(k),
      },
    };
  }

  test("handles network timeout / connection abort during code exchange", async () => {
    const storage = createMockStorage();
    storage.sessionStorage.setItem("meetings.pkce_verifier", "test-verifier");

    const mockFetch = async () => {
      throw new Error("Network request timed out");
    };

    await assert.rejects(
      async () => {
        await simulateExchangeAuthCode({
          code: "test-auth-code",
          verifier: "test-verifier",
          mockFetch,
          storage,
        });
      },
      {
        name: "Error",
        message: "Network request timed out",
      },
    );
  });

  test("handles Cognito HTTP 400 with structured OAuth error description", async () => {
    const storage = createMockStorage();
    const mockFetch = async () => ({
      ok: false,
      status: 400,
      json: async () => ({
        error: "invalid_grant",
        error_description: "Authorization code has expired",
      }),
    });

    await assert.rejects(
      async () => {
        await simulateExchangeAuthCode({
          code: "expired-code",
          verifier: "verifier-xyz",
          mockFetch,
          storage,
        });
      },
      {
        name: "Error",
        message: "Authorization code has expired",
      },
    );
  });

  test("handles Cognito HTTP 400 with raw error when description is missing", async () => {
    const storage = createMockStorage();
    const mockFetch = async () => ({
      ok: false,
      status: 400,
      json: async () => ({ error: "invalid_grant" }),
    });

    await assert.rejects(
      async () => {
        await simulateExchangeAuthCode({
          code: "bad-code",
          verifier: "verifier-xyz",
          mockFetch,
          storage,
        });
      },
      {
        name: "Error",
        message: "invalid_grant",
      },
    );
  });

  test("handles non-JSON error response (e.g. 502 Bad Gateway / CloudFront HTML error)", async () => {
    const storage = createMockStorage();
    const mockFetch = async () => ({
      ok: false,
      status: 502,
      json: async () => {
        throw new SyntaxError("Unexpected token < in JSON at position 0");
      },
    });

    await assert.rejects(
      async () => {
        await simulateExchangeAuthCode({
          code: "code-502",
          verifier: "verifier",
          mockFetch,
          storage,
        });
      },
      {
        name: "Error",
        message: "Token exchange failed",
      },
    );
  });

  test("fails if Cognito 200 response lacks id_token", async () => {
    const storage = createMockStorage();
    storage.sessionStorage.setItem("meetings.pkce_verifier", "verifier");
    const mockFetch = async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        access_token: "mock-access-token",
        expires_in: 3600,
      }),
    });

    await assert.rejects(
      async () => {
        await simulateExchangeAuthCode({
          code: "code",
          verifier: "verifier",
          mockFetch,
          storage,
        });
      },
      {
        name: "Error",
        message: "No ID token received from authentication server",
      },
    );

    // PKCE verifier must have been cleared from sessionStorage
    assert.strictEqual(
      storage.sessionStorage.getItem("meetings.pkce_verifier"),
      null,
    );
  });

  test("fails if id_token claims cannot be parsed", async () => {
    const storage = createMockStorage();
    const mockFetch = async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        id_token: "header.not-json-payload.sig",
        access_token: "access-token",
      }),
    });

    await assert.rejects(
      async () => {
        await simulateExchangeAuthCode({
          code: "code",
          verifier: "verifier",
          mockFetch,
          storage,
        });
      },
      {
        name: "Error",
        message: "Failed to parse ID token claims",
      },
    );
  });

  test("successfully stores tokens and returns user on valid exchange", async () => {
    const storage = createMockStorage();
    storage.sessionStorage.setItem("meetings.pkce_verifier", "verifier-abc");

    const payload = {
      sub: "user-1234",
      email: "alex@example.com",
      name: "Alex Dev",
    };
    const b64 = Buffer.from(JSON.stringify(payload)).toString("base64url");
    const idToken = `header.${b64}.signature`;

    const mockFetch = async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        id_token: idToken,
        access_token: "access-123",
        refresh_token: "refresh-123",
      }),
    });

    const user = await simulateExchangeAuthCode({
      code: "valid-code",
      verifier: "verifier-abc",
      mockFetch,
      storage,
    });

    assert.strictEqual(user.email, "alex@example.com");
    assert.strictEqual(user.name, "Alex Dev");
    assert.strictEqual(user.provider, "password");

    assert.strictEqual(
      storage.localStorage.getItem("meetings.id_token"),
      idToken,
    );
    assert.strictEqual(
      storage.localStorage.getItem("meetings.access_token"),
      "access-123",
    );
    assert.strictEqual(
      storage.localStorage.getItem("meetings.refresh_token"),
      "refresh-123",
    );
    assert.strictEqual(
      storage.sessionStorage.getItem("meetings.pkce_verifier"),
      null,
    );
  });
});

describe("Adversarial Suite 6: Domain & Redirect URI Sanitization Edge Cases", () => {
  test("cleanDomain normalizes diverse malicious and messy inputs", () => {
    assert.strictEqual(
      cleanDomain("   https://auth.example.com///   "),
      "auth.example.com",
    );
    assert.strictEqual(
      cleanDomain("http://auth.example.com"),
      "auth.example.com",
    );
    assert.strictEqual(
      cleanDomain("https://auth.example.com:443/"),
      "auth.example.com:443",
    );
    assert.strictEqual(cleanDomain("auth.example.com"), "auth.example.com");
  });

  test("redirect_uri handles unusual port numbers, paths, and query string neutrality", () => {
    const origin = "http://localhost:5173";
    const redirectUri = `${origin}/login`;
    const encoded = encodeURIComponent(redirectUri);

    assert.strictEqual(encoded, "http%3A%2F%2Flocalhost%3A5173%2Flogin");
    assert.strictEqual(decodeURIComponent(encoded), redirectUri);
  });
});
