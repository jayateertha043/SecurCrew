"use strict";

// SecurCrew Pages UI — renders docs/data/items.json. Feed content is untrusted,
// so all values are inserted via textContent / DOM APIs (never innerHTML).

const state = {
  items: [],
  source: "",
  query: "",
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
  // While browsing (no search/source), page by day: show the latest day first
  // and reveal older days via "Show more". Filtering shows all matches at once.
  const paging = !state.query.trim() && !state.source;

  let toShow = items;
  let groups = [];
  if (paging) {
    groups = groupByDay(items);
    toShow = groups.slice(0, state.visibleDays).flatMap((g) => g.items);
  }

  el.grid.replaceChildren(...toShow.map(card));
  el.empty.hidden = toShow.length !== 0;
  if (toShow.length === 0 && state.items.length > 0) {
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
  if (key === "undated") return "undated";
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

function card(item) {
  const card = document.createElement("article");
  card.className = "card";

  const top = document.createElement("div");
  top.className = "card-top";
  const ai = document.createElement("span");
  ai.className = "aiflag " + (item.ai ? "on" : "off");
  ai.textContent = item.ai ? "AI summary" : "Excerpt";
  ai.title = item.ai
    ? "Summary written by AI"
    : "Trimmed from the article's own text (no AI)";
  const time = document.createElement("span");
  time.className = "time";
  const when = Number(item.published) || 0;  // RSS publish date only
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

load();
