// AgentRouter relay with Claude Code spoof-header injection.
// Forwards ALL requests to https://agentrouter.org from Cloudflare egress IP
// (bypasses Aliyun WAF 405 block) and injects the spoof headers AgentRouter
// requires for auth (401 unauthorized_client_detected without them).
//
// v3 (18 Aug 2026): absorbs upstream 429 (AWS Bedrock ThrottlingException) with
// bounded retry+backoff. AgentRouter retries 3x internally then returns 429;
// the throttle window usually clears within a few seconds, so one or two
// retries here turn a hard failure into a successful response.
const MAX_ATTEMPTS = 3;
const BACKOFF_MS = [500, 1500]; // sleeps before attempt 2 and 3

export default {
  async fetch(request) {
    const url = new URL(request.url);

    // health check for local debugging
    if (url.pathname === "/" || url.pathname === "/health") {
      return new Response(JSON.stringify({ status: "ok", proxy: "agentrouter", spoof: "v3", retries: MAX_ATTEMPTS - 1 }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    const targetUrl = "https://agentrouter.org" + url.pathname + url.search;
    const headers = new Headers(request.headers);

    // clean CF-specific headers
    headers.delete("cf-connecting-ip");
    headers.delete("cf-ipcountry");
    headers.delete("cf-ray");
    headers.delete("cf-visitor");
    headers.delete("x-forwarded-for");
    headers.delete("x-forwarded-proto");
    headers.delete("x-real-ip");

    // --- Claude Code spoof headers (required by AgentRouter auth) ---
    headers.set("User-Agent", "claude-cli/2.1.92 (external, sdk-cli)");
    headers.set("Anthropic-Version", "2023-06-01");
    headers.set("Anthropic-Beta", "claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14,context-management-2025-06-27,prompt-caching-scope-2026-01-05,advanced-tool-use-2025-11-20,effort-2025-11-24,structured-outputs-2025-12-15,fast-mode-2026-02-01,token-efficient-tools-2026-03-28");
    headers.set("Anthropic-Dangerous-Direct-Browser-Access", "true");
    headers.set("X-App", "cli");
    headers.set("X-Stainless-Helper-Method", "messages.create");
    headers.set("X-Stainless-Retry-Count", "0");
    headers.set("X-Stainless-Runtime-Version", "v2.1.92");
    headers.set("X-Stainless-Package-Version", "2.1.92");
    headers.set("X-Stainless-Runtime", "node");
    headers.set("X-Stainless-Lang", "js");
    headers.set("X-Stainless-Arch", "x64");
    headers.set("X-Stainless-Os", "Linux");
    headers.set("X-Stainless-Timeout", "600");

    // Buffer the body so we can re-send it on retry. Chat payloads are small
    // (a few KB); this stays well within memory limits.
    let body = null;
    if (request.method !== "GET" && request.method !== "HEAD") {
      body = new Uint8Array(await request.arrayBuffer());
    }

    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
      const init = { method: request.method, headers };
      if (body) init.body = body;

      let resp;
      try {
        resp = await fetch(targetUrl, init);
      } catch (e) {
        // network-level failure — retry if we have attempts left
        if (attempt < MAX_ATTEMPTS - 1) {
          await sleep(BACKOFF_MS[attempt] || 1500);
          continue;
        }
        return new Response(JSON.stringify({ error: e.message }), {
          status: 502,
          headers: { "Content-Type": "application/json" },
        });
      }

      // Absorb transient 429s (rate limit). Respect Retry-After when present,
      // clamped so we never exceed the Workers wall-clock budget.
      if (resp.status === 429 && attempt < MAX_ATTEMPTS - 1) {
        const retryAfter = parseFloat(resp.headers.get("retry-after") || "");
        let delay = BACKOFF_MS[attempt] || 1500;
        if (!Number.isNaN(retryAfter) && retryAfter > 0) {
          delay = Math.min(retryAfter * 1000, 3000);
        }
        await sleep(delay);
        continue;
      }

      // Not retryable — pass through (including final 429 after attempts).
      const respHeaders = new Headers(resp.headers);
      respHeaders.set("Access-Control-Allow-Origin", "*");
      respHeaders.set("X-AgentRouter-Retries", String(attempt));
      respHeaders.delete("content-encoding");
      respHeaders.delete("content-length");
      respHeaders.delete("transfer-encoding");
      const contentType = resp.headers.get("content-type") || "";
      if (contentType.includes("text/event-stream") && resp.body) {
        // AgentRouter occasionally emits `data: null`, which the OpenAI SDK
        // parses as a null chunk and Hermes then dereferences as `choices`.
        const decoder = new TextDecoder();
        const encoder = new TextEncoder();
        let pending = "";
        const filtered = new TransformStream({
          transform(chunk, controller) {
            pending += decoder.decode(chunk, { stream: true });
            const lines = pending.split("\n");
            pending = lines.pop() || "";
            for (const line of lines) {
              if (line.trim() === "data: null") continue;
              controller.enqueue(encoder.encode(line + "\n"));
            }
          },
          flush(controller) {
            pending += decoder.decode();
            if (pending && pending.trim() !== "data: null") {
              controller.enqueue(encoder.encode(pending));
            }
          },
        });
        respHeaders.set("content-type", contentType);
        return new Response(resp.body.pipeThrough(filtered), {
          status: resp.status,
          headers: respHeaders,
        });
      }
      return new Response(resp.body, {
        status: resp.status,
        headers: respHeaders,
      });
    }
  },
};
