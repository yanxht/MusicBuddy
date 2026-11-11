"use strict";

/* ================================================================ helpers */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const KIDS = { keyu: { name: "Keyu", age: 10 }, ruyu: { name: "Ruyu", age: 7 } };
const view = $("#view");
const cache = { lessons: null, lesson: {}, timeline: {}, profile: {} };

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}
function parseDate(d) { return new Date(+d.slice(0, 4), +d.slice(4, 6) - 1, +d.slice(6, 8)); }
function longDate(d) { return parseDate(d).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" }); }
function shortDate(d) { return parseDate(d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }); }
function cap(s) { return s ? s[0].toUpperCase() + s.slice(1) : ""; }
function mins(m) { return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m} min`; }

async function api(path, opts = {}) {
  const r = await fetch(path, { credentials: "same-origin", ...opts });
  if (r.status === 401) { showLogin(); throw new Error("auth"); }
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.detail || r.statusText);
  }
  return r.json();
}
async function getLesson(date, fresh = false) {
  if (fresh || !cache.lesson[date]) cache.lesson[date] = await api(`/api/lessons/${date}`);
  return cache.lesson[date];
}
async function getTimeline(date) {
  if (!cache.timeline[date]) cache.timeline[date] = await api(`/api/lessons/${date}/timeline`);
  return cache.timeline[date];
}

/* ================================================================ login */
function showLogin() {
  $("#login").hidden = false;
  setTimeout(() => $("#login-pass").focus(), 50);
}
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-err").textContent = "";
  try {
    const r = await fetch("/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passcode: $("#login-pass").value }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "Sign in failed");
    $("#login").hidden = true;
    $("#login-pass").value = "";
    route();
  } catch (err) { $("#login-err").textContent = err.message; }
});

/* ================================================================ player */
const audio = $("#audio");
const P = { date: null, rec: null, start: 0, end: null, keep: false, label: "", btn: null, pendingSeek: null, retried: false };

function clipAttrs(date, clip, label) {
  if (!clip) return "";
  return `data-date="${date}" data-rec="${esc(clip.rec)}" data-start="${clip.start}" data-end="${clip.end}" data-label="${esc(label || "")}"`;
}
function clipBtn(date, clip, label, text) {
  if (!clip) return "";
  const t = text || clipTime(date, clip);
  return `<button class="play" ${clipAttrs(date, clip, label)} title="Play (${fmt(clip.end - clip.start)})">${esc(t)}</button>`;
}
function clipTime(date, clip) {
  const lesson = cache.lesson[date];
  const multi = lesson && lesson.recordings && lesson.recordings.length > 1;
  return `${multi ? "P" + clip.rec.slice(1) + " · " : ""}${fmt(clip.start)}`;
}

function playClip(c, btn) {
  const src = `/api/lessons/${c.date}/audio/${c.rec}`;
  P.date = c.date; P.rec = c.rec; P.start = +c.start; P.end = c.end == null || c.end === "" ? null : +c.end;
  P.keep = P.end == null; P.label = c.label || "";
  if (P.btn) P.btn.classList.remove("playing");
  P.btn = btn || null;
  if (P.btn) P.btn.classList.add("playing");
  if (audio.dataset.src !== src) {
    audio.dataset.src = src; P.retried = false;
    audio.src = src; audio.preload = "auto";
    P.pendingSeek = P.start;
  } else if (audio.readyState >= 1) {
    audio.currentTime = P.start;
  } else {
    P.pendingSeek = P.start;
  }
  audio.play().catch(() => {});
  const kidClass = [...view.classList].find((x) => x.startsWith("kid-"));
  $("#player").className = "player" + (kidClass ? " " + kidClass : "");
  $("#player").hidden = false;
  document.body.classList.add("has-player");
  $("#p-label").textContent = P.label || "Lesson recording";
  $("#p-more").classList.toggle("on", P.keep);
  paintPlayer();
}
audio.addEventListener("loadedmetadata", () => {
  if (P.pendingSeek != null) { audio.currentTime = P.pendingSeek; P.pendingSeek = null; }
});
audio.addEventListener("error", () => {
  // Signed audio URLs expire; re-request once to get a fresh one.
  if (P.retried || !audio.dataset.src) return;
  P.retried = true;
  const t = audio.currentTime || P.start;
  audio.src = audio.dataset.src + "?r=" + Date.now();
  P.pendingSeek = t;
  audio.play().catch(() => {});
});
audio.addEventListener("timeupdate", () => {
  if (!P.keep && P.end != null && audio.currentTime >= P.end) {
    audio.pause();
    audio.currentTime = P.end;
  }
  paintPlayer();
  followTranscript();
});
audio.addEventListener("play", paintPlayer);
audio.addEventListener("pause", () => { paintPlayer(); if (P.btn) P.btn.classList.remove("playing"); });

function paintPlayer() {
  const t = audio.currentTime || 0;
  const a = P.keep ? 0 : P.start;
  const b = P.keep ? (audio.duration || P.end || t + 1) : (P.end ?? audio.duration ?? t + 1);
  const pct = Math.min(100, Math.max(0, ((t - a) / Math.max(1, b - a)) * 100));
  $("#p-fill").style.width = pct + "%";
  $("#p-cur").textContent = fmt(t - a);
  $("#p-dur").textContent = isFinite(b - a) ? fmt(b - a) : "";
  $("#p-toggle").classList.toggle("on", !audio.paused);
}
$("#p-toggle").onclick = () => {
  if (audio.paused) {
    if (!P.keep && P.end != null && audio.currentTime >= P.end - 0.3) audio.currentTime = P.start;
    audio.play().catch(() => {});
  } else audio.pause();
};
$("#p-back").onclick = () => { audio.currentTime = Math.max(0, audio.currentTime - 10); };
$("#p-fwd").onclick = () => { audio.currentTime = audio.currentTime + 10; };
$("#p-more").onclick = () => {
  P.keep = !P.keep;
  $("#p-more").classList.toggle("on", P.keep);
  if (P.keep && audio.paused) audio.play().catch(() => {});
  paintPlayer();
};
const SPEEDS = [1, 0.75, 1.25];
$("#p-speed").onclick = () => {
  const i = (SPEEDS.indexOf(audio.playbackRate) + 1) % SPEEDS.length;
  audio.playbackRate = SPEEDS[i];
  $("#p-speed").textContent = SPEEDS[i] + "×";
};
$("#p-close").onclick = () => { audio.pause(); $("#player").hidden = true; document.body.classList.remove("has-player"); };
$("#p-bar").onclick = (e) => {
  const r = e.currentTarget.getBoundingClientRect();
  const f = (e.clientX - r.left) / r.width;
  const a = P.keep ? 0 : P.start;
  const b = P.keep ? audio.duration : P.end ?? audio.duration;
  audio.currentTime = a + f * (b - a);
};
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".play");
  if (!btn) return;
  e.preventDefault();
  if (btn.dataset.ids) {
    const [date, a, b] = btn.dataset.ids.split(":");
    const clip = await resolveIds(date, +a, +b);
    if (clip) playClip({ date, ...clip, label: btn.dataset.label || "From chat" }, btn);
    return;
  }
  if (P.btn === btn && !audio.paused) { audio.pause(); return; }
  playClip({ ...btn.dataset }, btn);
});

async function resolveIds(date, a, b) {
  const items = await getTimeline(date);
  const ph = items.filter((i) => i.id >= Math.min(a, b) && i.id <= Math.max(a, b));
  if (!ph.length) return null;
  const rec = ph[0].rec;
  const same = ph.filter((i) => i.rec === rec);
  await getLesson(date).catch(() => {});
  return { rec, start: Math.max(0, same[0].start - 1.5), end: same[same.length - 1].end + 1.0 };
}

/* ================================================================ router */
let pollTimer = null;
function route() {
  clearTimeout(pollTimer);
  const parts = (location.hash.slice(1) || "/").split("/").filter(Boolean);
  $$(".nav-links a").forEach((a) => a.classList.toggle("active",
    (parts[0] === "kid" && a.dataset.nav === "kid-" + parts[1]) || (parts[0] === "upload" && a.dataset.nav === "upload")));
  view.className = "view";
  $("#ask-fab").hidden = false;
  chatScope = { date: null, kid: null };
  window.scrollTo(0, 0);
  const go = parts[0] === "l" ? viewLesson(parts[1], parts[2], parts[3] || "notes")
    : parts[0] === "kid" ? viewKid(parts[1])
    : parts[0] === "upload" ? viewUpload()
    : viewHome();
  go.catch((err) => {
    if (err.message !== "auth") view.innerHTML = `<div class="empty">Something went wrong: ${esc(err.message)}</div>`;
  });
}
window.addEventListener("hashchange", route);

/* ================================================================ home */
async function viewHome() {
  view.innerHTML = `<div class="empty"><div class="spinner" style="margin:auto"></div></div>`;
  const data = await api("/api/lessons");
  cache.lessons = data.lessons;
  const pending = data.pending.filter((p) => p.state !== "ready");
  const pendingHtml = pending.map((p) => `
    <div class="card pending">
      ${p.state === "error" ? `<span class="status partly">Error</span>` : `<div class="spinner"></div>`}
      <div class="body"><div class="t"><b>${esc(longDate(p.date))}</b></div>
      <div class="muted small">${p.state === "error" ? "Processing failed: " : ""}${esc(p.step)}</div></div>
    </div>`).join("");
  const cards = data.lessons.map((l) => `
    <div class="card lesson-card">
      <div class="lesson-date">${esc(longDate(l.date))}</div>
      <div class="lesson-meta">${esc(cap(l.instrument))}${l.teacher ? " with " + esc(l.teacher) : ""} · ${esc(shortDate(l.date))}</div>
      <div class="kid-rows">
        ${Object.entries(l.kids).map(([k, v]) => `
          <a class="kid-row kid-${k}" href="#/l/${l.date}/${k}">
            <div class="kid-dot">${esc(KIDS[k]?.name[0] || "?")}</div>
            <div class="body"><div class="h">${esc(v.headline || "Lesson notes")}</div>
            <div class="m">${esc(KIDS[k]?.name || k)} · ${mins(v.minutes)}</div></div>
          </a>`).join("")}
      </div>
    </div>`).join("");
  view.innerHTML = `
    <div class="home-head">
      <div><p class="eyebrow">Lesson notes</p><h1 class="title">Lessons</h1></div>
      <a class="btn primary" href="#/upload">＋ Add lesson</a>
    </div>
    <div class="stack">${pendingHtml}</div>
    <div class="grid two" style="margin-top:14px">${cards}</div>
    ${!data.lessons.length && !pending.length ? `<div class="empty">No lessons yet. Drop a dated folder into the Music Lesson Recording folder, or upload here.</div>` : ""}`;
  if (pending.some((p) => p.state !== "error")) pollTimer = setTimeout(() => { if (!location.hash || location.hash === "#/") viewHome(); }, 15000);
}

/* ================================================================ lesson */
const LABELS = {
  en: { focus: "What the teacher focused on", came: (n) => `Came up ~${n}×`, practice: "Practice this week",
    replay: "Lesson replay", parts: "parts", words: "Words to know", photos: "Photos", min: "min",
    done: (a, b) => `${a} of ${b} done` },
  zh: { focus: "老师重点强调", came: (n) => `约提到 ${n} 次`, practice: "本周练习",
    replay: "课堂回放", parts: "个部分", words: "术语小词典", photos: "照片", min: "分钟",
    done: (a, b) => `已完成 ${a}/${b}` },
};
const imgKey = (im) => (im?.blob || "").match(/images\/([A-Za-z0-9]+)\.jpg$/)?.[1];
const imgUrl = (date, key) => `/api/lessons/${date}/images/${key}`;
const forKid = (im, kid) => im.kid === kid || im.kid === "both" || im.kid === "unknown";

async function viewLesson(date, kid, tab) {
  view.innerHTML = `<div class="empty"><div class="spinner" style="margin:auto"></div></div>`;
  const doc = await getLesson(date);
  const kids = Object.keys(doc.kids);
  if (!kids.length) { view.innerHTML = `<div class="empty">No lesson notes for this date yet.</div>`; return; }
  if (!doc.kids[kid]) { location.replace(`#/l/${date}/${kids[0]}/${tab}`); return; }
  const K = doc.kids[kid];
  const lang = localStorage.getItem("mb_lang") === "zh" ? "zh" : "en";
  const L = LABELS[lang];
  view.classList.add("kid-" + kid);
  chatScope = { date, kid };

  const head = `
    <a class="back" href="#/">‹ Lessons</a>
    <p class="eyebrow">${esc(cap(doc.instrument))}${doc.teacher ? " · " + esc(doc.teacher) : ""}</p>
    <h1 class="title">${esc(longDate(date))}</h1>
    <div class="seg-row">
      <div class="seg">${kids.map((k) => `<button class="${k === kid ? "on" : ""}" data-kid="${k}">${esc(KIDS[k]?.name || k)}<span class="mins">${mins(doc.kids[k].minutes)}</span></button>`).join("")}</div>
      ${tab === "notes" ? `<div class="seg lang"><button class="${lang === "en" ? "on" : ""}" data-lang="en">EN</button><button class="${lang === "zh" ? "on" : ""}" data-lang="zh">中文</button></div>` : ""}
    </div>
    <div class="tabs">
      <a href="#/l/${date}/${kid}/notes" class="${tab === "notes" ? "on" : ""}">Notes</a>
      <a href="#/l/${date}/${kid}/transcript" class="${tab === "transcript" ? "on" : ""}">Transcript</a>
    </div>`;
  view.innerHTML = head + `<div id="tab"></div>`;
  $$(".seg button[data-kid]", view).forEach((b) => (b.onclick = () => { location.hash = `#/l/${date}/${b.dataset.kid}/${tab}`; }));
  $$(".seg button[data-lang]", view).forEach((b) => (b.onclick = () => { localStorage.setItem("mb_lang", b.dataset.lang); route(); }));
  if (tab === "transcript") return renderTranscript(date, kid, doc);

  let S = K.summary;
  if (lang === "zh") {
    $("#tab").innerHTML = `<div class="empty"><div class="spinner" style="margin:auto"></div><p>正在生成中文版…（第一次约需 1 分钟）</p></div>`;
    try {
      cache.zh = cache.zh || {};
      S = cache.zh[`${date}/${kid}`] = cache.zh[`${date}/${kid}`] || await api(`/api/lessons/${date}/kids/${kid}/zh`);
    } catch (err) {
      if (err.message === "auth") return;
      S = K.summary;
    }
    if (location.hash.split("/")[3] !== kid && location.hash.split("/")[3]) return;
  }

  const focus = (S.teacher_focus || []).map((f, i) => `
    <div class="card focus">
      <div class="rank">${i + 1}</div>
      <h3>${esc(f.title)}</h3>
      ${f.mentions ? `<div class="mentions">${esc(L.came(f.mentions))}</div>` : ""}
      <p>${esc(f.detail)}</p>
      <div class="clips">${(f.clips || []).map((c) => clipBtn(date, c, f.title)).join("")}</div>
    </div>`).join("");

  const asg = (S.assignments || []).map((a, i) => `
    <div class="row">
      <button class="check" data-check="${i}" aria-label="Mark done"></button>
      <div class="body"><div class="t">${a.priority === "high" ? `<span class="prio high" title="high priority"></span>` : ""}${esc(a.task)}</div>${a.details ? `<div class="d">${esc(a.details)}</div>` : ""}</div>
      ${clipBtn(date, a.clip, "Practice: " + a.task)}
    </div>`).join("");
  const plan = (S.practice_plan || []).map((p, i) => `<div class="step"><b>${i + 1}</b>${esc(p.step)}${p.minutes ? ` <span class="muted">· ${esc(p.minutes)} ${L.min}</span>` : ""}</div>`).join("");

  const sections = (S.sections || []).map((s) => `
    <div class="tsec">
      <div class="card">
        <div class="tsec-head">
          <div><span class="kind">${esc((s.kind || "").replace("_", " "))}</span><h3>${esc(s.title)}</h3>
          ${s.material ? `<div class="material">${esc(s.material)}</div>` : ""}</div>
          ${clipBtn(date, s.clip, s.title, s.clip ? `${clipTime(date, s.clip)} · ${mins(Math.max(1, Math.round((s.clip.end - s.clip.start) / 60)))}` : "")}
        </div>
        ${s.summary ? `<p class="sum">${esc(s.summary)}</p>` : ""}
        ${(s.photos || []).length ? `<div class="thumbs">${s.photos.map((k) => `<button class="thumb" data-img="${esc(k)}"><img src="${imgUrl(date, k)}" alt="" loading="lazy"></button>`).join("")}</div>` : ""}
        <ul class="points">${(s.points || []).map((p) => `
          <li><span class="ptext">${esc(p.text)}</span>${clipBtn(date, p.clip, p.text)}</li>`).join("")}
        </ul>
      </div>
    </div>`).join("");

  const images = doc.images || [];
  const byKey = Object.fromEntries(images.filter(imgKey).map((im) => [imgKey(im), im]));
  const photos = images.filter((im) => imgKey(im) && forKid(im, kid)).map((im) => `
    <button class="photo" data-img="${esc(imgKey(im))}">
      <img src="${imgUrl(date, imgKey(im))}" alt="${esc(im.title)}" loading="lazy">
      <div class="cap">${esc(im.title || im.name)}</div>
    </button>`).join("");

  const CHECK = { agrees: ["ok", "Agrees"], conflicts: ["bad", "Conflicts"], not_discussed: ["meh", "Not discussed"] };
  const crossCheck = images.filter((im) => imgKey(im) && im.check).map((im) => `
    <div class="xrow">
      <button class="thumb" data-img="${esc(imgKey(im))}"><img src="${imgUrl(date, imgKey(im))}" alt="" loading="lazy"></button>
      <div class="body"><b>${esc(im.title || im.name)}</b> → ${esc(KIDS[im.kid]?.name || im.kid)}${im.span ? ` · #${im.span[0]}–#${im.span[1]}` : ""}
        <span class="xcheck ${(CHECK[im.check] || ["meh"])[0]}">${esc((CHECK[im.check] || ["", im.check])[1])}</span>
        <div class="muted small">${esc(im.check_note || im.why || "")}</div></div>
    </div>`).join("");

  const total = doc.recordings.reduce((a, r) => a + r.duration, 0);
  const segs = (doc.attribution?.segments || []);
  const segbar = segs.map((s) => {
    const color = s.kid === "keyu" ? "var(--keyu)" : s.kid === "ruyu" ? "var(--ruyu)" : "rgba(0,0,0,.15)";
    return `<div style="flex:${Math.max(1, s.to_id - s.from_id + 1)};background:${color}" title="${esc(KIDS[s.kid]?.name || "Other")} #${s.from_id}-#${s.to_id}"></div>`;
  }).join("");

  $("#tab").innerHTML = `
    <div class="hero">
      <h1>${esc(S.headline)}</h1>
      <p class="lede">${esc(S.overview)}</p>
      ${S.mood ? `<span class="mood">${esc(S.mood)}</span>` : ""}
    </div>
    ${focus ? `<h2 class="section">${L.focus}</h2><div class="focus-grid">${focus}</div>` : ""}
    ${asg || plan ? `<h2 class="section">${L.practice} <span class="count" id="done-count"></span></h2>${asg ? `<div class="card list-card" id="asg">${asg}</div>` : ""}${plan ? `<div class="plan">${plan}</div>` : ""}` : ""}
    ${sections ? `<h2 class="section">${L.replay} <span class="count">${(S.sections || []).length} ${L.parts}</span></h2><div class="timeline">${sections}</div>` : ""}
    ${(S.glossary || []).length ? `<h2 class="section">${L.words}</h2><div class="glossary">${S.glossary.map((g) => `<div class="card"><b>${esc(g.term)}</b><span>${esc(g.meaning)}</span></div>`).join("")}</div>` : ""}
    ${photos ? `<h2 class="section">${L.photos}</h2><div class="photos">${photos}</div>` : ""}
    <details class="how">
      <summary>How MusicBuddy split the recordings</summary>
      <div class="card">
        <div class="segbar">${segbar}</div>
        <div class="muted small">${doc.recordings.map((r) => `${esc(r.name)} (${fmt(r.duration)})`).join(" · ")} · total ${fmt(total)}</div>
        <p>${esc(doc.attribution?.reasoning || "")}</p>
        ${segs.map((s) => `<p><b>${esc(KIDS[s.kid]?.name || "Not a lesson")}</b> #${s.from_id}–#${s.to_id} · confidence ${Math.round((s.confidence || 0) * 100)}%<br>
          <span class="muted">${(s.evidence || []).slice(0, 4).map(esc).join(" · ")}</span></p>`).join("")}
        ${crossCheck ? `<h4>Photo cross-check</h4>${crossCheck}` : ""}
        <button class="btn" id="reprocess">Re-run AI processing</button>
      </div>
    </details>`;
  $("#reprocess").onclick = async (e) => {
    if (!confirm("Re-run processing for this lesson? Notes will refresh in a few minutes.")) return;
    e.target.disabled = true;
    await api(`/api/lessons/${date}/reprocess`, { method: "POST" });
    delete cache.lesson[date];
    location.hash = "#/";
  };
  $("#tab").onclick = (e) => {
    const b = e.target.closest("[data-img]");
    if (b) openPhoto(date, b.dataset.img, byKey[b.dataset.img]);
  };
  setupChecks(date, kid, (S.assignments || []).length, L);
}

async function setupChecks(date, kid, n, L) {
  const box = $("#asg");
  if (!box || !n) return;
  const url = `/api/lessons/${date}/kids/${kid}/checks`;
  let done = new Set();
  const paint = () => {
    $$(".check", box).forEach((c) => c.closest(".row").classList.toggle("done", done.has(+c.dataset.check)));
    $("#done-count").textContent = L.done(done.size, n);
  };
  try { done = new Set((await api(url)).done); } catch (_) { /* show unchecked */ }
  paint();
  box.onclick = async (e) => {
    const c = e.target.closest(".check");
    if (!c) return;
    const i = +c.dataset.check;
    if (done.has(i)) done.delete(i); else done.add(i);
    paint();
    await api(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ done: [...done] }) }).catch(() => {});
  };
}

function openPhoto(date, key, im) {
  $("#lb-img").src = imgUrl(date, key);
  $("#lb-cap").textContent = im ? (im.title || im.name) : "";
  $("#lb-open").href = imgUrl(date, key);
  $("#lightbox").hidden = false;
}
$("#lightbox").addEventListener("click", (e) => { if (e.target.id === "lightbox" || e.target.id === "lb-close") $("#lightbox").hidden = true; });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#lightbox").hidden = true; });

/* ---------------------------------------------------------------- transcript */
let trState = null;
async function renderTranscript(date, kid, doc) {
  const tab = $("#tab");
  tab.innerHTML = `<div class="empty"><div class="spinner" style="margin:auto"></div></div>`;
  const items = await getTimeline(date);
  const names = doc.attribution?.speaker_names || {};
  const ranges = doc.kids[kid].ranges;
  const inKid = (id) => ranges.some(([a, b]) => id >= a && id <= b);
  trState = { date, all: false, follow: true, q: "" };
  tab.innerHTML = `
    <div class="tr-tools">
      <input id="tr-q" type="search" placeholder="Search the transcript">
      <button class="chip-btn" id="tr-all">Show whole recording</button>
      <button class="chip-btn on" id="tr-follow">Follow audio</button>
    </div>
    <div class="card transcript" id="tr"></div>`;
  const pfx = (rec) => (doc.recordings.length > 1 ? "P" + rec.slice(1) + " " : "");
  const draw = () => {
    let last = 0;
    const q = trState.q.toLowerCase();
    const rows = [];
    for (const it of items) {
      if (it.id) last = it.id;
      const ok = trState.all || inKid(it.id || last);
      if (!ok) continue;
      if (it.gap) {
        if (q) continue;
        rows.push(`<div class="line gap" data-rec="${it.rec}" data-start="${it.start}"><span class="ts">${pfx(it.rec)}${fmt(it.start)}</span><span class="who"></span><span class="tx">${it.gap === "playing" ? "♪ playing" : "… quiet"} · ${fmt(it.end - it.start)}</span></div>`);
        continue;
      }
      if (q && !it.text.toLowerCase().includes(q)) continue;
      const who = names[`${it.rec}:${it.speaker}`] || it.speaker;
      let tx = esc(it.text);
      if (q) tx = tx.replace(new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), (m) => `<mark>${m}</mark>`);
      rows.push(`<div class="line" data-rec="${it.rec}" data-start="${it.start}" data-id="${it.id}"><span class="ts">${pfx(it.rec)}${fmt(it.start)}</span><span class="who ${who === "Teacher" ? "teacher" : ""}">${esc(who)}</span><span class="tx">${tx}</span></div>`);
    }
    $("#tr").innerHTML = rows.join("") || `<div class="empty">No matches.</div>`;
  };
  draw();
  $("#tr-q").oninput = (e) => { trState.q = e.target.value.trim(); draw(); };
  $("#tr-all").onclick = (e) => { trState.all = !trState.all; e.target.classList.toggle("on", trState.all); draw(); };
  $("#tr-follow").onclick = (e) => { trState.follow = !trState.follow; e.target.classList.toggle("on", trState.follow); };
  $("#tr").onclick = (e) => {
    const line = e.target.closest(".line");
    if (!line) return;
    playClip({ date, rec: line.dataset.rec, start: Math.max(0, +line.dataset.start - 0.5), end: null, label: `${KIDS[kid].name} · transcript ${fmt(+line.dataset.start)}` });
  };
}
function followTranscript() {
  const tr = $("#tr");
  if (!tr || !trState || trState.date !== P.date) return;
  const t = audio.currentTime;
  let best = null;
  for (const el of tr.children) {
    if (el.dataset.rec !== P.rec) continue;
    if (+el.dataset.start <= t + 0.2) best = el; else if (best) break;
  }
  const prev = tr.querySelector(".line.active");
  if (best === prev) return;
  if (prev) prev.classList.remove("active");
  if (best) {
    best.classList.add("active");
    if (trState.follow && !audio.paused) best.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

/* ================================================================ kid profile */
async function viewKid(kid) {
  if (!KIDS[kid]) { location.hash = "#/"; return; }
  view.classList.add("kid-" + kid);
  chatScope = { date: null, kid };
  view.innerHTML = `<div class="empty"><div class="spinner" style="margin:auto"></div></div>`;
  const [prof, data] = await Promise.all([api(`/api/profiles/${kid}`), api("/api/lessons")]);
  const lessons = data.lessons.filter((l) => l.kids[kid]);
  const list = (arr) => (arr || []).map((x) => `<span class="tag">${esc(x)}</span>`).join("");
  const tech = (prof.technique_focus || []).map((t) => `<span class="tag ${esc(t.status)}" title="${esc(t.notes || "")}">${esc(t.area)} · ${esc(t.status)}</span>`).join("");
  view.innerHTML = `
    <div class="profile-hero">
      <div class="avatar">${KIDS[kid].name[0]}</div>
      <div><p class="eyebrow">Age ${KIDS[kid].age}</p><h1 class="title" style="margin:0">${KIDS[kid].name}</h1></div>
    </div>
    ${prof.updated ? `<p class="muted small">Profile updated after the ${esc(shortDate(prof.updated))} lesson</p>` : `<p class="muted">The learning profile builds up automatically after each lesson.</p>`}
    ${(prof.current_repertoire || []).length ? `<h2 class="section">Working on</h2><div class="tags">${list(prof.current_repertoire)}</div>` : ""}
    ${(prof.scales_etudes || []).length ? `<h2 class="section">Scales &amp; exercises</h2><div class="tags">${list(prof.scales_etudes)}</div>` : ""}
    ${tech ? `<h2 class="section">Technique</h2><div class="tags">${tech}</div><p class="muted small">Outline: orange = new, color = improving, green = solid</p>` : ""}
    ${(prof.recurring_feedback || []).length ? `<h2 class="section">What the teacher keeps saying</h2><div class="card list-card">${prof.recurring_feedback.map((x) => `<div class="row"><div class="body d">${esc(x)}</div></div>`).join("")}</div>` : ""}
    ${(prof.strengths || []).length ? `<h2 class="section">Going well</h2><div class="card list-card">${prof.strengths.map((x) => `<div class="row"><div class="body d">${esc(x)}</div></div>`).join("")}</div>` : ""}
    ${(prof.milestones || []).length ? `<h2 class="section">Milestones</h2><div class="card list-card">${prof.milestones.map((m) => `<div class="row"><span class="status checked">${esc(m.date ? shortDate(m.date) : "")}</span><div class="body d">${esc(m.text)}</div></div>`).join("")}</div>` : ""}
    <h2 class="section">Lessons <span class="count">${lessons.length}</span></h2>
    <div class="kid-rows">${lessons.map((l) => `
      <a class="kid-row kid-${kid}" href="#/l/${l.date}/${kid}" style="background:#fff;box-shadow:var(--shadow)">
        <div class="kid-dot">${esc(String(parseDate(l.date).getDate()))}</div>
        <div class="body"><div class="h">${esc(l.kids[kid].headline)}</div><div class="m">${esc(longDate(l.date))} · ${mins(l.kids[kid].minutes)}</div></div>
      </a>`).join("")}</div>`;
}

/* ================================================================ upload */
async function viewUpload() {
  const today = new Date();
  const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  view.innerHTML = `<div class="narrow">
    <p class="eyebrow">New lesson</p><h1 class="title">Add a lesson</h1>
    <p class="muted">Recordings, the homework note screenshot, and any lesson-book photos. Anything dropped in the
      <b>Music Lesson Recording</b> Google Drive folder (one folder per date, like <code>20261107</code>) is picked up automatically too.</p>
    <label class="field" for="up-date">Lesson date</label>
    <input class="input" type="date" id="up-date" value="${iso}">
    <label class="field">Files</label>
    <label class="drop" id="drop"><input type="file" id="up-files" multiple accept="audio/*,video/mp4,image/*,.m4a,.txt,.md" hidden>
      Tap to choose files, or drop them here</label>
    <div class="files" id="up-list"></div>
    <label class="field" for="up-notes">Homework notes (optional)</label>
    <textarea class="input" id="up-notes" rows="4" placeholder="Paste the notes you sent the teacher"></textarea>
    <div style="margin-top:20px"><button class="btn primary" id="up-go" disabled>Upload &amp; process</button></div>
    <div class="progress" hidden id="up-prog"><div></div></div>
    <div class="muted small" id="up-msg" style="margin-top:10px"></div></div>`;
  let files = [];
  const list = () => {
    $("#up-list").innerHTML = files.map((f) => `<div>• ${esc(f.name)} <span class="muted">${(f.size / 1e6).toFixed(1)} MB</span></div>`).join("");
    $("#up-go").disabled = !files.length;
  };
  $("#up-files").onchange = (e) => { files = [...files, ...e.target.files]; list(); };
  const drop = $("#drop");
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); files = [...files, ...e.dataTransfer.files]; list(); };
  $("#up-go").onclick = () => {
    const fd = new FormData();
    fd.append("date", $("#up-date").value);
    fd.append("notes", $("#up-notes").value);
    files.forEach((f) => fd.append("files", f, f.name));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    $("#up-prog").hidden = false;
    $("#up-go").disabled = true;
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) $("#up-prog div").style.width = (e.loaded / e.total) * 100 + "%"; };
    xhr.onload = () => {
      if (xhr.status === 401) return showLogin();
      if (xhr.status >= 300) { $("#up-msg").textContent = "Upload failed: " + xhr.responseText; $("#up-go").disabled = false; return; }
      $("#up-msg").textContent = "Uploaded. Processing usually takes 5-10 minutes.";
      setTimeout(() => (location.hash = "#/"), 1200);
    };
    xhr.onerror = () => { $("#up-msg").textContent = "Network error. Please try again."; $("#up-go").disabled = false; };
    xhr.send(fd);
  };
}

/* ================================================================ chat */
let chatScope = { date: null, kid: null };
const chats = {};
const chatKey = () => `${chatScope.date || "all"}|${chatScope.kid || "all"}`;

function md(text) {
  // Escape first, then apply a small, safe subset of markdown.
  let s = esc(text);
  s = s.replace(/\[\[clip:(\d{8}):(\d+)-(\d+)\]\]/g, (_, d, a, b) => `<button class="play" data-ids="${d}:${a}:${b}">listen</button>`);
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>");
  const out = [];
  let list = null;
  for (const line of s.split("\n")) {
    const ul = line.match(/^\s*[-•*]\s+(.*)/), ol = line.match(/^\s*\d+[.)]\s+(.*)/), h = line.match(/^#{1,4}\s+(.*)/), q = line.match(/^&gt;\s?(.*)/);
    if (ul || ol) {
      const tag = ul ? "ul" : "ol";
      if (list !== tag) { if (list) out.push(`</${list}>`); out.push(`<${tag}>`); list = tag; }
      out.push(`<li>${(ul || ol)[1]}</li>`);
      continue;
    }
    if (list) { out.push(`</${list}>`); list = null; }
    if (h) out.push(`<h4>${h[1]}</h4>`);
    else if (q) out.push(`<blockquote>${q[1]}</blockquote>`);
    else if (line.trim()) out.push(`<p>${line}</p>`);
  }
  if (list) out.push(`</${list}>`);
  return out.join("");
}

function openChat() {
  const k = chatKey();
  chats[k] = chats[k] || [];
  const name = chatScope.kid ? KIDS[chatScope.kid].name : null;
  $("#chat-scope").textContent = chatScope.date
    ? `About ${name ? name + "'s" : "the"} lesson on ${longDate(chatScope.date)}`
    : name ? `About ${name}'s lessons` : "About all lessons";
  const sug = name
    ? [`What should ${name} practice this week?`, `What did the teacher correct most?`, `Explain today's new ideas simply for ${name}`, `Play me the part about the bow hold`, "用中文总结这节课的重点"]
    : ["Summarize the latest lessons", "What is each kid working on?", "用中文总结最近的课"];
  $("#chat-suggest").innerHTML = sug.map((q) => `<button>${esc(q)}</button>`).join("");
  $$("#chat-suggest button").forEach((b) => (b.onclick = () => sendChat(b.textContent)));
  drawChat();
  $("#chat").hidden = false;
  document.body.style.overflow = "hidden";
  setTimeout(() => $("#chat-input").focus(), 100);
}
function closeChat() { $("#chat").hidden = true; document.body.style.overflow = ""; }
function drawChat() {
  const msgs = chats[chatKey()];
  $("#chat-log").innerHTML = msgs.length ? msgs.map((m) => m.role === "user"
    ? `<div class="msg user">${esc(m.content)}</div>`
    : `<div class="msg bot ${chatScope.kid ? "kid-" + chatScope.kid : ""}">${m.content ? md(m.content) : `<span class="typing"><i></i><i></i><i></i></span>`}</div>`).join("")
    : `<div class="empty small">Ask anything about the lesson. Answers point to the exact moments in the recording.</div>`;
  $("#chat-suggest").hidden = msgs.length > 0;
  const log = $("#chat-log");
  log.scrollTop = log.scrollHeight;
  labelChatClips();
}
async function labelChatClips() {
  for (const b of $$("#chat-log .play[data-ids]:not([data-labeled])")) {
    b.dataset.labeled = "1";
    const [date, a, z] = b.dataset.ids.split(":");
    try {
      const clip = await resolveIds(date, +a, +z);
      if (clip) b.textContent = clipTime(date, clip);
    } catch (_) { /* keep generic label */ }
  }
}
let chatBusy = false;
async function sendChat(text) {
  text = text.trim();
  if (!text || chatBusy) return;
  chatBusy = true;
  $(".send").disabled = true;
  const msgs = chats[chatKey()];
  msgs.push({ role: "user", content: text });
  const bot = { role: "assistant", content: "" };
  msgs.push(bot);
  drawChat();
  try {
    const r = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
      body: JSON.stringify({ messages: msgs.slice(0, -1), date: chatScope.date, kid: chatScope.kid }),
    });
    if (r.status === 401) { showLogin(); throw new Error("Please sign in again."); }
    if (!r.ok) throw new Error("The assistant is unavailable right now.");
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let last = 0;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      bot.content += dec.decode(value, { stream: true });
      if (Date.now() - last > 120) { drawChat(); last = Date.now(); }
    }
  } catch (err) {
    bot.content = bot.content || err.message;
  }
  drawChat();
  chatBusy = false;
  $(".send").disabled = false;
}
$("#ask-fab").onclick = openChat;
$("#chat-close").onclick = closeChat;
$("#chat").addEventListener("click", (e) => { if (e.target.id === "chat") closeChat(); });
$("#chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("#chat-input").value;
  $("#chat-input").value = "";
  sendChat(v);
});
$("#chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#chat-form").requestSubmit(); }
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#chat").hidden) closeChat(); });

/* ================================================================ boot */
(async function boot() {
  try {
    await api("/api/me");
    route();
  } catch (_) { /* login shown */ }
})();
