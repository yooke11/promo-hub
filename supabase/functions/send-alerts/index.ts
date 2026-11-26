// 찜 알림 발송(2026-11-26): 매일 수집·추천 계산 뒤 GitHub Actions 가 수집 토큰과 함께 호출한다.
// 알림 키(VAPID)는 처음 호출 때 여기서 만들어 DB 비공개 영역(private.app_keys)에 둔다 — 키가 사람·대화·저장소를 거치지 않는다.
import webpush from "npm:web-push@3.6.7";
import { createClient } from "npm:@supabase/supabase-js@2";

const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });
const SITES: Record<string, string> = {
  food: "https://jangbopick.vercel.app",
  fashion: "https://fashionsalepick.vercel.app",
  beauty: "https://beautysalepick.vercel.app",
  "": "https://promo-hub-yooke-team.vercel.app",
};
const won = (n: number) => n.toLocaleString("ko-KR") + "원";
const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });

async function keys() {
  const pub = (await sb.rpc("vapid_public")).data as string | null;
  const priv = (await sb.rpc("vapid_private")).data as string | null;
  if (pub && priv) return { pub, priv };
  const k = webpush.generateVAPIDKeys();
  await sb.rpc("vapid_store", { p_pub: k.publicKey, p_priv: k.privateKey });
  return { pub: (await sb.rpc("vapid_public")).data as string, priv: (await sb.rpc("vapid_private")).data as string };
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return json({ error: "POST only" }, 405);
  const body = await req.json().catch(() => ({}));
  const { pub, priv } = await keys();
  if (body.mode === "init") return json({ ok: true, public_key: pub });

  const due = await sb.rpc("push_due", { p_token: String(body.token || "") });
  if (due.error) return json({ error: "unauthorized" }, 401);
  const rows = (due.data || []) as any[];
  const bySub = new Map<number, any[]>();
  for (const r of rows) { if (!bySub.has(r.sub_id)) bySub.set(r.sub_id, []); bySub.get(r.sub_id)!.push(r); }

  const sent: any[] = [], gone: number[] = [];
  let ok = 0, fail = 0;
  for (const [sid, list] of bySub) {
    const s = list[0];
    const site = SITES[(s.vertical as string) || ""] || SITES[""];
    let payload;
    if (list.length === 1) {
      const r = list[0];
      payload = r.kind === "drop"
        ? { title: "찜한 상품 가격이 내렸어요", body: `${r.name}\n${won(r.prev)} → ${won(r.price)}`, url: r.url || site + "/?view=fav", image: r.image_url }
        : { title: "찜한 상품 기획전이 내일 끝나요", body: `${r.name}\n${r.source_name || ""} · 지금 ${won(r.price)}`, url: r.url || site + "/?view=fav", image: r.image_url };
    } else {
      const drops = list.filter((r) => r.kind === "drop").length;
      payload = { title: `찜한 상품 ${list.length}개에 소식이 있어요`,
        body: [drops ? `${drops}개 가격 내림` : "", list.length - drops ? `${list.length - drops}개 내일 마감` : ""].filter(Boolean).join(" · ") + "\n" + list.slice(0, 2).map((r) => r.name).join(", "),
        url: site + "/?view=fav" };
    }
    try {
      await webpush.sendNotification({ endpoint: s.endpoint, keys: { p256dh: s.p256dh, auth: s.auth } }, JSON.stringify(payload),
        { TTL: 12 * 3600, vapidDetails: { subject: SITES[""], publicKey: pub, privateKey: priv } });
      ok++;
      for (const r of list) sent.push({ sub_id: sid, item_key: r.item_key, kind: r.kind, price: r.price, end_date: r.end_date });
    } catch (e: any) {
      fail++;
      if (e?.statusCode === 404 || e?.statusCode === 410) gone.push(sid);
    }
  }
  const done = await sb.rpc("push_done", { p_token: String(body.token || ""), p_sent: sent, p_gone: gone });
  return json({ ok: true, subscribers: bySub.size, notified: ok, failed: fail, expired: gone.length, recorded: !done.error });
});
