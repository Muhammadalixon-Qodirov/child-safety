// Shared helpers for the Guardian dashboards.
const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmtMin = (sec) => {
  if (sec == null) return "—";
  const m = Math.round(sec / 60);
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`;
};

const CAT = {
  GROOMING: { icon: "🚨", color: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" },
  SELF_HARM: { icon: "🆘", color: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" },
  SOS: { icon: "🆘", color: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" },
  ADULT: { icon: "⛔", color: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" },
  PII: { icon: "🔐", color: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300" },
  BULLYING: { icon: "💬", color: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300" },
  VIOLENCE: { icon: "⚠️", color: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300" },
  GAMBLING: { icon: "🎰", color: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300" },
  SCAM: { icon: "🎣", color: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300" },
  TAMPER: { icon: "🛠️", color: "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200" },
  APP_RULE: { icon: "⏱️", color: "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300" },
  SAFE: { icon: "✅", color: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300" },
};
const catBadge = (c) => {
  const k = CAT[c] || CAT.SAFE;
  return `<span class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${k.color}">${k.icon} ${esc(c.replace("_", " "))}</span>`;
};
const riskBar = (r) => {
  const color = r >= 80 ? "bg-red-500" : r >= 60 ? "bg-amber-500" : r >= 30 ? "bg-sky-500" : "bg-emerald-500";
  return `<div class="flex items-center gap-2"><div class="h-2 w-20 rounded bg-slate-200 dark:bg-slate-700"><div class="h-2 rounded ${color}" style="width:${r}%"></div></div><span class="text-xs tabular-nums text-slate-500">${r}</span></div>`;
};

let toastTimer;
const toast = (msg) => {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.className = "fixed bottom-5 left-1/2 -translate-x-1/2 z-50 rounded-xl bg-slate-900 text-white px-4 py-2 text-sm shadow-lg transition-opacity";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.style.opacity = 1;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.style.opacity = 0), 2600);
};
