(function () {
  const host = window.location.hostname;
  const isLocal = host === "localhost" || host === "127.0.0.1" || host === "";
  const storedApi = window.localStorage.getItem("PAPERLENS_API_BASE_URL");
  const storedSupabaseUrl = window.localStorage.getItem("PAPERLENS_SUPABASE_URL");
  const storedSupabaseAnon = window.localStorage.getItem("PAPERLENS_SUPABASE_ANON_KEY");

  const localApiBase = host === "127.0.0.1" ? "http://127.0.0.1:8000" : "http://localhost:8000";
  const defaultSupabaseUrl = "https://tzzleyysodusezlpttcl.supabase.co";
  const defaultSupabaseAnon = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InR6emxleXlzb2R1c2V6bHB0dGNsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3ODM3NDYsImV4cCI6MjA5NTM1OTc0Nn0.JuKKiPc1j-XM3Clj6P-eqYUHNP6ek3BZXCOWjIdvG6Q";

  window.PAPERLENS_CONFIG = {
    API_BASE_URL: storedApi || (isLocal ? localApiBase : "https://paperlens-mvp.onrender.com"),
    SUPABASE_URL: storedSupabaseUrl || defaultSupabaseUrl,
    SUPABASE_ANON_KEY: storedSupabaseAnon || defaultSupabaseAnon,
  };
})();
