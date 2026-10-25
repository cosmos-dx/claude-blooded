// Studio dashboard: create reels, watch stages, download files, buy packs.
let catalog = null, isAdmin = false;
const STAGES = { queued: "waiting in line", starting: "starting", moderate: "checking the request", research: "researching the topic",
  plan: "writing the script", voice: "recording the voice", render: "animating", mix: "mixing sound", publish: "writing your posting pack",
  done: "ready", failed: "failed", expired: "files deleted" };

async function boot() {
  const user = await me();
  if (!user) return loginModal(() => location.reload());
  isAdmin = user.is_admin;
  $("#who").textContent = user.email;
  if (isAdmin) $("#admin-link").style.display = "";
  $("#logout").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); location.href = "/"; };
  catalog = await api("/api/catalog");
  const o = catalog.options;
  $("#language").innerHTML = o.languages.map((l) => `<option value="${esc(l.code)}">${esc(l.label)}</option>`).join("");
  $("#seconds").innerHTML = o.lengths.map((s) => `<option value="${s}">${s < 60 ? s + " seconds" : s / 60 + (s === 60 ? " minute" : " minutes")}</option>`).join("");
  $("#skill").innerHTML = o.skills.map((s) => `<option>${esc(s)}</option>`).join("");
  const themes = () => ($("#theme").innerHTML = (o.themes[$("#skill").value] || []).map((t) => `<option>${esc(t)}</option>`).join(""));
  $("#skill").onchange = themes; themes();
  $("#plans").innerHTML = planCards(catalog.plans, "Buy");
  document.querySelectorAll("[data-plan]").forEach((b) => (b.onclick = () => buy(b.dataset.plan, refresh).catch((e) => alert(e.message))));
  renderCredits(user.credits);
  $("#create").onsubmit = create;
  refresh(); setInterval(refresh, 4000);
}

function renderCredits(credits) {
  $("#credits").innerHTML = credits.length
    ? credits.map((c) => `<span class="chip">${c.remaining} × up to ${c.max_seconds}s</span>`).join("")
    : '<span class="chip">no credits left</span>';
  $("#buy").style.display = credits.length ? "none" : "";
}

async function create(ev) {
  ev.preventDefault();
  const f = new FormData(ev.target), err = $("#create-err"); err.textContent = "";
  const body = Object.fromEntries(f.entries()); body.seconds = Number(body.seconds);
  $("#go").disabled = true;
  try { await api("/api/jobs", { method: "POST", body }); ev.target.problem.value = ""; await refresh(); }
  catch (e) { err.textContent = e.message; if (e.status === 402) $("#buy").style.display = ""; }
  finally { $("#go").disabled = false; }
}

const open = new Set();
async function refresh() {
  const [jobs, user] = await Promise.all([api("/api/jobs"), me()]);
  if (user) renderCredits(user.credits);
  if (!jobs.length) return;
  const detail = await Promise.all(jobs.map((j) => (j.status === "running" || j.status === "done" || open.has(j.id)) ? api(`/api/jobs/${j.id}`) : j));
  $("#jobs").innerHTML = detail.map(card).join("");
  document.querySelectorAll("[data-toggle]").forEach((b) => (b.onclick = () => { open.has(b.dataset.toggle) ? open.delete(b.dataset.toggle) : open.add(b.dataset.toggle); refresh(); }));
}

function minsLeft(iso) { return iso ? Math.max(0, Math.round((new Date(iso) - Date.now()) / 60000)) : null; }

function card(j) {
  const pct = Math.round((j.progress || 0) * 100), r = j.request || {};
  const files = (j.files || []).map((n) => `<a class="btn small ghost" href="/api/jobs/${j.id}/files/${n}">${esc(n)}</a>`).join("");
  const events = (j.events || []).map((e) => `<div>${esc(e.stage)} · ${esc(e.message || "")}${isAdmin && e.cost_inr !== undefined
    ? ` · ${e.input_tokens}+${e.output_tokens} tok · ${e.characters} chars · ₹${e.cost_inr.toFixed(2)}` : ""}</div>`).join("");
  const cost = isAdmin && j.cost ? `<div class="events"><b>total ₹${j.cost.inr.toFixed(2)}</b> · ${j.cost.input_tokens} in / ${j.cost.output_tokens} out tokens · ${j.cost.characters} voice chars</div>` : "";
  const pack = j.publish_pack ? `<details><summary class="status">posting pack</summary><pre class="pack">${esc(JSON.stringify(j.publish_pack, null, 2))}</pre></details>` : "";
  const left = minsLeft(j.expires_at);
  return `<div class="job"><div class="top"><div class="title">${esc(j.title || r.problem?.slice(0, 80) || "Reel")}</div>
      <span class="status ${j.status}">${esc(STAGES[j.stage] || j.stage)}</span></div>
    <div class="status">${esc(r.skill)} · ${esc(r.theme)} · ${r.seconds}s · ${esc(r.language)}</div>
    ${j.status === "running" || j.status === "queued" ? `<div class="progress"><i style="width:${pct}%"></i></div>` : ""}
    ${j.error ? `<div class="err">${esc(j.error)} (your credit was returned)</div>` : ""}
    ${j.status === "done" ? `<video class="preview" controls preload="metadata" src="/api/jobs/${j.id}/files/reel.mp4?inline=1"></video>
      <div class="files">${files}</div><div class="status" style="margin-top:8px">deletes in ${left} min, so download now</div>` : ""}
    ${pack}<div class="events">${events}</div>${cost}
    ${j.events ? "" : `<button class="btn small ghost" data-toggle="${j.id}" style="margin-top:10px">details</button>`}</div>`;
}

boot();
