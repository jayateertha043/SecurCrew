"use strict";

// SecurCrew Pages UI — renders docs/data/items.json. Feed content is untrusted,
// so all values are inserted via textContent / DOM APIs (never innerHTML).

const state = {
  items: [],
  status: "all",
  source: "",
  query: "",
};

const el = {
  grid: document.getElementById("grid"),
  empty: document.getElementById("empty"),
  stats: document.getElementById("stats"),
  updated: document.getElementById("updated"),
  search: document.getElementById("search"),
  sourceFilter: document.getElementById("sourceFilter"),
  chips: Array.from(document.querySelectorAll(".chip")),
};

async function load() {
  try {
    const res = await fetch("data/items.json", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    state.items = Array.isArray(data.items) ? data.items : [];
    renderStats(data);
    renderSources();
    render();
  } catch (err) {
    el.empty.hidden = false;
    el.empty.textContent = "Could not load the feed data yet.";
  }
}

function renderStats(data) {
  const sources = new Set(state.items.map((i) => i.source).filter(Boolean)).size;
  const shared = state.items.filter((i) => i.status === "posted").length;
  el.stats.replaceChildren(
    stat(state.items.length, "Stories"),
    stat(sources, "Sources"),
    stat(shared, "Shared")
  );
  if (data.generated_at) {
    el.updated.textContent = "Updated " + timeAgo(data.generated_at * 1000);
  }
}

function stat(value, label) {
  const wrap = document.createElement("div");
  wrap.className = "stat";
  const b = document.createElement("b");
  b.textContent = String(value);
  const s = document.createElement("span");
  s.textContent = label;
  wrap.append(b, s);
  return wrap;
}

function renderSources() {
  const sources = Array.from(
    new Set(state.items.map((i) => i.source).filter(Boolean))
  ).sort((a, b) => a.localeCompare(b));
  // Keep the "All sources" option, replace the rest.
  el.sourceFilter.length = 1;
  for (const src of sources) {
    const opt = document.createElement("option");
    opt.value = src;
    opt.textContent = src;
    el.sourceFilter.appendChild(opt);
  }
}

function filtered() {
  const q = state.query.trim().toLowerCase();
  return state.items.filter((i) => {
    if (state.status !== "all" && i.status !== state.status) return false;
    if (state.source && i.source !== state.source) return false;
    if (q) {
      const hay = (i.title + " " + i.summary + " " + i.source).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function render() {
  const items = filtered();
  el.grid.replaceChildren(...items.map(card));
  el.empty.hidden = items.length !== 0;
  if (items.length === 0 && state.items.length > 0) {
    el.empty.textContent = "No stories match your filters.";
  }
}

function card(item) {
  const card = document.createElement("article");
  card.className = "card";

  const top = document.createElement("div");
  top.className = "card-top";
  const badge = document.createElement("span");
  badge.className = "badge " + (item.status === "posted" ? "posted" : "queued");
  badge.textContent = item.status === "posted" ? "Shared" : "New";
  const ai = document.createElement("span");
  ai.className = "aiflag " + (item.ai ? "on" : "off");
  ai.textContent = item.ai ? "AI summary" : "Excerpt";
  ai.title = item.ai
    ? "Summary written by AI"
    : "Trimmed from the article's own text (no AI)";
  const time = document.createElement("span");
  time.className = "time";
  const when = Number(item.published) || 0;  // RSS publish date only
  time.textContent = when ? timeAgo(when * 1000) : "";
  top.append(badge, ai, time);

  const h3 = document.createElement("h3");
  h3.textContent = item.title || "(untitled)";

  const summary = document.createElement("p");
  summary.className = "summary";
  summary.textContent = item.summary || "";

  const foot = document.createElement("div");
  foot.className = "card-foot";
  const source = document.createElement("span");
  source.className = "source";
  source.textContent = item.source || "";
  foot.append(source);

  if (item.link && /^https?:\/\//i.test(item.link)) {
    const a = document.createElement("a");
    a.className = "readmore";
    a.href = item.link;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = "Read source →";
    foot.append(a);
  }

  card.append(top, h3);
  if (item.summary) card.append(summary);
  if (Array.isArray(item.tags) && item.tags.length) card.append(tagRow(item.tags));
  card.append(foot);
  return card;
}

function tagRow(tags) {
  const row = document.createElement("div");
  row.className = "tags";
  for (const t of tags) {
    if (typeof t !== "string") continue;
    const chip = document.createElement("span");
    chip.className = "tag";
    chip.textContent = t;
    row.append(chip);
  }
  return row;
}

function timeAgo(ms) {
  const diff = Date.now() - ms;
  if (!ms || diff < 0) return "just now";
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return mins + "m ago";
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + "h ago";
  const days = Math.floor(hrs / 24);
  return days + "d ago";
}

// Events
el.search.addEventListener("input", (e) => {
  state.query = e.target.value;
  render();
});
el.sourceFilter.addEventListener("change", (e) => {
  state.source = e.target.value;
  render();
});
el.chips.forEach((chip) => {
  chip.addEventListener("click", () => {
    el.chips.forEach((c) => c.classList.remove("is-active"));
    chip.classList.add("is-active");
    state.status = chip.dataset.status;
    render();
  });
});

load();
