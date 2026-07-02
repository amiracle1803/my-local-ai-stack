export interface WsEvent {
  event: "agent_message" | "job_update";
  [key: string]: unknown;
}

type Listener = (event: WsEvent) => void;

class WsClient {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private retryMs = 1000;

  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    this.ws = new WebSocket(`${proto}//${location.host}/ws`);
    this.ws.onopen = () => { this.retryMs = 1000; };
    this.ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as WsEvent;
        this.listeners.forEach((fn) => fn(data));
      } catch {
        // ignore malformed frames
      }
    };
    this.ws.onclose = () => {
      setTimeout(() => this.connect(), this.retryMs);
      this.retryMs = Math.min(this.retryMs * 1.5, 30000);
    };
    this.ws.onerror = () => this.ws?.close();
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    this.connect();
    return () => this.listeners.delete(fn);
  }
}

export const wsClient = new WsClient();
