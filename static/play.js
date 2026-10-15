// play.js — the player's phone view: bingo grid, challenge cards, the
// submit sheet (with photo compression + video length check) and leaderboard.

const G = window.GAME;
const $ = (id) => document.getElementById(id);
let subs = {};
let current = null;   // activity open in the sheet
let chosen = null;    // {blob, kind, name} ready to upload

const STATUS_TEXT = {
  done: "✓ Done",
  pending: "⏳ Waiting for approval (points count already)",
  approved: "✓ Points counted",
  rejected: "✗ Rejected — try again",
};

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.setAttribute("aria-selected", x === t));
    document.querySelectorAll("[data-panel]").forEach((p) => (p.hidden = p.dataset.panel !== t.dataset.tab));
    if (t.dataset.tab === "board") loadBoard();
  })
);

// ---------- rendering ----------
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function renderBingo() {
  const grid = $("bingo");
  grid.replaceChildren();
  for (const sq of G.bingo) {
    const s = subs[sq.id];
    const b = el("button", "sq", sq.title);
    b.type = "button";
    if (sq.id === "free") {
      b.classList.add("free");
      b.disabled = true;
    } else {
      if (s) b.classList.add(s.status === "approved" ? "done" : s.status);
      if (s && s.status !== "rejected" && s.note) b.append(el("span", "who-found", s.note));
      b.addEventListener("click", () => openSheet(sq));
    }
    grid.append(b);
  }
}

function renderCards(containerId, items) {
  const box = $(containerId);
  box.replaceChildren();
  for (const a of items) {
    const s = subs[a.id];
    const card = el("button", "card");
    card.type = "button";
    const body = el("div", "body");
    body.append(el("h3", null, a.title), el("p", null, a.detail));
    if (s) body.append(el("span", `chip ${s.status}`, STATUS_TEXT[s.status]));
    if (s && s.status !== "rejected") card.classList.add("complete");
    card.append(body, el("span", "pts", `+${a.points}`));
    card.addEventListener("click", () => openSheet(a));
    box.append(card);
  }
}

async function refresh() {
  try {
    const r = await fetch("/api/me");
    if (r.status === 401) return (location.href = "/");
    const me = await r.json();
    Object.assign(G, me.game); // picks up activity edits made in /admin/content
    subs = me.submissions;
    // Admin hid it from the projector; to the player it's still approved.
    for (const s of Object.values(subs)) if (s.status === "hidden") s.status = "approved";
    $("points").textContent = me.points;
    $("rank").textContent = me.rank ? `#${me.rank} of ${me.players}` + (me.lines ? ` · ${me.lines} bingo` : "") : "";
    renderBingo();
    renderCards("challenges", G.challenges);
    renderCards("perform", G.performances);
  } catch (_) { /* flaky wifi — the next poll will catch up */ }
}

async function loadBoard() {
  const r = await fetch("/api/screen");
  const { leaderboard } = await r.json();
  const ol = $("board");
  ol.replaceChildren();
  if (!leaderboard.length) ol.append(el("li", null, "No one yet — be first!"));
  leaderboard.forEach((b, i) => {
    const li = el("li", b.name === window.ME ? "me" : "");
    const nm = el("span", "nm", b.name);
    if (b.role) nm.append(el("small", null, b.role));
    li.append(el("span", "pos", ["🥇", "🥈", "🥉"][i] || i + 1), nm, el("span", "p", b.points));
    ol.append(li);
  });
}

// ---------- submit sheet ----------
const PICKER = {
  name: { label: "📷 Add a selfie together (optional)", accept: "image/*" },
  photo: { label: "📷 Take or choose a photo", accept: "image/*" },
  video: { label: "🎥 Record or choose a video", accept: "video/*" },
  either: { label: "📷 🎥 Photo or video", accept: "image/*,video/*" },
};

function openSheet(a) {
  current = a;
  chosen = null;
  const s = subs[a.id];
  $("sheet-title").textContent = a.title;
  $("sheet-detail").textContent = `${a.detail} · +${a.points} pts`;
  $("sheet-status").replaceChildren(s ? el("span", `chip ${s.status}`, STATUS_TEXT[s.status]) : "");
  $("note-field").hidden = a.proof !== "name";
  $("note").value = s && s.status !== "rejected" ? s.note : "";
  $("picker-label").textContent = PICKER[a.proof].label;
  $("picker-hint").textContent = a.proof === "photo" || a.proof === "name" ? "" :
    `Videos up to ${G.maxVideoSeconds} seconds`;
  $("file").accept = PICKER[a.proof].accept;
  $("file").value = "";
  showPreview(s && s.status !== "rejected" && s.mediaUrl ? { url: s.mediaUrl, kind: s.mediaType } : null);
  $("sheet-error").hidden = true;
  $("progress").hidden = true;
  $("submit").hidden = false;
  $("submit").disabled = false;
  $("submit").textContent = s && s.status !== "rejected" ? "Replace submission" : "Submit";
  $("undo").hidden = !s;
  $("sheet").hidden = false;
  if (a.proof === "name") setTimeout(() => $("note").focus(), 50);
}

