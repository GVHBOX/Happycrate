const port = process.argv[2] || "9222";
const expression = process.argv[3];
if (!expression) {
  console.error("用法: node tools/cdp_eval.mjs <端口> <要执行的 JS 表达式>");
  process.exit(2);
}

const response = await fetch(`http://127.0.0.1:${port}/json`);
const targets = await response.json();
const page = targets.find((t) => t.type === "page");
if (!page) {
  console.error("没有找到页面目标，实际拿到:", JSON.stringify(targets.map((t) => t.type)));
  process.exit(3);
}

const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

const reply = await new Promise((resolve) => {
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id === 1) resolve(message);
  });
  socket.send(
    JSON.stringify({
      id: 1,
      method: "Runtime.evaluate",
      params: { expression, awaitPromise: true, returnByValue: true },
    }),
  );
});

socket.close();

if (reply.result?.exceptionDetails) {
  console.error("页面里抛异常:", JSON.stringify(reply.result.exceptionDetails, null, 2));
  process.exit(4);
}

const value = reply.result?.result?.value;
console.log(typeof value === "string" ? value : JSON.stringify(value, null, 2));
