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
      if (t.dataset.p === "relations") loadRelations();
      if (t.dataset.p === "docgen") initDocGen();
      if (t.dataset.p === "platform") loadPlatform();
      if (t.dataset.p === "docplan") loadDocPlan();
      if (t.dataset.p === "cloud") loadCloud();
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
  // ---------- ① 失败/待处理清单（v0.1.21） ----------
  function loadFailList() {
    fetch("/api/scan/failed-list").then(function (r) { return r.json(); }).then(function (d) {
      var items = d.items || [];
      var box = $("failList");
      if (!items.length) { box.innerHTML = "暂无失败文件"; return; }
      var html = '<table style="width:100%;border-collapse:collapse;font-size:13px">' +
        '<tr style="background:#f0f3f8"><th style="padding:6px;text-align:left">文件</th><th>错误</th><th>重试</th><th>状态</th><th>操作</th></tr>';
      items.forEach(function (it) {
        var st = it.status === "pending_manual"
          ? '<span class="st failed">待处理</span>'
          : '<span class="st partial">失败</span>';
        var ops = '<button class="btn ghost" data-r="' + it.sha256 + '" style="padding:2px 8px;font-size:12px">重试</button> ' +
          '<button class="btn ghost" data-d="' + it.sha256 + '" style="padding:2px 8px;font-size:12px">删除</button>';
        html += '<tr><td style="padding:6px;word-break:break-all">' + esc(it.file_name) +
          '<div style="color:#999;font-size:11px">' + esc((it.error || "").slice(0, 80)) + "</div></td>" +
          '<td style="text-align:center">' + it.retry_count + "/3</td>" +
          '<td style="text-align:center">' + st + "</td>" +
          '<td style="text-align:center">' + ops + "</td></tr>";
      });
      html += "</table>";
      box.innerHTML = html;
      box.querySelectorAll("[data-r]").forEach(function (b) {
        b.addEventListener("click", function () {
          fetch("/api/scan/retry-failed/" + b.dataset.r, { method: "POST" }).then(function (r) { return r.json(); })
            .then(function (d) {
              $("scanMsg").textContent = "重试完成：恢复 " + d.stats.recovered + "，仍失败 " + d.stats.still_failed + "，转待处理 " + d.stats.pending_manual;
              loadFailList(); refreshStatus();
            });
        });
      });
      box.querySelectorAll("[data-d]").forEach(function (b) {
        b.addEventListener("click", function () {
          fetch("/api/scan/failed/delete", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ shas: [b.dataset.d] }) }).then(loadFailList);
        });
      });
    }).catch(function () {});
  }
  $("btnFailRefresh").addEventListener("click", loadFailList);
  $("btnFailClear").addEventListener("click", function () {
    fetch("/api/scan/failed/clear", { method: "POST" }).then(function () { loadFailList(); refreshStatus(); });
  });
  loadFailList();

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
      body: JSON.stringify({ query: q, top_k: 6, platform: !!$("chkPlatform").checked })
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (!d.results || !d.results.length) { out.innerHTML = '<div class="empty">无结果</div>'; return; }
      var html = "";
      d.results.forEach(function (it) {
        var src = it.source === "platform"
          ? '<span class="st parsed">平台规范</span> ' + esc(it.std_no || "") + " " + esc(it.std_name || "")
          : '<span class="st partial">项目库</span>';
        html += '<div class="search-item"><div class="meta">' + src + " · " +
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

  // ---------- 手动上传文件 ----------
  $("btnUploadFiles").addEventListener("click", function () {
    var inp = $("upfiles");
    if (!inp.files || !inp.files.length) { $("uploadFilesMsg").textContent = "请先选择文件"; return; }
    var fd = new FormData();
    fd.append("uploader", $("uploader").value.trim());
    for (var i = 0; i < inp.files.length; i++) fd.append("files", inp.files[i]);
    var m = $("uploadFilesMsg");
    m.textContent = "上传解析中…（" + inp.files.length + " 个文件）";
    fetch("/api/upload-files", { method: "POST", body: fd })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var html = "";
        d.results.forEach(function (it) {
          html += '<div style="font-size:13px">[' + it.status + "/" + (it.parser || "-") + "] " + esc(it.file) +
            (it.error ? ' <span style="color:#C0392B">' + esc(it.error) + "</span>" : "") +
            (it.entities ? " · 实体 " + it.entities + " 个" : "") + "</div>";
        });
        m.innerHTML = html;
        refreshStatus();
      })
      .catch(function (e) { m.textContent = "上传失败：" + e.message; });
  });

  // ---------- 关联图谱 ----------
  function loadRelations() {
    fetch("/api/relations").then(function (r) { return r.json(); }).then(function (g) {
      var st = g.stats || {};
      var chips = [
        ["已解析文件", st.docs || 0], ["车间", st.workshops || 0],
        ["关联设备", st.devices || 0], ["设备间距", st.distances || 0],
        ["关联关系", st.relations || 0], ["待人工确认", st.human_confirm || 0]
      ];
      $("relStats").innerHTML = chips.map(function (c) {
        return '<span class="chip">' + c[0] + " <b>" + c[1] + "</b></span>";
      }).join("");

      // 图纸网络 + 设备-车间映射（v0.1.13）
      var dwgs = g.drawings || [];
      var lay = g.layout || [];
      var dwgHtml = "";
      if (dwgs.length) {
        dwgHtml = '<h3>图纸网络（多图联动）</h3><table><tr><th>图号</th><th>图名</th><th>车间</th><th>类型</th><th>设备数</th><th>跨图设备</th><th>关联图纸</th></tr>';
        dwgs.forEach(function (d) {
          var cross = (d.cross_drawing_devices || []).join("、");
          var rels = (d.relations || []).map(function (r) {
            return r.to_no + "(" + r.reasons.join("/") + ")";
          }).join("；") || "—";
          dwgHtml += "<tr><td>" + esc(d.no || "—") + "</td><td>" + esc(d.name || d.file) + "</td><td>" +
            esc(d.workshop || "待确认") + "</td><td>" + esc(d.doc_type) + "</td><td>" + d.device_count + "</td><td>" +
            esc(cross || "—") + '</td><td style="font-size:12px">' + esc(rels) + "</td></tr>";
        });
        dwgHtml += "</table>";
      }
      var layHtml = "";
      if (lay.length) {
        layHtml = '<h3>设备→车间映射（以设计院图纸为准）</h3><table><tr><th>位号</th><th>归属车间</th><th>证据</th><th>跨图数</th></tr>';
        lay.forEach(function (r) {
          var ok = r.confirmed ? '<span class="st parsed">' + esc(r.workshop) + "</span>" :
            '<span class="st failed">' + (r.workshop ? esc(r.workshop) + "（平票）" : "待人工确认") + "</span>";
          layHtml += "<tr><td>" + esc(r.tag) + "</td><td>" + ok + "</td><td>" +
            (r.votes || []).map(function (v) { return v.workshop + "×" + v.weight; }).join(" ") + "</td><td>" + r.cross_drawings + "</td></tr>";
        });
        layHtml += "</table>";
      }
      $("relDwgOut").innerHTML = dwgHtml + layHtml;

      var sel = $("relWorkshop");
      var cur = sel.value;
      sel.innerHTML = '<option value="">— 选择车间查看详情 —</option>';
      (g.workshops || []).forEach(function (w) {
        sel.innerHTML += '<option value="' + esc(w.workshop) + '">' + esc(w.workshop) +
          "（图纸 " + w.doc_count + " · 设备 " + w.device_count + "）</option>";
      });
      sel.value = cur;
      if (cur) showWorkshop(cur); else $("relOut").innerHTML = "";

      // 待人工确认列表
      var hc = g.human_confirm || [];
      var html = "";
      if (hc.length) {
        html += '<div style="margin-top:8px"><b style="color:#B45309">待人工确认（' + hc.length + ' 条）</b>';
        html += '<div style="max-height:180px;overflow:auto;border:1px solid var(--line);border-radius:8px;padding:8px;margin-top:4px;font-size:13px">';
        hc.forEach(function (h) {
          html += "<div>[" + esc(h.type) + "] " + esc(h.tag) + " → " + esc((h.workshops || []).join("、")) +
            "（涉及：" + esc((h.files || []).join("、")) + "）</div>";
        });
        html += "</div></div>";
      }
      if (!html && !hc.length && $("relWorkshop").options.length <= 1) {
        html = '<div class="empty">尚未生成图谱：先在"① 扫描解析"完成扫描，再点"重建图谱"</div>';
      }
      $("relOut").insertAdjacentHTML("beforeend", "");
    }).catch(function (e) {
      $("relStats").innerHTML = '<span class="msg">图谱加载失败：' + esc(e.message) + "</span>";
    });
  }

  function showWorkshop(w) {
    fetch("/api/relations/workshop/" + encodeURIComponent(w)).then(function (r) { return r.json(); }).then(function (d) {
      var ws = d.workshop;
      var html = '<div style="margin-top:8px">';
      if (ws.zone) html += '<div class="msg">全场图位置：(' + ws.zone.x + ", " + ws.zone.y + ")（来自 " + esc(ws.zone.from) + "）</div>";
      html += "<b>图纸/资料（" + (ws.docs || []).length + "）</b><table><tr><th>文件</th><th>类型</th><th>解析器</th></tr>";
      (ws.docs || []).forEach(function (doc) {
        html += "<tr><td>" + esc(doc.file) + "</td><td>" + esc(doc.doc_type) + "</td><td>" + esc(doc.parser) + "</td></tr>";
      });
      html += "</table>";
      html += "<b style='display:block;margin-top:10px'>设备（" + (d.devices || []).length + "）</b><table><tr><th>位号</th><th>来源</th><th>坐标</th></tr>";
      (d.devices || []).forEach(function (dev) {
        var pos = (dev.cad_positions || []).map(function (p) { return "(" + p.x + "," + p.y + ")@" + p.file; }).join("、") || "—";
        html += "<tr><td><b>" + esc(dev.tag) + "</b></td><td>" + (dev.files || []).length + " 份</td><td>" + esc(pos) + "</td></tr>";
      });
      html += "</table>";
      var dists = d.distances || [];
      if (dists.length) {
        html += "<b style='display:block;margin-top:10px'>设备间距（" + dists.length + " 条，同图坐标差×比例/1000=米）</b><table><tr><th>设备A</th><th>设备B</th><th>距离</th><th>来源图纸</th></tr>";
        dists.forEach(function (r) {
          html += "<tr><td><b>" + esc(r.from) + "</b></td><td><b>" + esc(r.to) + "</b></td><td>" + r.meters + " m</td><td>" + esc(r.file) + "（1:" + r.scale + "）</td></tr>";
        });
        html += "</table>";
      }
      html += "</div>";
      $("relOut").innerHTML = html;
    }).catch(function (e) { $("relOut").innerHTML = '<span class="msg">加载失败：' + esc(e.message) + "</span>"; });
  }

  $("btnRebuildRel").addEventListener("click", function () {
    var b = $("btnRebuildRel");
    b.disabled = true; b.textContent = "重建中…";
    fetch("/api/relations/rebuild", { method: "POST" }).then(function (r) { return r.json(); }).then(function (d) {
      b.textContent = "重建图谱";
      setTimeout(function () { b.disabled = false; loadRelations(); }, 2500);
    }).catch(function (e) { b.textContent = "重建图谱"; b.disabled = false; alert("重建失败：" + e.message); });
  });
  $("btnRelRefresh").addEventListener("click", loadRelations);
  $("relWorkshop").addEventListener("change", function () {
    var v = this.value;
    if (v) showWorkshop(v); else $("relOut").innerHTML = "";
  });

  // ---------- 方案生成 ----------
  var dgTypes = [];
  function initDocGen() {
    if (!dgTypes.length) loadDocGenTypes();
  }
  function loadDocGenTypes() {
    fetch("/api/docgen/types").then(function (r) { return r.json(); }).then(function (d) {
      dgTypes = d.types || [];
      var sel = $("dgType");
      sel.innerHTML = dgTypes.map(function (t) { return '<option value="' + esc(t.key) + '">' + esc(t.label) + "</option>"; }).join("");
      renderDocForm();
      // 车间下拉
      fetch("/api/relations").then(function (r) { return r.json(); }).then(function (g) {
        var wsel = $("dgWorkshop");
        wsel.innerHTML = '<option value="">— 全项目设备 —</option>' +
          (g.workshops || []).map(function (w) { return '<option value="' + esc(w.workshop) + '">' + esc(w.workshop) + "</option>"; }).join("");
      }).catch(function () {});
    }).catch(function (e) { $("dgForm").innerHTML = '<span class="msg">加载失败：' + esc(e.message) + "</span>"; });
  }
  function renderDocForm() {
    var t = dgTypes.find(function (x) { return x.key === $("dgType").value; });
    if (!t) { $("dgForm").innerHTML = ""; return; }
    var html = "<b>必填字段（缺失将标红提示）</b><div style='margin-top:6px'>";
    (t.required || []).forEach(function (k) {
      html += '<div style="margin-bottom:6px"><label>' + esc(k) + '</label><input id="dg_' + esc(k) + '" class="dg-in" style="width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;box-sizing:border-box;font-size:14px"></div>';
    });
    html += "</div><b style='display:block;margin-top:8px'>可选字段（可留空）</b><div style='margin-top:6px'>";
    (t.optional || []).forEach(function (k) {
      html += '<div style="margin-bottom:6px"><label>' + esc(k) + '</label><input id="dg_' + esc(k) + '" class="dg-in" style="width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;box-sizing:border-box;font-size:14px"></div>';
    });
    html += "</div>";
    $("dgForm").innerHTML = html;
    $("dgMsg").textContent = "";
  }
  $("dgType").addEventListener("change", renderDocForm);
  $("btnDgPrefill").addEventListener("click", function () {
    var ws = $("dgWorkshop").value;
    fetch("/api/docgen/prefill?workshop=" + encodeURIComponent(ws), { method: "POST" })
      .then(function (r) { return r.json(); }).then(function (d) {
        var refTxt = (d.references && d.references.length) ? "；平台规范可引用：" + d.references.slice(0, 3).map(function (r) { return r.std_no + " " + r.std_name; }).join("、") : "";
        if (d.devices && d.devices.length) {
          $("dgMsg").textContent = "已预填 " + d.devices.length + " 台设备（" + (ws || "全项目") + "）：" + d.devices.slice(0, 12).map(function (v) { return v.tag; }).join("、") + (d.devices.length > 12 ? "…" : "") + refTxt;
          if ($("dg_车间")) $("dg_车间").value = ws;
        } else {
          $("dgMsg").textContent = "该车间暂无设备，请先扫描解析并重建图谱" + refTxt;
        }
      }).catch(function (e) { $("dgMsg").textContent = "预填失败：" + e.message; });
  });
  $("btnDgGen").addEventListener("click", function () {
    var t = dgTypes.find(function (x) { return x.key === $("dgType").value; });
    if (!t) return;
    var data = {};
    document.querySelectorAll(".dg-in").forEach(function (inp) {
      if (inp.value.trim()) data[inp.id.replace("dg_", "")] = inp.value.trim();
    });
    $("dgMsg").textContent = "生成中…";
    fetch("/api/docgen/generate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_type: t.key, data: data })
    }).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "生成失败"); });
      return r.blob();
    }).then(function (blob) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url; a.download = "繁工AI_" + t.label + "_" + new Date().toISOString().slice(0, 16).replace(/[T:]/g, "_") + ".docx";
      document.body.appendChild(a); a.click(); a.remove();
      $("dgMsg").textContent = "已生成下载。缺失必填字段在 Word 中以红字『待补充』标注。";
    }).catch(function (e) { $("dgMsg").textContent = "生成失败：" + e.message; });
  });

  // ---------- 解析库导出/合并 ----------
  $("btnLibExport").addEventListener("click", function () {
    fetch("/api/library/export").then(function (r) {
      if (!r.ok) throw new Error("导出失败");
      return r.blob();
    }).then(function (blob) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url; a.download = "繁工AI_解析库_" + new Date().toISOString().slice(0, 16).replace(/[T:]/g, "_") + ".fglib";
      document.body.appendChild(a); a.click(); a.remove();
      $("libMsg").textContent = "库包已导出，可传到另一台电脑导入合并。";
    }).catch(function (e) { $("libMsg").textContent = "导出失败：" + e.message; });
  });
  $("btnLibImport").addEventListener("click", function () { $("libImportFile").click(); });
  $("libImportFile").addEventListener("change", function () {
    var f = this.files[0];
    if (!f) return;
    var fd = new FormData();
    fd.append("file", f);
    $("libMsg").textContent = "导入合并中…";
    fetch("/api/library/import", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.detail || "导入失败"); return d; }); })
      .then(function (d) {
        var st = d.stats || {};
        $("libMsg").textContent = "合并完成：新增 " + st.index_added + " 项，去重跳过 " + st.index_dup + " 项，图谱已重建。";
        loadStatus(); loadResults();
      }).catch(function (e) { $("libMsg").textContent = "导入失败：" + e.message; });
    this.value = "";
  });

  // ---------- 平台级规范库（⑦） ----------
  function loadPlatform() {
    fetch("/api/platform/list").then(function (r) { return r.json(); }).then(function (d) {
      var box = $("platList");
      if (!d.items || !d.items.length) { box.innerHTML = '<div class="empty">平台库为空，请上传规范/标准文件</div>'; return; }
      var html = "<table><tr><th>标准号</th><th>标准名/文件名</th><th>状态</th><th>下次检查</th><th>操作</th></tr>";
      d.items.forEach(function (it) {
        var st = { "现行": "parsed", "待核验": "partial", "废止": "failed" }[it.status] || "skipped";
        html += "<tr><td>" + esc(it.std_no || "—") + "</td><td>" + esc(it.std_name || it.file_name) + "</td>" +
          '<td><span class="st ' + st + '">' + it.status + "</span>" + (it.obsolete_note ? '<br><span style="color:var(--err);font-size:12px">' + esc(it.obsolete_note) + "</span>" : "") + "</td>" +
          "<td>" + esc(it.next_check || "—") + "</td>" +
          '<td><select class="platStatus" data-sha="' + it.sha256 + '" style="max-width:80px;padding:3px 6px">' +
            '<option value="现行"' + (it.status === "现行" ? " selected" : "") + ">现行</option>" +
            '<option value="待核验"' + (it.status === "待核验" ? " selected" : "") + ">待核验</option>" +
            '<option value="废止"' + (it.status === "废止" ? " selected" : "") + ">废止</option>" +
          "</select> " +
          '<button class="btn ghost platDel" data-sha="' + it.sha256 + '" style="padding:3px 10px;font-size:12px">删除</button></td></tr>';
      });
      html += "</table>";
      box.innerHTML = html;
      box.querySelectorAll(".platStatus").forEach(function (sel) {
        sel.addEventListener("change", function () {
          fetch("/api/platform/status", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sha256: sel.dataset.sha, status: sel.value }) })
            .then(function (r) { return r.json(); }).then(function () { $("platMsg").textContent = "状态已更新"; })
            .catch(function (e) { $("platMsg").textContent = "更新失败：" + e.message; });
        });
      });
      box.querySelectorAll(".platDel").forEach(function (btn) {
        btn.addEventListener("click", function () {
          if (!confirm("删除该规范条目？")) return;
          fetch("/api/platform/delete", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sha256: btn.dataset.sha }) })
            .then(function (r) { return r.json(); }).then(function () { loadPlatform(); })
            .catch(function (e) { $("platMsg").textContent = "删除失败：" + e.message; });
        });
      });
    }).catch(function (e) { $("platList").innerHTML = '<div class="msg">加载失败：' + esc(e.message) + "</div>"; });
  }
  $("btnPlatUpload").addEventListener("click", function () {
    var inp = $("platFiles");
    if (!inp.files.length) { $("platMsg").textContent = "请先选择规范文件"; return; }
    var fd = new FormData();
    for (var i = 0; i < inp.files.length; i++) fd.append("files", inp.files[i]);
    $("platMsg").textContent = "上传解析中…";
    fetch("/api/platform/upload", { method: "POST", body: fd }).then(function (r) { return r.json(); }).then(function (d) {
      var ok = d.results.filter(function (x) { return x.status === "added"; }).length;
      var dup = d.results.filter(function (x) { return x.status === "duplicate"; }).length;
      $("platMsg").textContent = "上传完成：新增 " + ok + " 项，重复跳过 " + dup + " 项";
      inp.value = ""; loadPlatform();
    }).catch(function (e) { $("platMsg").textContent = "上传失败：" + e.message; });
  });
  $("btnPlatCheck").addEventListener("click", function () {
    $("platMsg").textContent = "检查中…";
    fetch("/api/platform/check-expiry", { method: "POST" }).then(function (r) { return r.json(); }).then(function (d) {
      var m = "检查完成：到期 " + d.checked + " 项，待核验 " + d.due.length + " 项" + (d.replaced.length ? "，联网替换 " + d.replaced.length + " 项" : "");
      $("platMsg").textContent = m;
      loadPlatform();
    }).catch(function (e) { $("platMsg").textContent = "检查失败：" + e.message; });
  });
  $("btnPlatExport").addEventListener("click", function () {
    fetch("/api/platform/export").then(function (r) { if (!r.ok) throw new Error("导出失败"); return r.blob(); })
      .then(function (blob) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a"); a.href = url; a.download = "繁工AI_平台规范库.fpglib";
        document.body.appendChild(a); a.click(); a.remove();
        $("platMsg").textContent = "平台库已导出（可拷到新电脑导入复用）";
      }).catch(function (e) { $("platMsg").textContent = "导出失败：" + e.message; });
  });
  $("btnPlatImport").addEventListener("click", function () { $("platImportFile").click(); });
  $("platImportFile").addEventListener("change", function () {
    var f = this.files[0]; if (!f) return;
    var fd = new FormData(); fd.append("file", f);
    $("platMsg").textContent = "导入中…";
    fetch("/api/platform/import", { method: "POST", body: fd }).then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.detail || "导入失败"); return d; }); })
      .then(function (d) { $("platMsg").textContent = "导入完成：新增 " + d.stats.added + "，重复 " + d.stats.dup + " 项"; loadPlatform(); })
      .catch(function (e) { $("platMsg").textContent = "导入失败：" + e.message; });
    this.value = "";
  });
  loadPlatform();

  // ---------- ⑧ 工程资料生成计划（v0.1.12） ----------
  function loadDocPlan() {
    fetch("/api/docplan/status").then(function (r) { return r.json(); }).then(function (d) {
      var box = $("docplanList");
      var html = '<div class="row" style="margin:6px 0;gap:8px;flex-wrap:wrap">' +
        '<span class="st parsed">可生成 ' + d.ready + "</span>" +
        '<span class="st partial">缺部分 ' + d.partial + "</span>" +
        '<span class="st failed">无前置 ' + d.missing + "</span>" +
        '<span style="font-size:12px;color:var(--text2)">库内资料类别：' + Object.keys(d.classes).join(" / ") + "</span></div>";
      d.plans.forEach(function (p) {
        var st = { ready: "parsed", partial: "partial", missing: "failed" }[p.state];
        var lacks = p.missing.length ? '<div style="color:var(--err);font-size:12px">缺：' + p.missing.join("、") + "</div>" : "";
        var act = (p.state === "ready" || p.state === "partial")
          ? '<button class="btn ghost docplanGen" data-t="' + p.doc_type + '" style="padding:3px 10px;font-size:12px">去生成</button>'
          : "";
        html += '<div class="search-item"><div class="meta"><span class="st ' + st + '">' +
          (p.state === "ready" ? "可生成" : p.state === "partial" ? "缺部分" : "无前置") + "</span> " +
          esc(p.key) + " · 已有前置 " + p.have_files + " 份文件</div>" +
          esc(p.desc) + lacks + act + "</div>";
      });
      box.innerHTML = html;
      box.querySelectorAll(".docplanGen").forEach(function (b) {
        b.addEventListener("click", function () {
          genOpen(b.dataset.t, "");
        });
      });
    }).catch(function (e) { $("docplanList").innerHTML = '<div class="msg">加载失败：' + esc(e.message) + "</div>"; });
    // 人工任务列表
    fetch("/api/docplan/tasks").then(function (r) { return r.json(); }).then(function (d) {
      var box = $("docplanMsg");
      var tasks = d.items || [];
      if (!tasks.length) { box.innerHTML = '<div class="msg">暂无人工登记的资料任务</div>'; return; }
      var html = '<div style="margin-top:10px"><b>人工登记任务：</b><table><tr><th>名称</th><th>类型</th><th>状态</th><th>登记时间</th><th>操作</th></tr>';
      tasks.forEach(function (t) {
        html += "<tr><td>" + esc(t.name) + "</td><td>" + esc(t.doc_type) + "</td><td>" + esc(t.status) + "</td><td>" +
          esc((t.created_at || "").slice(0, 16).replace("T", " ")) + "</td>" +
          '<td><button class="btn ghost docplanDone" data-id="' + t.id + '" style="padding:2px 8px;font-size:12px">完成</button> ' +
          '<button class="btn ghost docplanDel" data-id="' + t.id + '" style="padding:2px 8px;font-size:12px">删除</button></td></tr>';
      });
      html += "</table></div>";
      box.innerHTML = html;
      box.querySelectorAll(".docplanDone").forEach(function (b) {
        b.addEventListener("click", function () {
          fetch("/api/docplan/task/" + b.dataset.id, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "已完成" }) })
            .then(function () { loadDocPlan(); });
        });
      });
      box.querySelectorAll(".docplanDel").forEach(function (b) {
        b.addEventListener("click", function () {
          if (!confirm("删除该资料任务？")) return;
          fetch("/api/docplan/task/" + b.dataset.id, { method: "DELETE" }).then(function () { loadDocPlan(); });
        });
      });
    }).catch(function () {});
  }
  $("btnDocPlanTask").addEventListener("click", function () {
    fetch("/api/docplan/task", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_type: $("docplanType").value, name: $("docplanName").value, status: "待补充" }) })
      .then(function (r) { return r.json(); }).then(function () { $("docplanName").value = ""; loadDocPlan(); })
      .catch(function (e) { $("docplanMsg").textContent = "登记失败：" + e.message; });
  });

  // ---------- ⑨ 云库（v0.1.14） ----------
  function loadCloud() {
    fetch("/api/cloud/info").then(function (r) { return r.json(); }).then(function (d) {
      if (!d.connected) {
        $("clConn").innerHTML = "未连接";
        $("clFiles").textContent = d.message || "未配置";
        $("clField").textContent = "";
        return;
      }
      $("clConn").innerHTML = "已连接";
      $("clFiles").textContent = "云库文件 " + d.cloud_files;
      $("clField").textContent = "现场上传 " + d.field_uploads;
      loadCloudLists();
    }).catch(function (e) {
      $("clConn").textContent = "连接失败：" + e.message;
    });
  }
  function loadCloudLists() {
    fetch("/api/cloud/field-list").then(function (r) { return r.json(); }).then(function (d) {
      var box = $("clFieldList");
      var items = d.items || [];
      if (!items.length) { box.innerHTML = '<div class="empty">暂无现场上传</div>'; return; }
      var html = "<table><tr><th>时间</th><th>项目</th><th>上传人</th><th>类型</th><th>文件</th><th>说明</th></tr>";
      items.slice(0, 50).forEach(function (it) {
        html += "<tr><td>" + esc((it.ts || "").slice(0, 16).replace("T", " ")) + "</td><td>" + esc(it.project) +
          "</td><td>" + esc(it.uploader) + "</td><td>" + esc(it.kind) + "</td><td>" + esc(it.file_name) +
          '</td><td style="font-size:12px">' + esc(it.note || "") + "</td></tr>";
      });
      html += "</table>";
      box.innerHTML = html;
    }).catch(function () { $("clFieldList").innerHTML = '<div class="empty">拉取清单失败</div>'; });
    fetch("/api/cloud/list-proxy").then(function (r) { return r.json(); }).then(function (d) {
      var box = $("clCloudList");
      var items = d.items || [];
      if (!items.length) { box.innerHTML = '<div class="empty">云库为空</div>'; return; }
      box.innerHTML = "<table><tr><th>时间</th><th>节点</th><th>文件</th><th>类型</th></tr>" + items.slice(0, 50).map(function (it) {
        return "<tr><td>" + esc((it.received_at || "").slice(0, 16).replace("T", " ")) + "</td><td>" + esc(it.node_name) +
          "</td><td>" + esc(it.file_name) + "</td><td>" + esc(it.parser) + "</td></tr>";
      }).join("") + "</table>";
    }).catch(function () { $("clCloudList").innerHTML = '<div class="empty">云库清单不可用</div>'; });
  }
  $("btnPullField").addEventListener("click", function () {
    $("clMsg").textContent = "拉取中…（自动解析入库）";
    fetch("/api/cloud/pull-field", { method: "POST" }).then(function (r) { return r.json(); }).then(function (d) {
      $("clMsg").textContent = "拉取 " + d.pulled + " 个文件，解析入库 " + d.parsed + "，重复跳过 " + d.duplicate +
        (d.errors && d.errors.length ? "，失败：" + d.errors.join("；") : "");
      loadCloud();
    }).catch(function (e) { $("clMsg").textContent = "拉取失败：" + e.message; });
  });
  $("btnClRefresh").addEventListener("click", loadCloud);

  // ---------- 工具 ----------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  refreshStatus();
  setInterval(refreshStatus, 5000);
})();
// ---------- ⑩ AI 助手 ----------
function aiAdd(role, html) {
    var box = document.getElementById("aiChatBox");
    var row = document.createElement("div");
    row.style.cssText = "margin:6px 0;padding:8px 10px;border-radius:8px;white-space:pre-wrap;word-break:break-all;font-size:13px;line-height:1.6;";
    if (role === "me") { row.style.cssText += "background:#e8f0fe;text-align:right;margin-left:60px;"; }
    else { row.style.cssText += "background:#fff;border:1px solid #e3e8ef;margin-right:60px;"; }
    row.innerHTML = html;
    box.appendChild(row);
    box.scrollTop = box.scrollHeight;
}
function aiStatus() {
    fetch("/api/ai/status").then(function(r){ return r.json(); }).then(function(d){
        aiAdd("ai", "助手模式：" + d.mode + "  |  AI 网关：" + (d.gateway || "未配置") + "\n可生成资料类型：" + (d.doc_types || []).join("、"));
    });
}
function aiDownloadDoc(name) {
    fetch("/api/ai/chat", {method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({query: "生成 " + name})}).then(function(r){ return r.json(); }).then(function(d){
        if (d.mode !== "local_doc" || !d.doc) { alert("重新生成失败"); return; }
        var bin = atob(d.doc.content_b64);
        var bytes = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) { bytes[i] = bin.charCodeAt(i); }
        var a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([bytes], {type:"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}));
        a.download = d.doc.file_name;
        a.click();
    });
}
function aiSend() {
    var q = document.getElementById("aiInput").value.trim();
    if (!q) return;
    aiAdd("me", q);
    document.getElementById("aiInput").value = "";
    aiAdd("ai", "思考中…");
    fetch("/api/ai/chat", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({query: q})})
    .then(function(r){ return r.json(); })
    .then(function(d){
        var box = document.getElementById("aiChatBox");
        if (box.lastChild) box.removeChild(box.lastChild);
        var html = (d.answer || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/\n/g,"<br>");
        if (d.mode === "local_doc" && d.doc) {
            html += "<br><button onclick=\"aiDownloadDoc('" + d.doc.file_name + "')\">下载生成的 Word 文档</button>";
        }
        if (d.mode === "error") { html = "<span style='color:#c0392b'>" + html + "</span>"; }
        aiAdd("ai", html);
    })
    .catch(function(e){
        var box = document.getElementById("aiChatBox");
        if (box.lastChild) box.removeChild(box.lastChild);
        aiAdd("ai", "<span style='color:#c0392b'>请求失败：" + e + "</span>");
    });
}
(function(){
    var el = document.getElementById("aiSuggest");
    if (!el) return;
    var SUGGEST = ["生成 1号车间 P-101 吊装方案，设备重3.5t", "P-101 安装要求", "当前资料待办有哪些", "1号车间有哪些设备"];
    el.innerHTML = SUGGEST.map(function(t){
        return "<button onclick=\"document.getElementById('aiInput').value='" + t + "';aiSend();\">" + t + "</button>";
    }).join("");
})();
// ---------- ⑧ 计划页一键生成（v0.1.18） ----------
var genState = { doc_type: "", fields: {}, required: [] };
function genOpen(docType, workshop) {
    genState.doc_type = docType;
    genState.fields = {};
    var box = document.getElementById("genModalFields");
    box.innerHTML = '<div class="msg">加载预填数据…</div>';
    document.getElementById("genModalTitle").textContent = "生成：" + docType;
    document.getElementById("genModal").style.display = "flex";
    fetch("/api/docgen/prefill", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workshop: workshop || "", doc_type: docType }) })
    .then(function (r) { return r.json(); })
    .then(function (pf) {
        var html = "";
        // 必填字段（来自模板）
        fetch("/api/docgen/types").then(function (r) { return r.json(); }).then(function (types) {
            var t = (types || []).filter(function (x) { return x.key === docType; })[0] || {};
            genState.required = t.required || [];
            var reqs = (t.required || []).concat(t.optional || []);
            var defaultVals = { "项目名称": "", "车间": pf.workshop || "", "编制单位": "", "编制人": "", "编制日期": "", "吊装日期": "" };
            reqs.forEach(function (k) {
                var pre = (pf.devices && pf.devices.length) ? "" : "";
                html += '<div style="margin:6px 0"><label style="font-size:12px;color:#555">' + esc(k) +
                    (((t.required || []).indexOf(k) >= 0) ? ' <span style="color:#c0392b">*必填</span>' : "") + "</label><br>" +
                    '<input id="genF_' + k + '" style="width:100%;box-sizing:border-box;padding:6px;border:1px solid #c0c9d6;border-radius:6px;" value="' + esc(defaultVals[k] || "") + '"></div>';
            });
            if (pf.devices && pf.devices.length) {
                html += '<div style="margin:6px 0"><label style="font-size:12px;color:#555">自动带出设备 ' + pf.devices.length + ' 台：' + esc(pf.devices.map(function (d) { return d.tag; }).join("、")) + "</label></div>";
            }
            if (pf.references && pf.references.length) {
                html += '<div style="margin:6px 0;font-size:12px;color:#555">编制依据自动引用：' + esc(pf.references.map(function (r) { return r.std_no; }).join("、")) + "</div>";
            }
            var box2 = document.getElementById("genModalFields");
            box2.innerHTML = html || '<div class="msg">该类型无补充字段，可直接生成</div>';
        });
    })
    .catch(function (e) { document.getElementById("genModalFields").innerHTML = '<div class="msg">预填失败：' + esc(e.message) + "</div>"; });
}
function genClose() { document.getElementById("genModal").style.display = "none"; }
function genDo() {
    var data = {};
    genState.required.forEach(function (k) {
        var el = document.getElementById("genF_" + k);
        if (el) data[k] = el.value.trim();
    });
    // 收集全部已填输入
    var inputs = document.querySelectorAll("#genModalFields input");
    inputs.forEach(function (el) {
        var k = el.id.replace("genF_", "");
        data[k] = el.value.trim();
    });
    fetch("/api/docplan/generate", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_type: genState.doc_type, workshop: genState.fields.workshop || "", fields: data }) })
    .then(function (r) {
        if (!r.ok) { return r.json().then(function (e) { throw new Error(e.detail || "生成失败"); }); }
        return r.blob();
    })
    .then(function (blob) {
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "fanGongAI_" + genState.doc_type + "_" + new Date().toISOString().slice(0, 16).replace(/[T:]/g, "_") + ".docx";
        a.click();
        genClose();
    })
    .catch(function (e) { document.getElementById("genModalHint").textContent = "生成失败：" + e.message; });
}
