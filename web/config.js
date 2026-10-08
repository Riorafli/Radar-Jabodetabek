// Supabase > Project Settings > API. The anon key is safe in the browser
// ONLY because RLS is enabled (db/schema.sql). Never put the service_role key here.
// While these are placeholders the site runs in demo mode with sample data.
window.RADAR_CONFIG = {
  SUPABASE_URL: "https://brhhptouutbckstqyhil.supabase.co",
  SUPABASE_ANON_KEY: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJyaGhwdG91dXRiY2tzdHF5aGlsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE0MTU1MTIsImV4cCI6MjEwNjk5MTUxMn0.0-HUC7pPXSA3WA6H_lRsNBE9bt0YEMjdo1PEg4CX42U",
  TELEGRAM_BOT: "", // e.g. "RadarJabodetabekBot" (without @), shown in the footer
};
