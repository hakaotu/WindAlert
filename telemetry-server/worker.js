/**
 * Example reference telemetry aggregator (Cloudflare Worker).
 *
 * This is NOT required to use wingfoil-wind-alert. It's an optional,
 * self-hosted example for anyone who wants to see aggregate usage
 * stats (e.g. "how many instances, in which regions") without ever
 * storing anything that identifies an individual installation.
 *
 * Privacy design, enforced server-side (not just trusted from the client):
 * - The client payload includes an `instance_id`, but this worker
 *   DELIBERATELY IGNORES AND NEVER PERSISTS IT. Only an aggregate
 *   counter is stored, keyed by (date, region_grid, event). This means
 *   even if you run this worker yourself, you cannot reconstruct
 *   per-instance activity from the stored data - only daily totals per
 *   coarse region.
 * - No IP address is read or logged by this code.
 * - Counters expire automatically after ~13 months (TTL below).
 *
 * Deploy with Wrangler:
 *   npm install -g wrangler
 *   wrangler kv:namespace create WINGFOIL_KV
 *   # put the resulting id into wrangler.toml
 *   wrangler deploy
 *
 * Then set in your config.yaml:
 *   telemetry:
 *     enabled: true
 *     endpoint: "https://<your-worker>.workers.dev"
 */

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return new Response("Invalid JSON", { status: 400 });
    }

    const { region_grid, date, event } = body;
    if (!region_grid || !date || !event) {
      return new Response("Missing required fields", { status: 400 });
    }
    // instance_id is intentionally read but never stored - see file header.

    if (!/^-?\d+\.\d,-?\d+\.\d$/.test(region_grid)) {
      return new Response("Malformed region_grid", { status: 400 });
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      return new Response("Malformed date", { status: 400 });
    }
    if (!["wind_start", "wind_stop"].includes(event)) {
      return new Response("Unknown event type", { status: 400 });
    }

    const key = `count:${date}:${region_grid}:${event}`;
    const current = parseInt((await env.WINGFOIL_KV.get(key)) || "0", 10);
    await env.WINGFOIL_KV.put(key, String(current + 1), {
      expirationTtl: 60 * 60 * 24 * 400, // ~13 months
    });

    return new Response("ok");
  },
};
