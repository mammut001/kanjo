// Family dashboard v2: switches time ranges without a reload, sorts the ranking,
// and shows chart readouts. Data comes from <script type="application/json" id="dash-data">
// (never executed). The server already rendered the requested range; this file
// re-renders the range-dependent sections with the same markup as dashboard_view.py.
// All data is inserted with textContent / setAttribute, never parsed as HTML.
(function () {
  "use strict";

  // Reset countdowns tick even if the data block is missing; same text as countdown_text() in Python.
  function countdownText(ms) {
    var secs = Math.floor(ms / 1000);
    if (secs <= 0) return "已到重置时间";
    var days = Math.floor(secs / 86400);
    var hours = Math.floor((secs % 86400) / 3600);
    var minutes = Math.floor((secs % 3600) / 60);
    if (days > 0) return days + " 天 " + hours + " 小时 " + minutes + " 分";
    if (hours > 0) return hours + " 小时 " + minutes + " 分";
    if (minutes > 0) return minutes + " 分钟";
    return "不到 1 分钟";
  }
  function tickCountdowns() {
    var now = Date.now();
    var els = document.querySelectorAll("[data-reset-at]");
    for (var i = 0; i < els.length; i++) {
      var at = Date.parse(els[i].getAttribute("data-reset-at"));
      if (!isNaN(at)) els[i].textContent = countdownText(at - now);
    }
  }
  tickCountdowns();
  setInterval(tickCountdowns, 15000);

  var dataEl = document.getElementById("dash-data");
  if (!dataEl) return;
  var DATA;
  try {
    DATA = JSON.parse(dataEl.textContent);
  } catch (e) {
    return;
  }

  var SVG_NS = "http://www.w3.org/2000/svg";
  var LABELS = {};
  DATA.order.forEach(function (pair) { LABELS[pair[0]] = pair[1]; });
  var MEMBERS = {};
  DATA.members.forEach(function (m) { MEMBERS[m.id] = m; });
  var STATUS_TEXT = { ok: "正常", stale: "超过 2 小时未上报", never: "从未上报" };
  var STATUS_CLASS = { ok: "badge badge-active", stale: "badge badge-stale", never: "badge badge-stale badge-never" };
  var MODES = [["person", "按人"], ["model", "按模型"], ["agent", "按代理"]];

  var state = { range: DATA.range, sortKey: "tokens", sortDir: "descending" };

  // ------------------------------------------------------------ formatting
  function fmtTokens(n) {
    if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
    return String(n);
  }
  function fmtCost(c) {
    return "$" + Number(c).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function md(iso) {
    if (!iso) return "";
    if (iso.length === 10) return iso.slice(5, 7) + "/" + iso.slice(8, 10);
    return iso;
  }
  function signed(p) {
    return (p > 0 ? "+" : p < 0 ? "-" : "+") + Math.abs(p).toFixed(1) + "%";
  }
  function formatChange(pct, cur, prev) {
    if (prev === null || prev === undefined) return ["—", ""];
    if (prev <= 0) return cur > 0 ? ["新增", "up"] : ["—", ""];
    if (pct === null || Math.abs(pct) < 0.05) return ["0.0%", ""];
    return [signed(pct), pct > 0 ? "up" : "down"];
  }
  function rangeTitle(r) {
    if (r.key === "all") return r.label;
    if (r.start === r.end) return r.label + " · " + md(r.start);
    return r.label + " · " + md(r.start) + " – " + md(r.end);
  }

  // ------------------------------------------------------------ DOM helpers
  function h(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined && text !== null) el.textContent = String(text);
    return el;
  }
  function add(parent) {
    for (var i = 1; i < arguments.length; i++) {
      if (arguments[i]) parent.appendChild(arguments[i]);
    }
    return parent;
  }
  function svg(tag, attrs) {
    var el = document.createElementNS(SVG_NS, tag);
    for (var k in attrs) {
      if (Object.prototype.hasOwnProperty.call(attrs, k)) el.setAttribute(k, attrs[k]);
    }
    return el;
  }
  function dot(color) {
    var d = h("span", "color-dot");
    d.style.background = color;
    return d;
  }
  function shareCell(share, color, cls) {
    var cell = h("div", "share-cell" + (cls ? " " + cls : ""));
    var bg = h("div", "share-bar-bg");
    var fill = h("div", "share-bar-fill");
    fill.style.width = Math.min(100, share).toFixed(1) + "%";
    fill.style.background = color;
    add(cell, add(bg, fill), h("span", "share-pct", share.toFixed(1) + "%"));
    return cell;
  }

  // ------------------------------------------------------------ overview
  function renderOverview(r, key) {
    var sec = h("section", "card");
    var head = h("div", "section-head");
    sec.appendChild(head);
    if (!r) {
      head.appendChild(h("h2", "section-title", LABELS[key]));
      sec.appendChild(h("div", "empty-state", "暂无 Google AI Ultra 额度重置时间，无法计算「重置以来」。"));
      return sec;
    }
    head.appendChild(h("h2", "section-title", rangeTitle(r)));
    if (r.note) head.appendChild(h("span", "range-note", r.note));
    var grid = h("div", "stat-grid");
    sec.appendChild(grid);
    function stat(label, value, sub, cls) {
      add(grid, add(h("div", "stat"), h("div", "stat-label", label),
        h("div", "stat-value" + (cls ? " " + cls : ""), value), h("div", "stat-sub", sub)));
    }
    var tot = r.total;
    var tokens = tot.tokens.total;
    stat("总 token", fmtTokens(tokens), "折算 " + fmtCost(tot.cost));
    if (r.compare_label && tot.prev_tokens !== null) {
      if (r.compare_mode === "reference") {
        stat(r.compare_label, fmtTokens(tot.prev_tokens), "折算 " + fmtCost(tot.prev_cost || 0));
      } else {
        var ch = formatChange(tot.change_pct, tokens, tot.prev_tokens);
        stat(r.compare_label, ch[0], r.compare_label.slice(1) + " " + fmtTokens(tot.prev_tokens), ch[1]);
      }
    }
    stat("活跃成员", r.active_members + "/" + r.member_count, "该时段有用量");
    if (r.elapsed_days > 1) stat("日均 token", fmtTokens(r.daily_avg), "按 " + r.elapsed_days + " 天");
    if (r.peak && r.elapsed_days > 1 && r.peak.tokens < tokens) stat(r.bucket === "day" ? "峰值日" : "峰值月", fmtTokens(r.peak.tokens), md(r.peak.key));
    return sec;
  }

  // ------------------------------------------------------------ trend
  function niceMax(v) {
    if (v <= 0) return 1000;
    var mag = Math.pow(10, Math.max(0, String(Math.floor(v)).length - 1));
    return Math.ceil(v / mag) * mag;
  }

  function trendSvg(chart, series) {
    var buckets = chart.buckets;
    var n = Math.max(1, buckets.length);
    var width = Math.max(720, 70 + n * 24), height = 220;
    var ml = 56, mr = 12, mt = 14, mb = 28;
    var pw = width - ml - mr, ph = height - mt - mb;
    var slot = pw / n, bw = Math.min(slot * 0.7, 48);
    var yMax = niceMax(Math.max.apply(null, chart.totals.concat([0])));
    var root = svg("svg", { "class": "chart-svg", viewBox: "0 0 " + width + " " + height, role: "img", "aria-label": "用量趋势图" });
    if (n > 12) root.style.minWidth = (n * 16 + 70) + "px";
    [0, 0.5, 1].forEach(function (f) {
      var y = mt + ph * (1 - f);
      root.appendChild(svg("line", { x1: ml, y1: y.toFixed(1), x2: width - mr, y2: y.toFixed(1), stroke: "var(--bar-grid)", "stroke-dasharray": "3,3" }));
      var t = svg("text", { x: ml - 8, y: (y + 4).toFixed(1), "text-anchor": "end", fill: "var(--text-muted)", "font-size": "11" });
      t.textContent = fmtTokens(Math.floor(yMax * f));
      root.appendChild(t);
    });
    var step = Math.max(1, Math.ceil(n / 12));
    buckets.forEach(function (b, i) {
      var x = ml + i * slot + (slot - bw) / 2;
      var yCur = mt + ph;
      series.forEach(function (s) {
        var v = s.values[i];
        if (v <= 0) return;
        var hgt = v / yMax * ph;
        yCur -= hgt;
        root.appendChild(svg("rect", { x: x.toFixed(1), y: yCur.toFixed(1), width: bw.toFixed(1), height: hgt.toFixed(1), fill: s.color, rx: "2" }));
      });
      if (i % step === 0 || i === n - 1) {
        var t = svg("text", { x: (x + bw / 2).toFixed(1), y: height - 9, "text-anchor": "middle", fill: "var(--text-muted)", "font-size": "10" });
        t.textContent = md(b);
        root.appendChild(t);
      }
    });
    buckets.forEach(function (b, i) {
      var hit = svg("rect", { "class": "hit", "data-i": i, x: (ml + i * slot).toFixed(1), y: mt, width: slot.toFixed(1), height: ph });
      var title = svg("title", {});
      title.textContent = readoutLines(chart, series, i).join("\n");
      hit.appendChild(title);
      root.appendChild(hit);
    });
    return root;
  }

  function readoutLines(chart, series, i) {
    var lines = [md(chart.buckets[i]) + " 合计 " + fmtTokens(chart.totals[i])];
    series.forEach(function (s) {
      if (s.values[i] > 0) lines.push(s.label + " " + fmtTokens(s.values[i]));
    });
    return lines;
  }

  function renderTrend(r, mode) {
    var sec = h("section", "card trend");
    MODES.forEach(function (m) {
      var input = h("input", "mode-radio");
      input.type = "radio";
      input.name = "trend-mode";
      input.id = "tm-" + m[0];
      input.value = m[0];
      if (m[0] === mode) input.checked = true;
      sec.appendChild(input);
    });
    var head = h("div", "section-head");
    var title = h("h2", "section-title", "趋势");
    title.appendChild(h("span", "section-sub", " · " + (r.bucket === "day" ? "每天" : "每月") + "一根"));
    var sw = h("div", "mode-switch");
    sw.setAttribute("role", "radiogroup");
    sw.setAttribute("aria-label", "趋势分组");
    MODES.forEach(function (m) {
      var lab = h("label", null, m[1]);
      lab.htmlFor = "tm-" + m[0];
      sw.appendChild(lab);
    });
    add(sec, add(head, title, sw));
    MODES.forEach(function (m) {
      var series = r.chart[m[0]];
      var panel = h("div", "trend-panel trend-" + m[0]);
      sec.appendChild(panel);
      if (!series.length) {
        panel.appendChild(h("div", "empty-state", "该时段暂无用量"));
        return;
      }
      var legend = h("div", "chart-legend");
      series.forEach(function (s) {
        add(legend, add(h("span", "legend-item"), dot(s.color), document.createTextNode(s.label)));
      });
      add(panel, legend, add(h("div", "chart-scroll"), trendSvg(r.chart, series)));
    });
    var readout = h("div", "chart-readout");
    readout.setAttribute("aria-live", "polite");
    sec.appendChild(readout);
    return sec;
  }

  // ------------------------------------------------------------ ranking
  function miniSvg(values, color) {
    var n = Math.max(1, values.length);
    var vmax = Math.max.apply(null, values.concat([0])) || 1;
    var root = svg("svg", { "class": "mini-svg", viewBox: "0 0 " + (n * 10) + " 48", preserveAspectRatio: "none", role: "img", "aria-label": "每日用量" });
    values.forEach(function (v, i) {
      if (v <= 0) return;
      var hgt = Math.max(1.5, v / vmax * 46);
      root.appendChild(svg("rect", { x: i * 10 + 1, y: (48 - hgt).toFixed(1), width: 8, height: hgt.toFixed(1), fill: color, rx: "1" }));
    });
    return root;
  }

  function rankRow(row, meta, r) {
    var ch = formatChange(row.change_pct, row.tokens, row.prev_tokens);
    var changeSort = row.change_pct !== null ? row.change_pct : (ch[0] === "新增" ? 1e12 : -1e12);
    var det = h("details", "rank-row");
    det.setAttribute("data-name", meta.name);
    det.setAttribute("data-tokens", row.tokens);
    det.setAttribute("data-cost", row.cost);
    det.setAttribute("data-change", changeSort);
    det.setAttribute("data-model", row.top_model || "");
    det.setAttribute("data-last", meta.received_ts);

    var sum = h("summary", "rank-line");
    var nameBox = h("div", "cell");
    nameBox.appendChild(h("div", "member-title", meta.name));
    if (meta.label) nameBox.appendChild(h("div", "member-label", meta.label));
    add(sum,
      add(h("div", "cell cell-name c-name"), dot(meta.color), nameBox),
      h("div", "cell cell-num c-tokens", fmtTokens(row.tokens)),
      h("div", "cell cell-num c-cost", fmtCost(row.cost)),
      shareCell(row.share, meta.color, "cell c-share"),
      h("div", "cell cell-num c-change" + (ch[1] ? " " + ch[1] : ""), ch[0]),
      h("div", "cell cell-small c-model", row.top_model || "—"),
      h("div", "cell cell-small c-last", meta.received),
      add(h("div", "cell c-status"), h("span", STATUS_CLASS[meta.status], STATUS_TEXT[meta.status])));
    det.appendChild(sum);

    var detail = h("div", "rank-detail");
    var metaLine = h("div", "detail-meta");
    metaLine.appendChild(h("span", null, "上次上报：" + meta.received));
    if (meta.scope) metaLine.appendChild(h("span", "member-scope", meta.scope));
    if (meta.legacy) metaLine.appendChild(h("span", "legacy-note", meta.legacy + " 台电脑使用旧版 Kanjo 未计入 — 请更新客户端以合并统计"));
    detail.appendChild(metaLine);

    var grid = h("div", "detail-grid");
    var models = add(h("div", "detail-block"), h("h4", null, "模型明细"));
    if (row.models.length) {
      var table = h("table", "mini-table");
      var thead = h("thead");
      add(thead, add(h("tr"), h("th", null, "模型"), h("th", "text-right", "Token"), h("th", "text-right", "折算金额")));
      var tbody = h("tbody");
      row.models.forEach(function (mr) {
        var tr = h("tr", mr.other ? "other-row" : null);
        var td = h("td", null, mr.model);
        td.title = mr.model;
        add(tbody, add(tr, td, h("td", "text-right", fmtTokens(mr.tokens)), h("td", "text-right", fmtCost(mr.cost))));
      });
      add(models, add(table, thead, tbody));
    } else {
      models.appendChild(h("div", "muted", "该时段暂无模型用量明细"));
    }
    grid.appendChild(models);

    var devBlock = h("div", "detail-block");
    var devices = meta.devices || [];
    if (devices.length) {
      devBlock.appendChild(h("h4", null, devices.length + " 台电脑"));
      var list = h("div", "device-list");
      devices.forEach(function (dev, i) {
        var dr = row.devices[i] || { tokens: 0, cost: 0 };
        var item = h("div", "device-item");
        add(item,
          add(h("div", "device-item-top"), h("span", "device-name", dev.name),
            h("span", "device-totals", fmtTokens(dr.tokens) + " (" + fmtCost(dr.cost) + ")")),
          add(h("div", "device-item-meta"), h("span", null, dev.os), h("span", null, dev.version), h("span", null, dev.tz),
            h("span", null, "上次上报：" + dev.received),
            h("span", null, "累计 " + fmtTokens(dev.all_tokens) + " (" + fmtCost(dev.all_cost) + ")")));
        list.appendChild(item);
      });
      devBlock.appendChild(list);
    } else {
      add(devBlock, h("h4", null, "电脑"), h("div", "muted", "从未上报"));
    }
    grid.appendChild(devBlock);
    if (r.chart.buckets.length) {
      grid.appendChild(add(h("div", "detail-block detail-wide"),
        h("h4", null, (r.bucket === "day" ? "每日" : "每月") + "用量"), miniSvg(row.series, meta.color)));
    }
    detail.appendChild(grid);
    det.appendChild(detail);
    return det;
  }

  var RANK_COLUMNS = [
    ["name", "成员", "c-name"], ["tokens", "Token", "c-tokens cell-num"], ["cost", "金额", "c-cost cell-num"],
    ["tokens", "占比", "c-share"], ["change", "变化", "c-change cell-num"], ["model", "常用模型", "c-model"],
    ["last", "最后上报", "c-last"], [null, "状态", "c-status"]
  ];

  function renderRanking(r) {
    var sec = h("section", "card ranking");
    add(sec, add(h("div", "section-head"), h("h2", "section-title", "成员排行"),
      h("span", "section-sub", "点一行展开模型、电脑和每日用量")));
    if (!r.members.length) {
      sec.appendChild(h("div", "empty-state", "尚未添加任何成员"));
      return sec;
    }
    var table = h("div", "rank-table");
    var head = h("div", "rank-head");
    RANK_COLUMNS.forEach(function (col) {
      var cell = h("div", col[2]);
      if (col[0] === null) {
        cell.textContent = col[1];
      } else {
        var btn = h("button", "sort-btn", col[1]);
        btn.type = "button";
        btn.setAttribute("data-sort", col[0]);
        if (col[0] === "tokens" && col[1] === "Token") btn.setAttribute("aria-sort", "descending");
        cell.appendChild(btn);
      }
      head.appendChild(cell);
    });
    var body = h("div", "rank-body");
    var zero = [];
    r.members.forEach(function (row) {
      var meta = MEMBERS[row.id];
      if (row.tokens <= 0 && row.cost <= 0) zero.push([row, meta]);
      else body.appendChild(rankRow(row, meta, r));
    });
    add(table, head, body);
    if (zero.length) {
      var z = h("details", "rank-zero");
      z.appendChild(h("summary", null, "另有 " + zero.length + " 人无用量"));
      zero.forEach(function (p) { z.appendChild(rankRow(p[0], p[1], r)); });
      table.appendChild(z);
    }
    sec.appendChild(table);
    return sec;
  }

  // ------------------------------------------------------------ analysis
  function barList(rows, compact) {
    var list = h("div", "bar-list" + (compact ? " compact" : ""));
    rows.forEach(function (row, i) {
      var color = row.other ? "var(--text-muted)" : (i < DATA.palette.length ? DATA.palette[i] : "var(--heat-2)");
      var name = row.model !== undefined ? row.model : row.label;
      var el = h("div", "bar-row" + (row.other ? " other-row" : ""));
      var nm = h("div", "bar-name", name);
      nm.title = name;
      if (row.provider) nm.appendChild(h("small", null, row.provider));
      add(el, nm, h("div", "cell-num", fmtTokens(row.tokens)));
      if (!compact) el.appendChild(h("div", "cell-num b-cost", fmtCost(row.cost)));
      el.appendChild(shareCell(row.share, color));
      if (!compact) el.appendChild(h("div", "cell-small b-users", row.users === null || row.users === undefined ? "" : row.users + " 人"));
      list.appendChild(el);
    });
    return list;
  }

  function renderAnalysis(r) {
    var sec = h("section", "card analysis");
    add(sec, add(h("div", "section-head"), h("h2", "section-title", "分析")));
    if (r.insights.length) {
      var grid = h("div", "insight-grid");
      r.insights.forEach(function (ins) {
        var value = ins.key === "peak" ? md(ins.value) : ins.value;
        var detail = ins.key === "peak" ? fmtTokens(ins.tokens) : (ins.detail || "");
        var v = h("div", "insight-value", value);
        v.title = value;
        add(grid, add(h("div", "insight"), h("div", "insight-label", ins.label), v, h("div", "insight-detail", detail)));
      });
      sec.appendChild(grid);
    }
    sec.appendChild(h("h3", "sub-title", "模型排行"));
    sec.appendChild(r.models.length ? barList(r.models, false) : h("div", "empty-state", "该时段暂无模型用量明细"));
    var split = h("div", "split-grid");
    add(split,
      add(h("div"), h("h3", "sub-title", "按服务商"), r.providers.length ? barList(r.providers, true) : h("div", "muted", "—")),
      add(h("div"), h("h3", "sub-title", "按代理"), r.agents.length ? barList(r.agents, true) : h("div", "muted", "—")));
    sec.appendChild(split);
    return sec;
  }

  // ------------------------------------------------------------ wiring
  function currentMode() {
    var checked = document.querySelector('input[name="trend-mode"]:checked');
    return checked ? checked.value : "person";
  }

  // Long charts scroll inside their box; start at the most recent end.
  function scrollChartsToEnd() {
    document.querySelectorAll("#view-main .chart-scroll").forEach(function (box) {
      box.scrollLeft = box.scrollWidth;
    });
  }

  function render(key) {
    var r = DATA.ranges[key] || null;
    var mode = currentMode();
    var ov = document.getElementById("view-overview");
    var main = document.getElementById("view-main");
    ov.replaceChildren(renderOverview(r, key));
    if (r) main.replaceChildren(renderTrend(r, mode), renderRanking(r), renderAnalysis(r));
    else main.replaceChildren();
    scrollChartsToEnd();
    state.range = key;
    state.sortKey = "tokens";
    state.sortDir = "descending";
    document.querySelectorAll(".range-tab").forEach(function (a) {
      if (a.getAttribute("data-range") === key) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
  }

  function sortRows(key) {
    var body = document.querySelector("#view-main .rank-body");
    if (!body) return;
    if (state.sortKey === key) state.sortDir = state.sortDir === "descending" ? "ascending" : "descending";
    else { state.sortKey = key; state.sortDir = (key === "name" || key === "model") ? "ascending" : "descending"; }
    var dir = state.sortDir === "ascending" ? 1 : -1;
    var attr = "data-" + key;
    var rows = Array.prototype.slice.call(body.children);
    rows.sort(function (a, b) {
      var va = a.getAttribute(attr), vb = b.getAttribute(attr);
      var c;
      if (key === "name" || key === "model") {
        if (!va && vb) return 1;
        if (va && !vb) return -1;
        c = va.localeCompare(vb, "zh-CN");
      } else {
        c = Number(va) - Number(vb);
      }
      if (c === 0) c = Number(b.getAttribute("data-tokens")) - Number(a.getAttribute("data-tokens"));
      else c = c * dir;
      return c;
    });
    rows.forEach(function (row) { body.appendChild(row); });
    document.querySelectorAll("#view-main .sort-btn").forEach(function (btn) {
      var isLabel = btn.getAttribute("data-sort") === key && (key !== "tokens" || btn.textContent === "Token");
      if (isLabel) btn.setAttribute("aria-sort", state.sortDir);
      else btn.removeAttribute("aria-sort");
    });
  }

  function showReadout(hit) {
    var trend = hit.closest(".trend");
    if (!trend) return;
    var r = DATA.ranges[state.range];
    if (!r) return;
    var panel = hit.closest(".trend-panel");
    var mode = panel ? panel.className.replace(/.*trend-(\w+).*/, "$1") : "person";
    var i = Number(hit.getAttribute("data-i"));
    trend.querySelectorAll(".hit.on").forEach(function (el) { el.classList.remove("on"); });
    hit.classList.add("on");
    var out = trend.querySelector(".chart-readout");
    if (out) out.textContent = readoutLines(r.chart, r.chart[mode] || [], i).join(" · ");
  }

  document.addEventListener("click", function (ev) {
    var tab = ev.target.closest(".range-tab");
    if (tab && !ev.metaKey && !ev.ctrlKey && !ev.shiftKey && ev.button === 0) {
      var key = tab.getAttribute("data-range");
      if (LABELS[key] !== undefined) {
        ev.preventDefault();
        if (key !== state.range) {
          render(key);
          history.pushState({ range: key }, "", "?range=" + encodeURIComponent(key));
        }
      }
      return;
    }
    var btn = ev.target.closest(".sort-btn");
    if (btn) {
      sortRows(btn.getAttribute("data-sort"));
      return;
    }
    var hit = ev.target.closest && ev.target.closest(".hit");
    if (hit) showReadout(hit);
  });
  document.addEventListener("mouseover", function (ev) {
    var hit = ev.target.closest && ev.target.closest(".hit");
    if (hit) showReadout(hit);
  });
  window.addEventListener("popstate", function () {
    var params = new URLSearchParams(window.location.search);
    var key = params.get("range");
    if (LABELS[key] === undefined) key = DATA.range;
    if (key !== state.range) render(key);
  });
  history.replaceState({ range: state.range }, "", window.location.href);
  scrollChartsToEnd();
  document.addEventListener("change", function (ev) {
    if (ev.target && ev.target.name === "trend-mode") scrollChartsToEnd();
  });
})();
