/* factory-office · data client: token, GET /state, the /stream of events, GET /events.
 * It knows HTTP and nothing about drawing; office.js (or a future Phaser scene) subscribes. */
(function (root) {
  "use strict";
  const KEY = "factory-office.token";

  function readToken() {
    try { return root.localStorage.getItem(KEY) || ""; } catch (e) { return ""; }
  }
  function writeToken(value) {
    try {
      if (value) root.localStorage.setItem(KEY, value); else root.localStorage.removeItem(KEY);
    } catch (e) { /* private mode: the token lives only in memory */ }
  }

  class AuthError extends Error {}

  class OfficeClient {
    /* handlers: onState(state), onMessage(msg), onStatus('connecting'|'live'|'retrying'|'auth'), */
    constructor(handlers) {
      this.h = handlers;
      this.token = readToken();
      /* A link like /#token=… signs in once; the token is moved to storage and removed from the URL. */
      const m = (root.location.hash || "").match(/(?:^#|&)token=([^&]+)/);
      if (m) {
        this.token = decodeURIComponent(m[1]);
        writeToken(this.token);
        root.history.replaceState(null, "", root.location.pathname + root.location.search);
      }
      this.seq = 0;
      this.abort = null;
      this.retry = 1000;
      this.running = false;
    }

    setToken(value) { this.token = value.trim(); writeToken(this.token); }
    forget() { this.stop(); this.token = ""; writeToken(""); this.h.onStatus("auth"); }

    async request(path) {
      const res = await fetch(path, {
        headers: { Authorization: "Bearer " + this.token },
        cache: "no-store",
        signal: this.abort ? this.abort.signal : undefined
      });
      if (res.status === 401 || res.status === 403) throw new AuthError("token rejected");
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res;
    }

    async fetchEvents(params) {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v != null && v !== "") q.set(k, String(v));
      const res = await this.request("/events?" + q.toString());
      return (await res.json()).events;
    }

    start() {
      if (!this.token) { this.h.onStatus("auth"); return; }
      this.stop();
      this.running = true;
      this.loop();
    }

    stop() {
      this.running = false;
      if (this.abort) this.abort.abort();
      this.abort = null;
    }

    async loop() {
      while (this.running) {
        this.abort = new AbortController();
        try {
          this.h.onStatus("connecting");
          const state = await (await this.request("/state")).json();
          this.seq = state.seq || 0;
          this.h.onState(state);
          await this.stream();
        } catch (err) {
          if (!this.running) return;
          if (err instanceof AuthError) { this.running = false; this.h.onStatus("auth"); return; }
        }
        if (!this.running) return;
        this.h.onStatus("retrying");
        await new Promise(r => setTimeout(r, this.retry));
        this.retry = Math.min(this.retry * 2, 15000);
      }
    }

    async stream() {
      const res = await this.request("/stream?after=" + this.seq);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      this.h.onStatus("live");
      this.retry = 1000;
      for (;;) {
        const { value, done } = await reader.read();
        if (done) return;
        buffer += decoder.decode(value, { stream: true });
        const parsed = root.OfficeModel.parseSSE(buffer);
        buffer = parsed.rest;
        for (const m of parsed.messages) {
          let msg;
          try { msg = JSON.parse(m.data); } catch (e) { continue; }
          if (msg.event && msg.event.seq <= this.seq) continue;
          if (msg.event) this.seq = msg.event.seq;
          this.h.onMessage(msg);
        }
      }
    }
  }

  root.OfficeClient = OfficeClient;
})(self);
