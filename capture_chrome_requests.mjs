import fs from "node:fs";
import path from "node:path";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseArgs(argv) {
  const args = {
    port: 9222,
    out: "captures/portal_capture.jsonl",
    targetHint: "portal.csu.edu.cn",
    maxIdleSeconds: 900,
  };

  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i];
    const value = argv[i + 1];
    if (key === "--port" && value) {
      args.port = Number(value);
      i += 1;
    } else if (key === "--out" && value) {
      args.out = value;
      i += 1;
    } else if (key === "--target-hint" && value) {
      args.targetHint = value;
      i += 1;
    } else if (key === "--max-idle-seconds" && value) {
      args.maxIdleSeconds = Number(value);
      i += 1;
    }
  }

  return args;
}

const args = parseArgs(process.argv);
const outPath = path.resolve(args.out);
fs.mkdirSync(path.dirname(outPath), { recursive: true });
const out = fs.createWriteStream(outPath, { flags: "a" });

function safeStringify(record) {
  return JSON.stringify(record)
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

function writeRecord(record) {
  out.write(`${safeStringify(record)}\n`);
}

function sanitizeUrl(url) {
  try {
    return new URL(url);
  } catch {
    return null;
  }
}

function isRelevantUrl(url) {
  return typeof url === "string" && url.includes("portal.csu.edu.cn");
}

function summarizeUrl(url) {
  const parsed = sanitizeUrl(url);
  if (!parsed) {
    return { url };
  }

  const query = {};
  for (const [key, value] of parsed.searchParams.entries()) {
    query[key] = value;
  }

  return {
    url,
    path: parsed.pathname,
    query,
  };
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${url}`);
  }
  return response.json();
}

async function waitForTarget() {
  const endpoint = `http://127.0.0.1:${args.port}/json/list`;
  for (;;) {
    try {
      const targets = await fetchJson(endpoint);
      const found = targets.find(
        (target) =>
          target.type === "page" &&
          typeof target.url === "string" &&
          target.url.includes(args.targetHint) &&
          target.webSocketDebuggerUrl,
      );
      if (found) {
        return found;
      }
    } catch {
      // Chrome may not be ready yet.
    }
    await sleep(1000);
  }
}

async function main() {
  writeRecord({
    event: "meta",
    time: new Date().toISOString(),
    message: "capture_started",
    port: args.port,
    targetHint: args.targetHint,
  });

  const target = await waitForTarget();
  writeRecord({
    event: "meta",
    time: new Date().toISOString(),
    message: "target_attached",
    targetId: target.id,
    targetUrl: target.url,
  });

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  const pending = new Map();
  const tracked = new Map();
  let nextId = 1;
  let lastActivity = Date.now();

  function send(method, params = {}) {
    const id = nextId;
    nextId += 1;
    ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject, method });
    });
  }

  function handleRequest(event) {
    const params = event.params;
    const request = params?.request ?? {};
    if (!isRelevantUrl(request.url)) {
      return;
    }

    lastActivity = Date.now();
    tracked.set(params.requestId, {
      requestId: params.requestId,
      url: request.url,
      method: request.method,
    });
    writeRecord({
      event: "request",
      time: new Date().toISOString(),
      requestId: params.requestId,
      method: request.method,
      hasPostData: Boolean(request.hasPostData),
      postData: request.postData ?? "",
      requestHeaders: {
        "content-type": request.headers?.["Content-Type"] ?? request.headers?.["content-type"] ?? "",
        referer: request.headers?.Referer ?? request.headers?.referer ?? "",
        origin: request.headers?.Origin ?? request.headers?.origin ?? "",
      },
      initiatorType: params.initiator?.type ?? "",
      ...summarizeUrl(request.url),
    });
  }

  function handleResponse(event) {
    const params = event.params;
    const trackedRequest = tracked.get(params?.requestId);
    if (!trackedRequest) {
      return;
    }

    lastActivity = Date.now();
    writeRecord({
      event: "response",
      time: new Date().toISOString(),
      requestId: params.requestId,
      url: trackedRequest.url,
      status: params.response?.status,
      mimeType: params.response?.mimeType,
      responseHeaders: {
        "content-type":
          params.response?.headers?.["Content-Type"] ??
          params.response?.headers?.["content-type"] ??
          "",
      },
    });
  }

  async function handleLoadingFinished(event) {
    const params = event.params;
    const trackedRequest = tracked.get(params?.requestId);
    if (!trackedRequest) {
      return;
    }

    lastActivity = Date.now();
    try {
      const bodyResult = await send("Network.getResponseBody", {
        requestId: params.requestId,
      });
      const body = bodyResult?.body ?? "";
      writeRecord({
        event: "body",
        time: new Date().toISOString(),
        requestId: params.requestId,
        url: trackedRequest.url,
        body,
        base64Encoded: Boolean(bodyResult?.base64Encoded),
      });
    } catch (error) {
      writeRecord({
        event: "body_error",
        time: new Date().toISOString(),
        requestId: params.requestId,
        url: trackedRequest.url,
        error: String(error),
      });
    }
  }

  ws.addEventListener("open", async () => {
    try {
      await send("Network.enable");
      await send("Page.enable");
      await send("Runtime.enable");
      writeRecord({
        event: "meta",
        time: new Date().toISOString(),
        message: "domains_enabled",
      });
    } catch (error) {
      writeRecord({
        event: "fatal",
        time: new Date().toISOString(),
        error: String(error),
      });
      process.exitCode = 1;
      ws.close();
    }
  });

  ws.addEventListener("message", (raw) => {
    const payload = JSON.parse(raw.data);
    if (typeof payload.id === "number" && pending.has(payload.id)) {
      const entry = pending.get(payload.id);
      pending.delete(payload.id);
      if (payload.error) {
        entry.reject(new Error(payload.error.message || "Unknown CDP error"));
      } else {
        entry.resolve(payload.result);
      }
      return;
    }

    if (payload.method === "Network.requestWillBeSent") {
      handleRequest(payload);
    } else if (payload.method === "Network.responseReceived") {
      handleResponse(payload);
    } else if (payload.method === "Network.loadingFinished") {
      handleLoadingFinished(payload).catch((error) => {
        writeRecord({
          event: "fatal",
          time: new Date().toISOString(),
          error: String(error),
        });
      });
    }
  });

  ws.addEventListener("close", () => {
    writeRecord({
      event: "meta",
      time: new Date().toISOString(),
      message: "websocket_closed",
    });
    out.end();
    process.exit(process.exitCode ?? 0);
  });

  ws.addEventListener("error", (error) => {
    writeRecord({
      event: "fatal",
      time: new Date().toISOString(),
      error: String(error),
    });
    process.exitCode = 1;
  });

  setInterval(() => {
    if (Date.now() - lastActivity > args.maxIdleSeconds * 1000) {
      writeRecord({
        event: "meta",
        time: new Date().toISOString(),
        message: "idle_timeout",
      });
      ws.close();
    }
  }, 5000);
}

main().catch((error) => {
  writeRecord({
    event: "fatal",
    time: new Date().toISOString(),
    error: String(error),
  });
  out.end();
  process.exit(1);
});
