const HEARTBEAT_INTERVAL_MS = 15_000;
const TAB_KEY = "catalyst-tab-id";

function tabId(): string {
  const current = sessionStorage.getItem(TAB_KEY);
  if (current) return current;
  const created = crypto.randomUUID().replaceAll("-", "_");
  sessionStorage.setItem(TAB_KEY, created);
  return created;
}

async function post(path: string, id: string): Promise<void> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tab_id: id }),
    keepalive: true,
  });
  if (!response.ok) throw new Error(`Lifecycle request failed: ${response.status}`);
}

export function startLifecycleHeartbeat(): () => void {
  const id = tabId();
  let stopped = false;

  const beat = () => {
    if (!stopped) void post("/api/lifecycle/heartbeat", id).catch(() => undefined);
  };
  beat();
  const timer = window.setInterval(beat, HEARTBEAT_INTERVAL_MS);

  const goodbye = () => {
    if (stopped) return;
    stopped = true;
    window.clearInterval(timer);
    const body = new Blob([JSON.stringify({ tab_id: id })], { type: "application/json" });
    navigator.sendBeacon("/api/lifecycle/goodbye", body);
  };
  window.addEventListener("pagehide", goodbye, { once: true });

  return () => {
    window.removeEventListener("pagehide", goodbye);
    goodbye();
  };
}
