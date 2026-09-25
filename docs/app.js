"use strict";

// SecurCrew Pages UI — renders docs/data/items.json. Feed content is untrusted,
// so all values are inserted via textContent / DOM APIs (never innerHTML).

const state = {
  items: [],
  source: "",
  query: "",
  tag: "",
  visibleDays: 1,
};

const el = {
  grid: document.getElementById("grid"),
  empty: document.getElementById("empty"),
  stats: document.getElementById("stats"),
  updated: document.getElementById("updated"),
  search: document.getElementById("search"),
  sourceFilter: document.getElementById("sourceFilter"),
  showMore: document.getElementById("showMore"),
  count: document.getElementById("count"),
  activeFilters: document.getElementById("activeFilters"),
  toTop: document.getElementById("toTop"),
};

async function load() {
  showSkeletons();
  try {
    const res = await fetch("data/items.json", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    state.items = Array.isArray(data.items) ? data.items : [];
    renderStats(data);
    renderSources();
    render();
  } catch (err) {
    el.grid.replaceChildren();
    el.empty.hidden = false;
    el.empty.textContent = "Could not load the feed data yet.";
  }
}

function showSkeletons(n = 6) {
  const nodes = [];
  for (let i = 0; i < n; i++) {
    const s = document.createElement("div");
    s.className = "card skeleton";
    s.innerHTML =
      '<div class="sk-line sk-sm"></div><div class="sk-line sk-lg"></div>' +
      '<div class="sk-line"></div><div class="sk-line sk-md"></div>';
    nodes.push(s);
  }
  el.grid.replaceChildren(...nodes);
}

function renderStats(data) {
  const sources = new Set(state.items.map((i) => i.source).filter(Boolean)).size;
  el.stats.replaceChildren(
    stat(state.items.length, "Stories"),
    stat(sources, "Sources")
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
  el.sourceFilter.length = 1; // keep "All sources"
  for (const src of sources) {
    const opt = document.createElement("option");
    opt.value = src;
    opt.textContent = src;
    el.sourceFilter.appendChild(opt);
  }
}

function matches(i) {
  if (state.source && i.source !== state.source) return false;
  if (state.tag && !(Array.isArray(i.tags) && i.tags.includes(state.tag))) return false;
  const q = state.query.trim().toLowerCase();
  if (q) {
    const hay = (i.title + " " + i.summary + " " + i.source).toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

function isFiltering() {
  return Boolean(state.query.trim() || state.source || state.tag);
}

function render() {
  const items = state.items.filter(matches);
  const groups = groupByDay(items);
  const paging = !isFiltering();
  const shownGroups = paging ? groups.slice(0, state.visibleDays) : groups;

  const nodes = [];
  for (const g of shownGroups) {
    nodes.push(dayHeader(g.key, g.items.length));
    for (const it of g.items) nodes.push(card(it));
  }
  el.grid.replaceChildren(...nodes);

  const shown = shownGroups.reduce((n, g) => n + g.items.length, 0);
  el.count.textContent = state.items.length
    ? "Showing " + shown + " of " + state.items.length
    : "";

  el.empty.hidden = items.length !== 0;
  if (items.length === 0 && state.items.length > 0) {
    el.empty.textContent = "No stories match your filters.";
  }

  if (paging && groups.length > state.visibleDays) {
    const next = groups[state.visibleDays];
    el.showMore.hidden = false;
    el.showMore.textContent =
      "Show " + dayLabel(next.key) + " (" + next.items.length + ")";
  } else {
    el.showMore.hidden = true;
  }

  renderActiveFilters();
}

function renderActiveFilters() {
  const chips = [];
  if (state.tag) chips.push(filterChip("Tag " + state.tag, () => setTag("")));
  if (state.source) chips.push(filterChip("Source: " + state.source, () => {
    state.source = "";
    el.sourceFilter.value = "";
    state.visibleDays = 1;
    render();
  }));
  el.activeFilters.replaceChildren(...chips);
}

function filterChip(label, onClear) {
  const chip = document.createElement("button");
  chip.className = "active-chip";
  chip.textContent = label + "  ✕";
  chip.title = "Clear filter";
  chip.addEventListener("click", onClear);
  return chip;
}

function setTag(tag) {
  state.tag = tag;
  state.visibleDays = 1;
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function groupByDay(items) {
  const groups = [];
  const index = {};
  for (const it of items) {
    const key = dayKey(it);
    if (!(key in index)) {
      index[key] = groups.length;
      groups.push({ key, items: [] });
    }
    groups[index[key]].items.push(it);
  }
  return groups;
}

function dayKey(item) {
  const when = Number(item.published) || 0;
  if (!when) return "undated";
  const d = new Date(when * 1000);
  return (
    d.getFullYear() +
    "-" +
    String(d.getMonth() + 1).padStart(2, "0") +
    "-" +
    String(d.getDate()).padStart(2, "0")
  );
}

function dayLabel(key) {
  if (key === "undated") return "Undated";
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

function dayHeader(key, n) {
  const head = document.createElement("div");
  head.className = "day-head";
  const label = document.createElement("span");
  label.className = "day-label";
  label.textContent = dayLabel(key);
  const count = document.createElement("span");
  count.className = "day-count";
  count.textContent = n + (n === 1 ? " story" : " stories");
  head.append(label, count);
  return head;
}

function faviconEl(link) {
  let host;
  try {
    host = new URL(link).hostname;
  } catch (e) {
    return null;
  }
  const img = document.createElement("img");
  img.className = "favicon";
  img.width = 16;
  img.height = 16;
  img.loading = "lazy";
  img.alt = "";
  img.src = "https://www.google.com/s2/favicons?domain=" + host + "&sz=64";
  img.addEventListener("error", () => img.remove());
  return img;
}

function card(item) {
  const card = document.createElement("article");
  card.className = "card";
  const hasLink = item.link && /^https?:\/\//i.test(item.link);
  if (hasLink) {
    card.tabIndex = 0;
    card.classList.add("clickable");
    card.setAttribute("role", "link");
    card.setAttribute("aria-label", item.title || "Open source");
    const open = () => window.open(item.link, "_blank", "noopener,noreferrer");
    card.addEventListener("click", (e) => {
      if (e.target.closest("a,button,.tag")) return; // let inner controls act
      open();
    });
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter") open();
    });
  }

  const top = document.createElement("div");
  top.className = "card-top";
  const ai = document.createElement("span");
  ai.className = "aiflag " + (item.ai ? "on" : "off");
  ai.textContent = item.ai ? "✨" : "✂";
  ai.setAttribute("aria-label", item.ai ? "AI summary" : "Excerpt");
  ai.title = item.ai
    ? "Summary written by AI"
    : "Trimmed from the article's own text (no AI)";
  const time = document.createElement("span");
  time.className = "time";
  const when = Number(item.published) || 0;
  if (when) {
    const dt = new Date(when * 1000);
    time.textContent = dt.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
    time.title = "Published " + dt.toLocaleString();
  }
  top.append(ai, time);

  const h3 = document.createElement("h3");
  h3.append(highlight(item.title || "(untitled)"));

  const summary = document.createElement("p");
  summary.className = "summary";
  if (item.summary) summary.append(highlight(item.summary));

  const foot = document.createElement("div");
  foot.className = "card-foot";
  const source = document.createElement("span");
  source.className = "source";
  if (hasLink) {
    const fav = faviconEl(item.link);
    if (fav) source.append(fav);
  }
  source.append(document.createTextNode(item.source || ""));
  foot.append(source);

  if (hasLink) {
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
    const chip = document.createElement("button");
    chip.className = "tag";
    chip.textContent = t;
    chip.title = "Filter by " + t;
    if (t === state.tag) chip.classList.add("is-active");
    chip.addEventListener("click", (e) => {
      e.stopPropagation();
      setTag(t === state.tag ? "" : t);
    });
    row.append(chip);
  }
  return row;
}

// Wrap query matches in <mark> without using innerHTML on untrusted text.
function highlight(text) {
  const q = state.query.trim();
  if (!q) return document.createTextNode(text);
  const frag = document.createDocumentFragment();
  const lower = text.toLowerCase();
  const needle = q.toLowerCase();
  let i = 0;
  let idx;
  while ((idx = lower.indexOf(needle, i)) !== -1) {
    if (idx > i) frag.append(document.createTextNode(text.slice(i, idx)));
    const mark = document.createElement("mark");
    mark.textContent = text.slice(idx, idx + needle.length);
    frag.append(mark);
    i = idx + needle.length;
  }
  if (i < text.length) frag.append(document.createTextNode(text.slice(i)));
  return frag;
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
  state.visibleDays = 1;
  render();
});
el.sourceFilter.addEventListener("change", (e) => {
  state.source = e.target.value;
  state.visibleDays = 1;
  render();
});
el.showMore.addEventListener("click", () => {
  state.visibleDays += 1;
  render();
});
el.toTop.addEventListener("click", () =>
  window.scrollTo({ top: 0, behavior: "smooth" })
);
window.addEventListener("scroll", () => {
  el.toTop.hidden = window.scrollY < 600;
});

load();
