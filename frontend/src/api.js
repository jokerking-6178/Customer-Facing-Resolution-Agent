/** SSE client for POST /api/chat (fetch + manual stream parsing). */

export async function streamChat(
  { sessionId, customerId, message, signal },
  handlers
) {
  let res;
  try {
    res = await fetch("/api/chat", {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId || null,
        customer_id: customerId,
        message,
      }),
    });
  } catch (e) {
    if (e.name === "AbortError") return;
    handlers.error?.({ detail: "Could not reach the server." });
    return;
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    // Always hand the caller the same shape the SSE `error` frame uses.
    handlers.error?.({ detail: err.detail || res.statusText || "Request failed" });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let event = "message";
        let data = "";
        for (const line of frame.split("\n")) {
          if (line.startsWith("event: ")) event = line.slice(7).trim();
          else if (line.startsWith("data: ")) data += line.slice(6);
        }
        if (!data) continue;
        try {
          handlers[event]?.(JSON.parse(data));
        } catch {
          /* skip malformed frame */
        }
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") {
      handlers.error?.({ detail: "The connection dropped mid-reply." });
    }
  } finally {
    try {
      reader.cancel();
    } catch {
      /* already closed */
    }
  }
}

export async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`GET ${url} failed`);
  return res.json();
}
