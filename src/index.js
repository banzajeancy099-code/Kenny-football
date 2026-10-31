// Cloudflare Worker — proxy Bzzoiro pour Kenny Football
// Cache les résultats 30s pour éviter de spammer Bzzoiro

const BZZOIRO_BASE = "https://sports.bzzoiro.com/api/v2";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    
    // CORS pour que le dashboard Render puisse appeler
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };
    
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }
    
    try {
      // Route /scores/{event_id}
      if (url.pathname.startsWith("/scores/")) {
        const eventId = url.pathname.replace("/scores/", "");
        const data = await fetchBzzoiro(env, `/events/${eventId}/`);
        return jsonResponse(data, corsHeaders);
      }
      
      // Route /odds/{event_id}
      if (url.pathname.startsWith("/odds/")) {
        const eventId = url.pathname.replace("/odds/", "");
        const data = await fetchBzzoiro(env, `/events/${eventId}/odds/`);
        return jsonResponse(data, corsHeaders);
      }
      
      // Route /live
      if (url.pathname === "/live") {
        const data = await fetchBzzoiro(env, "/events/");
        return jsonResponse(data, corsHeaders);
      }
      
      // Route /health
      if (url.pathname === "/health") {
        return jsonResponse({ status: "ok", worker: "kenny-live" }, corsHeaders);
      }
      
      return jsonResponse({ error: "route inconnue" }, corsHeaders, 404);
    } catch (e) {
      return jsonResponse({ error: e.message }, corsHeaders, 500);
    }
  },
};

async function fetchBzzoiro(env, path) {
  const r = await fetch(`${BZZOIRO_BASE}${path}`, {
    headers: {
      "Authorization": `Token ${env.BZZOIRO_API_KEY}`,
      "Accept": "application/json",
    },
  });
  if (!r.ok) throw new Error(`Bzzoiro ${r.status}`);
  return await r.json();
}

function jsonResponse(data, headers, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...headers, "Content-Type": "application/json" },
  });
}
