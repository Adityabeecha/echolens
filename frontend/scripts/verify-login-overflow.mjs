const endpoint = process.env.ECHOLENS_CDP || "http://127.0.0.1:9223";
const appUrl = process.env.ECHOLENS_APP_URL || "http://127.0.0.1:5173/";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function openTarget(url) {
  const response = await fetch(`${endpoint}/json/new?${encodeURIComponent(url)}`, { method: "PUT" });
  if (!response.ok) throw new Error(`Could not open browser target: ${response.status}`);
  return response.json();
}

function connect(webSocketDebuggerUrl) {
  const socket = new WebSocket(webSocketDebuggerUrl);
  const pending = new Map();
  let sequence = 0;

  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data);
    if (!message.id) return;
    const entry = pending.get(message.id);
    if (!entry) return;
    pending.delete(message.id);
    if (message.error) entry.reject(new Error(message.error.message));
    else entry.resolve(message.result);
  };

  const ready = new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = () => reject(new Error("Could not connect to Chrome DevTools Protocol"));
  });

  return {
    ready,
    send(method, params = {}) {
      const id = ++sequence;
      socket.send(JSON.stringify({ id, method, params }));
      return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
    },
    close() { socket.close(); },
  };
}

const target = await openTarget(appUrl);
const client = connect(target.webSocketDebuggerUrl);
await client.ready;

try {
  await client.send("Page.enable");
  await client.send("Runtime.enable");
  await client.send("Network.enable");
  await client.send("Network.setBlockedURLs", {
    urls: ["*://fonts.googleapis.com/*", "*://fonts.gstatic.com/*"],
  });
  await client.send("Page.addScriptToEvaluateOnNewDocument", {
    source: `window.__loginQaErrors = [];
      addEventListener('error', (event) => window.__loginQaErrors.push(event.message));
      addEventListener('unhandledrejection', (event) => window.__loginQaErrors.push(String(event.reason)));`,
  });
  await client.send("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 320,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await client.send("Page.reload", { ignoreCache: true });
  let rendered = false;
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const probe = await client.send("Runtime.evaluate", {
      returnByValue: true,
      expression: "Boolean(document.querySelector('.el-login-form'))",
    });
    if (probe.result.value) {
      rendered = true;
      break;
    }
    await sleep(250);
  }
  if (!rendered) {
    const diagnostic = await client.send("Runtime.evaluate", {
      returnByValue: true,
      expression: `({
        url: location.href,
        title: document.title,
        readyState: document.readyState,
        root: document.querySelector('#root')?.innerHTML.slice(0, 240),
        errors: window.__loginQaErrors,
        resources: performance.getEntriesByType('resource').map((entry) => entry.name).slice(-8),
      })`,
    });
    throw new Error(`Login form was not rendered: ${JSON.stringify(diagnostic.result.value)}`);
  }

  const evaluation = await client.send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const form = document.querySelector('.el-login-form');
      if (!form) return { error: 'Login form was not rendered' };
      const content = form.querySelector('.el-login-form-content') || form.firstElementChild;
      const actions = form.querySelectorAll('button, input, a[href]');
      const lastAction = actions[actions.length - 1];
      const initialForm = form.getBoundingClientRect();
      const initialContent = content?.getBoundingClientRect();
      const overflowY = getComputedStyle(form).overflowY;
      const scrollRange = form.scrollHeight - form.clientHeight;
      form.scrollTop = form.scrollHeight;
      const finalAction = lastAction?.getBoundingClientRect();
      const finalForm = form.getBoundingClientRect();
      return {
        overflowY,
        scrollRange,
        scrollTop: form.scrollTop,
        topReachable: !!initialContent && initialContent.top >= initialForm.top - 1,
        finalActionReachable: !!finalAction && finalAction.bottom <= finalForm.bottom + 1,
      };
    })()`,
  });

  const result = evaluation.result.value;
  if (result.error) throw new Error(result.error);
  if (!['auto', 'scroll'].includes(result.overflowY)) {
    throw new Error(`Login form must scroll vertically; overflow-y is ${result.overflowY}`);
  }
  if (result.scrollRange <= 0) throw new Error("Short viewport did not exercise login overflow");
  if (!result.topReachable) throw new Error("Centered login content is clipped above the viewport");
  if (result.scrollTop < result.scrollRange - 1 || !result.finalActionReachable) {
    throw new Error("The final login action is not reachable by scrolling");
  }

  console.log("Login overflow behavior verified at 390x320.");
} finally {
  client.close();
}
