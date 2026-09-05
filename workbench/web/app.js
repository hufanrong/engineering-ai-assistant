/* 繁工AI 本地解析工作台 - 前端逻辑 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  // ---------- Tab 切换 ----------
  document.querySelectorAll(".tab").forEach(function (t) {
    t.addEventListener("click", function () {
      document.querySelectorAll(".tab").forEach(function (x) { x.classList.remove("on"); });
      document.querySelectorAll(".panel").forEach(function (x) { x.classList.remove("on"); });
      t.classList.add("on");
      $("p-" + t.dataset.p).classList.add("on");
      if (t.dataset.p === "results") loadResults();
      if (t.dataset.p === "queue") loadQueue();
    });
  });

  // ---------- 状态栏 ----------
  function refreshStatus() {
    fetch("/api/status").then(function (r) { return r.json(); }).then(function (s) {
      $("nodeName").textContent = "解析节点：" + (s.node_name || "—");
      $("stVec").textContent = s.vector_count + " 块";
      $("stIdx").textContent = s.indexed_files + " 个";
      $("stQueue").textContent = s.queue_pending + " 个";
      $("stCloud").textContent = s.cloud_endpoint || "未配置";
      var b = $("btnScan"), c = $("btnCancel");
      if (s.scan_running) { b.disabled = true; $("btnForce").disabled = true; c.style.display = "inline-block"; }
      else { b.disabled = false; $("btnForce").disabled = false; c.style.display = "none"; }
    }).catch(function () {});
  }

  // ---------- 扫描 ----------
  var pollTimer = null;
  function startScan(force) {
    var folders = $("folder").value.split("\n").map(function (s) { return s.trim(); }).filter(Boolean);
    if (!folders.length) { $("scanMsg").textContent = "请先输入至少一个文件夹路径"; return; }
    fetch("/api/scan", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder: folders, force: force })
    }).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "启动失败"); });
      return r.json();
    }).then(function () {
      $("scanMsg").textContent = "扫描中…（" + folders.length + " 个文件夹）";
      $("progBar").style.width = "0%";
      pollTimer = setInterval(pollScan, 800);
      refreshStatus();
    }).catch(function (e) {
      $("scanMsg").textContent = "启动失败：" + e.message;
    });
  }

  function startRetry() {
    fetch("/api/scan/retry-failed", { method: "POST" }).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "启动失败"); });
      return r.json();
    }).then(function () {
      $("scanMsg").textContent = "重试失败文件中…";
      $("progBar").style.width = "0%";
      pollTimer = setInterval(pollScan, 800);
      refreshStatus();
    }).catch(function (e) {
      $("scanMsg").textContent = "启动失败：" + e.message;
    });
  }

  function pollScan() {
    fetch("/api/scan/status").then(function (r) { return r.json(); }).then(function (s) {
      if (s.total > 0) $("progBar").style.width = Math.round(s.done / s.total * 100) + "%";
      $("scanMsg").textContent = (s.msg || "") + "  (" + (s.done || 0) + "/" + (s.total || 0) + ")";
      if (!s.running) {
        clearInterval(pollTimer);
        refreshStatus();
        if (s.stats) {
          var st = s.stats;
          $("scanStats").innerHTML =
            "本次：发现 " + st.found + " 个文件 → 解析 " + st.parsed + "，向量化 " + st.vectorized +
            "，重复跳过 " + st.duplicate + "，跳过 " + st.skipped + "，失败 " + st.failed;
        }
      }
    }).catch(function () {});
  }

  $("btnScan").addEventListener("click", function () { startScan(false); });
  $("btnForce").addEventListener("click", function () { startScan(true); });
  $("btnRetry").addEventListener("click", function () { startRetry(); });
  $("btnCancel").addEventListener("click", function () {
    fetch("/api/scan/cancel", { method: "POST" }).then(refreshStatus);
  });
  $("folder").addEventListener("keydown", function (e) { if (e.key === "Enter") startScan(false); });

  // ---------- 结果库 ----------
  function loadResults() {
    var f = $("filter").value;
    fetch("/api/results?status_filter=" + encodeURIComponent(f) + "&limit=300")
      .then(function (r) { return r.json(); })
      .then(function (items) {
        var box = $("resultList");
        if (!items.length) { box.innerHTML = '<div class="empty">暂无记录，先去"扫描解析"</div>'; return; }
        var html = '<table><tr><th>文件名</th><th>状态</th><th>解析器</th><th>实体数</th><th>时间</th></tr>';
        items.forEach(function (it) {
          html += '<tr class="item" data-sha="' + it.sha256 + '">' +
            '<td>' + esc(it.file_name) + '</td>' +
            '<td><span class="st ' + it.status + '">' + it.status + '</span></td>' +
            '<td>' + esc(it.parser || "") + '</td>' +
            '<td>' + (it.entities || 0) + '</td>' +
            '<td style="white-space:nowrap">' + esc((it.ts || "").slice(0, 16).replace("T", " ")) + '</td></tr>';
        });
        html += "</table>";
        box.innerHTML = html;
        box.querySelectorAll(".item").forEach(function (tr) {
          tr.addEventListener("click", function () { showDetail(tr.dataset.sha); });
        });
      });
  }
  $("filter").addEventListener("change", loadResults);
  $("btnRefresh").addEventListener("click", loadResults);

  function showDetail(sha) {
    fetch("/api/results/" + sha).then(function (r) { return r.json(); }).then(function (d) {
      var box = $("resultDetail");
      box.style.display = "block";
      var html = "<b>" + esc(d.file_name) + "</b>  [" + d.status + " / " + d.parser + "]" +
        (d.error ? ' <span style="color:#C0392B">' + esc(d.error) + "</span>" : "") +
        '<div style="margin-top:6px">实体位号：' + (d.entities || []).map(function (e) { return esc(e.tag); }).join("、") || "（无）" + "</div>";
      if (d.structure && d.structure.sheets) {
        html += "<div style='margin-top:8px'>";
        d.structure.sheets.forEach(function (sh) {
          html += "<b>工作表：" + esc(sh.sheet) + "</b>（" + sh.row_count + " 行）";
          if (sh.header && sh.header.length) html += "<pre>" + esc(sh.header.join(" | ")) + "</pre>";
          html += "<pre>" + esc(JSON.stringify(sh.rows.slice(0, 10), null, 1)) + "</pre>";
        });
        html += "</div>";
      } else {
        html += "<pre>" + esc(JSON.stringify(d.structure || {}, null, 1)) + "</pre>";
      }
      box.innerHTML = html;
    }).catch(function () { $("resultDetail").innerHTML = "加载失败（该文件无缓存，请强制重扫）"; });
  }

  // ---------- AI 检索 ----------
  $("btnSearch").addEventListener("click", doSearch);
  $("query").addEventListener("keydown", function (e) { if (e.key === "Enter") doSearch(); });
  function doSearch() {
    var q = $("query").value.trim();
    if (!q) return;
    var out = $("searchOut");
    out.innerHTML = '<div class="msg">检索中…（首次检索会加载模型，约 10-30 秒）</div>';
    fetch("/api/search", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q, top_k: 6 })
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (!d.results || !d.results.length) { out.innerHTML = '<div class="empty">无结果</div>'; return; }
      var html = "";
      d.results.forEach(function (it) {
        html += '<div class="search-item"><div class="meta">' +
          esc(it.meta.file_name) + " · 相似度 " + (1 - it.distance).toFixed(3) + " · " + esc(it.meta.parser) + "</div>" +
          esc(it.text.slice(0, 300)) + (it.text.length > 300 ? "…" : "") + "</div>";
      });
      out.innerHTML = html;
    }).catch(function (e) { out.innerHTML = '<div class="msg">检索失败：' + esc(e.message) + "</div>"; });
  }

  // ---------- 上传队列 ----------
  function loadQueue() {
    fetch("/api/queue").then(function (r) { return r.json(); }).then(function (d) {
      var box = $("queueList");
      if (!d.items.length) { box.innerHTML = '<div class="empty">队列为空</div>'; return; }
      var html = "<table><tr><th>文件名</th><th>状态</th><th>打包时间</th></tr>";
      d.items.forEach(function (it) {
        html += "<tr><td>" + esc(it.file_name) + '</td><td><span class="st ' + it.status + '">' + it.status +
          "</span></td><td>" + esc((it.created_at || "").slice(0, 16).replace("T", " ")) + "</td></tr>";
      });
      html += "</table>";
      box.innerHTML = html;
    });
  }
  $("btnQueueRefresh").addEventListener("click", loadQueue);
  $("btnUpload").addEventListener("click", function () {
    var m = $("uploadMsg");
    m.textContent = "上传中…";
    fetch("/api/upload", { method: "POST" }).then(function (r) { return r.json(); }).then(function (d) {
      m.textContent = "结果：" + (d.message || "") + "  成功 " + (d.ok || 0) + "，失败 " + (d.failed || 0) + "，跳过 " + (d.skipped || 0);
      loadQueue(); refreshStatus();
    }).catch(function (e) { m.textContent = "上传失败：" + e.message; });
  });

  // ---------- 工具 ----------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  refreshStatus();
  setInterval(refreshStatus, 5000);
})();