function closeSheet() {
  $("sheet").hidden = true;
  showPreview(null);
}
$("sheet-close").addEventListener("click", closeSheet);
$("sheet").addEventListener("click", (e) => { if (e.target === $("sheet")) closeSheet(); });

function showPreview(media) {
  const box = $("preview");
  const old = box.querySelector("[data-blob]");
  if (old) URL.revokeObjectURL(old.src);
  box.replaceChildren();
  box.hidden = !media;
  if (!media) return;
  const m = document.createElement(media.kind === "video" ? "video" : "img");
  m.src = media.url;
  if (media.blob) m.dataset.blob = "1";
  if (media.kind === "video") { m.controls = true; m.playsInline = true; }
  box.append(m);
}

function fail(msg) {
  $("sheet-error").textContent = msg;
  $("sheet-error").hidden = false;
}

// Shrinks big phone photos (often 4–10 MB) to ~300 KB before upload.
async function compressImage(file) {
  if (file.type === "image/gif") return file;
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * scale);
    c.height = Math.round(bmp.height * scale);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    const blob = await new Promise((res) => c.toBlob(res, "image/jpeg", 0.82));
    return blob && blob.size < file.size ? blob : file;
  } catch (_) {
    return file; // e.g. HEIC on a browser that can't decode it — send as is
  }
}

function videoDuration(file) {
  return new Promise((resolve) => {
    const v = document.createElement("video");
    v.preload = "metadata";
    v.onloadedmetadata = () => { URL.revokeObjectURL(v.src); resolve(v.duration); };
    v.onerror = () => resolve(null); // unknown format: let the server decide
    v.src = URL.createObjectURL(file);
  });
}

$("file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  $("sheet-error").hidden = true;
  chosen = null;
  if (!file) return;
  const kind = file.type.startsWith("video/") ? "video" : "image";
  if (kind === "video") {
    const secs = await videoDuration(file);
    if (secs && secs > G.maxVideoSeconds + 0.5)
      return fail(`That video is ${Math.round(secs)}s — keep it under ${G.maxVideoSeconds}s.`);
    if (file.size > G.maxUploadMb * 1024 * 1024)
      return fail(`That video is too big (${Math.round(file.size / 1048576)} MB). Record a shorter clip.`);
    chosen = { blob: file, kind, name: file.name };
  } else {
    const blob = await compressImage(file);
    chosen = { blob, kind, name: blob === file ? file.name : "photo.jpg" };
  }
  showPreview({ url: URL.createObjectURL(chosen.blob), kind, blob: true });
});

// XHR rather than fetch so we can show upload progress on slow wifi.
// Resolves to { status, body } (body parsed as JSON when possible).
function send(method, url, data, { contentType, onProgress } = {}) {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    if (onProgress) xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) onProgress(ev.loaded / ev.total); };
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch (_) {}
      resolve({ status: xhr.status, body });
    };
    xhr.onerror = () => resolve({ status: 0, body: {} });
    xhr.open(method, url);
    if (contentType) xhr.setRequestHeader("Content-Type", contentType);
    xhr.send(data);
  });
}

function form(fields) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.append(k, v);
  return fd;
}

$("sheet-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const a = current;
  const note = $("note").value.trim();
  if (a.proof === "name" && !note) return fail("Type the name of the person you found.");
  if (a.proof !== "name" && !chosen) return fail("Add your photo or video first.");

  const bar = $("progress");
  const progress = (f) => { bar.firstElementChild.style.width = `${f * 100}%`; };
  bar.hidden = !chosen;
  progress(0);
  $("submit").disabled = true;
  $("submit").textContent = chosen ? "Uploading…" : "Saving…";
  const retry = (msg) => {
    $("submit").disabled = false;
    $("submit").textContent = "Try again";
    fail(msg || "Upload failed — check your connection and try again.");
  };

  const fd = form({ activity_id: a.id, note });
  if (chosen && G.directUpload) {
    // Straight to Supabase: the app's host can't take big files.
    const type = chosen.blob.type;
    const r = await send("POST", "/api/upload-url",
      form({ activity_id: a.id, content_type: type, size: chosen.blob.size }));
    if (r.status !== 200) return retry(r.body.error);
    const up = await send("PUT", r.body.url, chosen.blob, { contentType: type, onProgress: progress });
    if (up.status !== 200) return retry(up.body.message);
    fd.append("media_key", r.body.key);
  } else if (chosen) {
    fd.append("media", chosen.blob, chosen.name);
  }

  const r = await send("POST", "/api/submit", fd, { onProgress: G.directUpload ? null : progress });
  if (r.status !== 200) return retry(r.body.error);
  closeSheet();
  toast(r.body.status === "approved" ? "Sent! Points added — it's on the big screen." : "Nice! Points added.");
  refresh();
});

$("undo").addEventListener("click", async () => {
  if (!confirm("Remove this submission and its points?")) return;
  const fd = new FormData();
  fd.append("activity_id", current.id);
  await fetch("/api/undo", { method: "POST", body: fd });
  closeSheet();
  refresh();
});

let toastTimer;
function toast(msg) {
  $("toast").textContent = msg;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("toast").hidden = true), 3200);
}

refresh();
setInterval(() => { if (!document.hidden && $("sheet").hidden) refresh(); }, 15000);
