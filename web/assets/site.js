// Shared helpers: API calls, login modal, checkout. No framework.
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, { credentials: "same-origin", headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { const e = new Error(data.error || `Request failed (${res.status})`); e.status = res.status; e.code = data.code; throw e; }
  return data;
}

async function me() { try { return await api("/api/me"); } catch { return null; } }

function loginModal(onDone) {
  let el = $("#login");
  if (!el) {
    el = document.createElement("div");
    el.id = "login"; el.className = "modal";
    el.innerHTML = `<div class="box">
      <div class="mono">your first reel is free</div><h3>Log in</h3>
      <div class="field"><label>Email</label><input id="lg-email" type="email" autocomplete="email" placeholder="you@example.com"></div>
      <div class="field" id="lg-code-wrap" style="display:none"><label>6-digit code from your inbox</label><input id="lg-code" inputmode="numeric" maxlength="8"></div>
      <div class="err" id="lg-err"></div>
      <div style="display:flex;gap:10px;justify-content:space-between">
        <button class="btn" id="lg-go">Send code</button><button class="btn ghost" id="lg-x">Close</button></div></div>`;
    document.body.appendChild(el);
    $("#lg-x", el).onclick = () => el.classList.remove("open");
  }
  let stage = "email";
  $("#lg-go", el).onclick = async () => {
    const err = $("#lg-err", el); err.textContent = "";
    try {
      if (stage === "email") {
        await api("/api/auth/code", { method: "POST", body: { email: $("#lg-email", el).value } });
        stage = "code"; $("#lg-code-wrap", el).style.display = ""; $("#lg-go", el).textContent = "Log in"; $("#lg-code", el).focus();
      } else {
        await api("/api/auth/verify", { method: "POST", body: { email: $("#lg-email", el).value, code: $("#lg-code", el).value } });
        el.classList.remove("open"); onDone && onDone();
      }
    } catch (e) { err.textContent = e.message; }
  };
  el.classList.add("open"); $("#lg-email", el).focus();
}

function loadScript(src) {
  return new Promise((ok, fail) => { const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = fail; document.head.appendChild(s); });
}

async function buy(planCode, onPaid) {
  const start = await api("/api/checkout", { method: "POST", body: { plan: planCode } });
  const co = start.checkout;
  const confirm = (orderId, paymentId, signature) =>
    api("/api/checkout/confirm", { method: "POST", body: { order_id: orderId, payment_id: paymentId, signature } }).then(onPaid);
  if (co.provider === "mock") return confirm(co.order_id, "mock_pay", "mock");
  if (!window.Razorpay) await loadScript("https://checkout.razorpay.com/v1/checkout.js");
  const rzp = new window.Razorpay({
    key: co.key, order_id: co.order_id, amount: co.amount, currency: co.currency, name: co.name,
    description: `${start.plan.name}: ${start.plan.videos} reels up to ${start.plan.max_seconds}s`, prefill: co.prefill,
    theme: { color: "#0D0D0D" },
    handler: (r) => confirm(r.razorpay_order_id, r.razorpay_payment_id, r.razorpay_signature).catch((e) => alert(e.message)),
  });
  rzp.open();
}

function planCards(plans, cta) {
  return plans.map((p) => `<div class="plan ${p.highlight ? "hl" : ""}">
    ${p.highlight ? '<span class="flag mono">most picked</span>' : ""}
    <div class="name">${esc(p.name)}</div>
    <div class="price">₹${p.price_inr}<small> · ${p.videos} reels</small></div>
    <ul><li>Up to ${p.max_seconds} seconds each</li><li>₹${Math.round(p.per_video_inr)} a reel</li>
        <li>Research, script, voice, motion</li><li>Captions + posting pack</li></ul>
    <button class="btn" data-plan="${esc(p.code)}">${cta}</button></div>`).join("");
}
