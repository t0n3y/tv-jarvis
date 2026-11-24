"use strict";

/* Live-Vorschau: laeuft in Fernbedienung und Fernseher (iframes) VOR deren
   eigenen Skripten. Alle Anfragen an den Pi ("/api/...") und die
   WebSocket-Verbindung des Fernsehers gehen an den simulierten Pi im
   Elternfenster (demo/server.js). Nichts verlaesst den Browser. */
(() => {
  const demo = window.parent && window.parent !== window ? window.parent.RPITV_DEMO : null;
  if (!demo) return;
  const realFetch = window.fetch.bind(window);

  window.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    const index = url.pathname.indexOf("/api/");
    if (index < 0) return realFetch(input, options);
    let body = options.body;
    if (typeof body === "string") {
      try {
        body = JSON.parse(body);
      } catch (err) {
        // kein JSON
      }
    }
    const result = await demo.handle((options.method || "GET").toUpperCase(), url.pathname.slice(index), url.searchParams, body);
    return new Response(JSON.stringify(result.json ?? null), {
      status: result.status || 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  // Fernseher: WebSocket zum Pi -> direkter Draht zum simulierten Pi
  class DemoSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.onopen = this.onmessage = this.onclose = this.onerror = null;
      const tv = /\/ws$/.test(new URL(url, location.href).pathname);
      setTimeout(() => {
        if (!tv) return; // TV-Browser-Livebild gibt es in der Vorschau nicht
        this.readyState = 1;
        demo.connectTv(this);
        if (this.onopen) this.onopen({});
      }, 50);
    }
    send(data) {
      demo.fromTv(JSON.parse(data));
    }
    deliver(message) {
      if (this.readyState === 1 && this.onmessage) this.onmessage({ data: JSON.stringify(message) });
    }
    close() {
      this.readyState = 3;
      demo.disconnectTv(this);
    }
    addEventListener(type, fn) {
      this[`on${type}`] = fn;
    }
  }
  DemoSocket.OPEN = 1;
  window.WebSocket = DemoSocket;

  // Jellyfin-Videos: freie Blender-Filme statt des Streams vom Pi
  const srcDescriptor = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, "src");
  Object.defineProperty(HTMLMediaElement.prototype, "src", {
    get() {
      return srcDescriptor.get.call(this);
    },
    set(value) {
      srcDescriptor.set.call(this, demo.mediaUrl(String(value)));
    },
  });
})();
