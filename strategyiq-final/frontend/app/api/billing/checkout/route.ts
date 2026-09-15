export const runtime = "edge";

import { getServerApiUrl } from "@/lib/serverApi";

export async function POST(req: Request) {
  const { tier } = await req.json();
  const auth = req.headers.get("authorization");
  const apiUrl = getServerApiUrl();

  const res = await fetch(`${apiUrl}/billing/checkout`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: auth || "",
    },
    body: JSON.stringify({ tier }),
  });

  const data = await res.json();
  return Response.json(data, { status: res.status });
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const tier = url.searchParams.get("tier") || "pro";
  const auth = req.headers.get("authorization");
  const apiUrl = getServerApiUrl();

  const res = await fetch(`${apiUrl}/billing/checkout`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: auth || "",
    },
    body: JSON.stringify({ tier }),
  });

  const data = await res.json();
  return Response.json(data, { status: res.status });
}
