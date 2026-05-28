(function () {
  const config = window.PAPERLENS_CONFIG || {};
  const baseUrl = (config.API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

  function createSupabaseClient() {
    if (!window.supabase || !config.SUPABASE_URL || !config.SUPABASE_ANON_KEY) {
      return null;
    }
    return window.supabase.createClient(config.SUPABASE_URL, config.SUPABASE_ANON_KEY);
  }

  function getAuthClient() {
    if (!window.PaperLensAuth) {
      window.PaperLensAuth = createSupabaseClient();
    }
    return window.PaperLensAuth;
  }

  async function getSessionToken(client) {
    client = client || getAuthClient();
    if (!client) return null;
    const { data } = await client.auth.getSession();
    return data && data.session ? data.session.access_token : null;
  }

  async function request(path, options = {}) {
    const token = await getSessionToken();
    const headers = new Headers(options.headers || {});
    if (!headers.has("Content-Type") && options.body && !(options.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }

    const response = await fetch(`${baseUrl}${path}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      let message = `Request failed with ${response.status}`;
      try {
        const errorBody = await response.json();
        message = errorBody.detail || errorBody.message || message;
      } catch (_) {
        message = await response.text() || message;
      }
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return response.json();
  }

  async function stream(path, payload, onToken) {
    const token = await getSessionToken();
    const headers = new Headers({ "Content-Type": "application/json" });
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }

    const response = await fetch(`${baseUrl}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });

    if (!response.ok || !response.body) {
      throw new Error(`Stream failed with ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalText = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const frames = buffer.split("\n\n");
      buffer = frames.pop() || "";

      for (const frame of frames) {
        const line = frame.split("\n").find((item) => item.startsWith("data: "));
        if (!line) continue;
        const event = JSON.parse(line.slice(6));
        if (event.type === "token") {
          finalText += event.text;
          onToken(event.text, finalText);
        }
        if (event.type === "error") {
          throw new Error(event.message || "Chat stream failed");
        }
      }
    }

    return finalText;
  }

  window.PaperLensAuth = createSupabaseClient();
  window.PaperLensGetAuthClient = getAuthClient;
  window.PaperLensAPI = {
    baseUrl,
    getSessionToken: () => getSessionToken(),
    getUsage: () => request("/api/usage"),
    listThreads: () => request("/api/peeler/threads"),
    getThread: (threadId) => request(`/api/peeler/threads/${threadId}`),
    resolvePaper: (input, inputType, options = {}) => request("/api/peeler/resolve", {
      method: "POST",
      body: JSON.stringify({ input, input_type: inputType || "auto" }),
      signal: options.signal,
    }),
    uploadPdf: (file, options = {}) => {
      const body = new FormData();
      body.append("file", file);
      return request("/api/peeler/upload", { method: "POST", body, signal: options.signal });
    },
    createJob: (paper) => request("/api/peeler/jobs", {
      method: "POST",
      body: JSON.stringify({ paper }),
    }),
    getJob: (jobId) => request(`/api/peeler/jobs/${jobId}`),
    streamChat: (threadId, question, onToken) => stream(
      `/api/peeler/threads/${threadId}/chat/stream`,
      { question },
      onToken
    ),
  };
})();
