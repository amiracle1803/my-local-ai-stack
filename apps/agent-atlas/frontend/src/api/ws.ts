/**
 * WebSocket client — connects to /ws on the backend.
 * Works for local dev (via Vite proxy) and cloud deployment (same host).
 * Features: auto-reconnect with exponential backoff, connection state, typed events.
 */
type Listener = (event: Record<string, unknown>) => void;
type StateListener = (state: WSState) => void;

export type WSState = "connecting" | "open" | "closed";

class WSClient {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private stateListeners = new Set<StateListener>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private stopped = false;
  public state: WSState = "closed";

  private setState(s: WSState) {
    this.state = s;
    this.stateListeners.forEach((fn) => fn(s));
  }

  connect() {
    if (this.stopped) return;
    if (this.ws && this.ws.readyState < WebSocket.CLOSING) return;

    this.setState("connecting");
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${window.location.host}/ws`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.setState("open");
    };

    this.ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as Record<string, unknown>;
        this.listeners.forEach((fn) => fn(data));
      } catch {
        // ignore malformed messages
      }
    };

    this.ws.onclose = () => {
      this.setState("closed");
      if (!this.stopped) {
        // Exponential backoff: 1s, 2s, 4s, 8s … capped at 30s
        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30_000);
        this.reconnectAttempts++;
        this.reconnectTimer = setTimeout(() => this.connect(), delay);
      }
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  onStateChange(fn: StateListener): () => void {
    this.stateListeners.add(fn);
    return () => this.stateListeners.delete(fn);
  }

  ping() {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send("ping");
    }
  }

  disconnect() {
    this.stopped = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
    this.setState("closed");
  }

  reconnect() {
    this.stopped = false;
    this.reconnectAttempts = 0;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
    this.connect();
  }
}

export const wsClient = new WSClient();
