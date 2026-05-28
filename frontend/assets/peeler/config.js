(function () {
  const host = window.location.hostname;
  const isLocal = host === "localhost" || host === "127.0.0.1" || host === "";
  const storedApi = window.localStorage.getItem("PAPERLENS_API_BASE_URL");
  const storedSupabaseUrl = window.localStorage.getItem("PAPERLENS_SUPABASE_URL");
  const storedSupabaseAnon = window.localStorage.getItem("PAPERLENS_SUPABASE_ANON_KEY");

  const localApiBase = host === "127.0.0.1" ? "http://127.0.0.1:8000" : "http://localhost:8000";

  window.PAPERLENS_CONFIG = {
    API_BASE_URL: storedApi || (isLocal ? localApiBase : window.location.origin),
    SUPABASE_URL: storedSupabaseUrl || "",
    SUPABASE_ANON_KEY: storedSupabaseAnon || "",
  };
})();
