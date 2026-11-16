import { DurableObject } from "cloudflare:workers";

interface Env {
  TRIAGE_RUN: DurableObjectNamespace<TriageRun>;
  RUN_TOKEN: string;
  RUN_ENABLED: string;
  HELPDESK_BASE_URL: string;
  HELPDESK_API_KEY: string;
  CANDIDATE_EMAIL: string;
  GROQ_API_KEY: string;
  GEMINI_API_KEY: string;
  DATABASE_URL: string;
}

const PASSED_TO_THE_AGENT = [
  "HELPDESK_BASE_URL",
  "HELPDESK_API_KEY",
  "CANDIDATE_EMAIL",
  "GROQ_API_KEY",
  "GEMINI_API_KEY",
  "DATABASE_URL",
] as const;

export class TriageRun extends DurableObject<Env> {
  async start(options: string[]): Promise<"started" | "already running"> {
    const container = this.ctx.container;
    if (!container) {
      throw new Error("this Durable Object has no container");
    }
    if (container.running) {
      return "already running";
    }
    const env = Object.fromEntries(PASSED_TO_THE_AGENT.map((name) => [name, this.env[name]]));
    container.start({
      env,
      enableInternet: true,
      entrypoint: ["/app/.venv/bin/python", "-m", "triage", "run", ...options],
    });
    this.ctx.waitUntil(container.monitor().catch(() => undefined));
    return "started";
  }
}

export default {
  async fetch(request, env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({ ok: true, runs_enabled: env.RUN_ENABLED === "true" });
    }
    if (url.pathname !== "/run" || request.method !== "POST") {
      return new Response("Not found", { status: 404 });
    }
    if (!(await presentsToken(request, env.RUN_TOKEN))) {
      return new Response("Unauthorized", { status: 401 });
    }
    if (env.RUN_ENABLED !== "true") {
      return new Response("Live runs are locked", { status: 423 });
    }
    const outcome = await env.TRIAGE_RUN.getByName("run").start(runOptions(url.searchParams));
    return Response.json({ outcome }, { status: outcome === "started" ? 202 : 409 });
  },
} satisfies ExportedHandler<Env>;

function runOptions(query: URLSearchParams): string[] {
  const options: string[] = [];
  if (query.get("dry_run") === "1") {
    options.push("--dry-run");
  }
  const limit = query.get("limit");
  if (limit !== null && /^\d{1,3}$/.test(limit)) {
    options.push("--limit", limit);
  }
  return options;
}

async function presentsToken(request: Request, token: string): Promise<boolean> {
  if (!token) {
    return false;
  }
  const [presented, expected] = await Promise.all([
    sha256(request.headers.get("Authorization") ?? ""),
    sha256(`Bearer ${token}`),
  ]);
  return crypto.subtle.timingSafeEqual(presented, expected);
}

async function sha256(text: string): Promise<ArrayBuffer> {
  return crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
}
