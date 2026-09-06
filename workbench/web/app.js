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

      // v0.1.25：关系网络图
      try { renderRelNet(g); } catch (e) { console.error(e); }

      // v0.1.23：铭牌候选设备人工确认
      var hc = g.human_confirm || [];
      var cand = hc.filter(function (c) { return (c.type || "").indexOf("铭牌未在台账") >= 0; });
      var candHtml = "";
      if (cand.length) {
        candHtml = '<h3>铭牌候选设备（现场照片识别，未在图纸/台账中，请确认归属车间）</h3><table><tr><th>位号</th><th>铭牌信息</th><th>来源照片</th><th>车间</th><th>操作</th></tr>';
        cand.forEach(function (c) {
          var pl = c.plate || {};
          var info = [ (pl.params || []).join("；"), (pl.manufacturers || []).join("、") ].filter(Boolean).join(" · ") || "—";
          var opts = '<option value="">选择车间</option>';
          (g.workshops || []).forEach(function (w) { opts += '<option value="' + esc(w.workshop) + '">' + esc(w.workshop) + "</option>"; });
          opts += '<option value="__new">+ 新建车间</option>';
          candHtml += '<tr><td><b>' + esc(c.tag) + '</b></td><td style="font-size:12px">' + esc(info) +
            '</td><td style="font-size:12px">' + esc((c.evidence || []).join("、")) +
            '</td><td><select class="candWs">' + opts + '</select></td>' +
            '<td><button class="btn small btnCandOk" data-tag="' + esc(c.tag) + '">确认</button></td></tr>';
        });
        candHtml += "</table>";
      }
      var candBox = $("relCand");
      if (candBox) candBox.innerHTML = candHtml;
      Array.prototype.forEach.call(document.querySelectorAll(".btnCandOk"), function (b) {
        b.addEventListener("click", function () {
          var tag = b.getAttribute("data-tag");
          var sel = b.closest("tr").querySelector(".candWs");
          var ws = sel.value;
          if (!ws) { alert("请选择车间"); return; }
          if (ws === "__new") {
            ws = prompt("输入新车间名（如：3号车间）");
            if (!ws) return;
          }
          fetch("/api/relations/confirm-candidate", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tag: tag, workshop: ws, note: "现场铭牌人工确认" })
          }).then(function (r) { return r.json(); }).then(function () { loadRelations(); })
            .catch(function (e) { alert("确认失败：" + e.message); });
        });
      });

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
    var dt = $("dgType").value;
    $("dgMsg").textContent = "预填中…";
    fetch("/api/docgen/prefill?workshop=" + encodeURIComponent(ws) + "&doc_type=" + encodeURIComponent(dt), { method: "POST" })
      .then(function (r) { return r.json(); }).then(function (d) {
        // 把预填数据写入表单输入框
        var data = d.data || {};
        Object.keys(data).forEach(function (k) {
          if (k.startsWith("_")) return;
          var inp = document.getElementById("dg_" + k);
          if (inp && !inp.value.trim()) { inp.value = String(data[k]); }
        });
        if ($("dg_车间") && ws) $("dg_车间").value = ws;
        // 缺失字段提示
        var missing = d.missing || [];
        var msg = "";
        if (d.devices && d.devices.length) {
          msg = "已预填 " + d.devices.length + " 台设备（" + (ws || "全项目") + "）：" +
            d.devices.slice(0, 10).map(function (v) { return v.tag; }).join("、") +
            (d.devices.length > 10 ? "…" : "");
        } else {
          msg = "该车间暂无设备，请先扫描解析并重建图谱";
        }
        if (missing.length) {
          msg += "\n⚠ 缺失字段（生成时标红待补充）：" + missing.join("、");
        }
        if (d.citations && d.citations.length) {
          msg += "\n📚 已引用现行规范：" + d.citations.slice(0, 3).map(function (c) { return c.std_no; }).join("、");
        }
        $("dgMsg").textContent = msg;
        $("dgMsg").style.whiteSpace = "pre-line";
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
      var html = "<table><tr><th>标准号</th><th>标准名/文件名</th><th>状态/核验</th><th>下次检查</th><th>操作</th></tr>";
      d.items.forEach(function (it) {
        var st = { "现行": "parsed", "待核验": "partial", "废止": "failed" }[it.status] || "skipped";
        var srcLabel = it.verify_source ? '<br><span style="font-size:11px;color:var(--text2)">来源：' + esc(it.verify_source) +
          (it.verify_confidence ? " · 置信 " + Math.round((it.verify_confidence || 0) * 100) + "%" : "") + "</span>" : "";
        var searchBtn = (it.status === "废止" || it.status === "待核验")
          ? '<br><a href="https://openstd.samr.gov.cn/bzgk/gb/std_list?p.p2=' + encodeURIComponent(it.std_no || "") +
            '" target="_blank" style="font-size:11px;color:var(--accent)">搜索最新版 ↗</a>' : "";
        html += "<tr><td>" + esc(it.std_no || "—") + "</td><td>" + esc(it.std_name || it.file_name) + "</td>" +
          '<td><span class="st ' + st + '">' + it.status + "</span>" +
          (it.obsolete_note ? '<br><span style="color:var(--err);font-size:12px">' + esc(it.obsolete_note) + "</span>" : "") +
          srcLabel + searchBtn + "</td>" +
          "<td>" + esc(it.next_check || "—") + "</td>" +
          '<td><select class="platStatus" data-sha="' + it.sha256 + '" style="max-width:80px;padding:3px 6px">' +
            '<option value="现行"' + (it.status === "现行" ? " selected" : "") + ">现行</option>" +
            '<option value="待核验"' + (it.status === "待核验" ? " selected" : "") + ">待核验</option>" +
            '<option value="废止"' + (it.status === "废止" ? " selected" : "") + ">废止</option>" +
          "</select> " +
          '<button class="btn ghost platVerify" data-sha="' + it.sha256 + '" data-std="' + esc(it.std_no || "") +
          '" style="padding:3px 10px;font-size:12px">核验</button>' +
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
      box.querySelectorAll(".platVerify").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var std = btn.getAttribute("data-std");
          if (!std) { alert("该条目无标准号，无法核验"); return; }
          btn.textContent = "核验中…";
          fetch("/api/platform/verify", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sha256: btn.getAttribute("data-sha") }) })
            .then(function (r) { return r.json(); })
            .then(function (d) {
              btn.textContent = "核验";
              if (d.ok) { alert("核验完成：" + d.status + (d.source ? "（来源：" + d.source + "）" : "")); }
              else { alert("核验失败：" + (d.error || "")); }
              loadPlatform();
            }).catch(function (e) { btn.textContent = "核验"; alert("核验失败：" + e.message); });
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
      var html = "<table><tr><th>时间</th><th>项目</th><th>上传人</th><th>类型</th><th>文件</th><th>说明/转写</th></tr>";
      items.slice(0, 50).forEach(function (it) {
        var extra = esc(it.note || "");
        if (it.kind === "voice" || it.transcript) {
          extra = it.transcript
            ? '<span class="st parsed">已转写</span> <span style="color:var(--text2)">' + esc(String(it.transcript).slice(0, 120)) + "</span>"
            : '<span class="st failed">待转写</span>';
        }
        // v0.1.37：现场记录自动分析结果
        if (it.record_type) {
          var rtColor = it.record_missing && it.record_missing.length ? "#FAAD14" : "#52C41A";
          extra += '<div style="margin-top:3px"><span style="color:' + rtColor + ';font-weight:600">📋 ' + esc(it.record_type) + '</span>';
          if (it.record_missing && it.record_missing.length) {
            extra += ' <span style="color:#C0392B;font-size:11px">缺：' + esc(it.record_missing.join("、")) + "</span>";
          } else {
            extra += ' <span style="color:#52C41A;font-size:11px">字段齐全</span>';
          }
          if (it.record_generated) {
            extra += ' <span class="st parsed">已生成</span>';
          }
          extra += "</div>";
        }
        html += "<tr><td>" + esc((it.ts || "").slice(0, 16).replace("T", " ")) + "</td><td>" + esc(it.project) +
          "</td><td>" + esc(it.uploader) + "</td><td>" + esc(it.kind) + "</td><td>" + esc(it.file_name) +
          '</td><td style="font-size:12px">' + extra + "</td></tr>";
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
  // ---------- 文件夹批量上传（v0.1.22） ----------
  var BATCH_SIZE = 20;
  var batchFiles = [];          // 当前会话待传文件（File 对象）
  var batchUploading = false;
  var doneKey = "fanGongUploaded";   // localStorage：已成功 name+size 集合（断点续传用）

  function loadDoneSet() {
    try { return JSON.parse(localStorage.getItem(doneKey) || "[]"); } catch (e) { return []; }
  }
  function saveDoneSet(arr) { localStorage.setItem(doneKey, JSON.stringify(arr.slice(-2000))); }
  function markDone(name, size) {
    var s = loadDoneSet(); s.push(name + "|" + size); saveDoneSet(s);
  }
  function isDone(name, size) { return loadDoneSet().indexOf(name + "|" + size) >= 0; }

  function setBatchMsg(html) { $("batchMsg").innerHTML = html; }

  function collectDirFiles(entry, out, cb) {
    // 递归收集目录下所有文件（webkitGetAsEntry）
    var reader = entry.createReader();
    var all = [];
    function readBatch() {
      reader.readEntries(function (entries) {
        if (!entries.length) {
          (function next(i) {
            if (i >= all.length) { cb(); return; }
            var e = all[i];
            if (e.isFile) {
              e.file(function (f) { out.push(f); next(i + 1); }, function () { next(i + 1); });
            } else { collectDirFiles(e, out, function () { next(i + 1); }); }
          })(0);
          return;
        }
        all = all.concat(entries);
        readBatch();
      }, function () { cb(); });
    }
    readBatch();
  }

  function handleDropFiles(items, isDirMode) {
    var entries = [];
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      var ent = it.webkitGetAsEntry ? it.webkitGetAsEntry() : null;
      if (ent) entries.push(ent);
    }
    var out = [];
    var pend = entries.length || 1;
    function done() {
      batchFiles = batchFiles.concat(out);
      var doneSet = loadDoneSet();
      // 断点续传：过滤已传完的
      var fresh = [];
      for (var j = 0; j < out.length; j++) {
        if (isDone(out[j].name, out[j].size)) continue;
        fresh.push(out[j]);
      }
      batchFiles = batchFiles.concat(fresh);
      var n = batchFiles.length;
      $("btnBatchClear").style.display = n ? "" : "none";
      $("batchSelInfo").textContent = "已选 " + n + " 个文件（本次新加入 " + fresh.length + "，已自动跳过已传 " + (out.length - fresh.length) + " 个）";
      if (n) setBatchMsg("就绪：共 " + n + " 个文件，将分 " + Math.ceil(n / BATCH_SIZE) + " 批上传");
    }
    if (!entries.length) { done(); return; }
    var remain = entries.length;
    entries.forEach(function (e) {
      if (e.isFile) { e.file(function (f) { out.push(f); if (--remain === 0) done(); }, function () { if (--remain === 0) done(); }); }
      else collectDirFiles(e, out, function () { if (--remain === 0) done(); });
    });
  }

  $("upfilesDir").addEventListener("change", function () {
    var files = Array.prototype.slice.call(this.files || []);
    var out = files.map(function (f) { return f; });
    batchFiles = batchFiles.concat(out);
    var doneSet = loadDoneSet();
    var fresh = out.filter(function (f) { return !isDone(f.name, f.size); });
    batchFiles = batchFiles.concat(fresh);
    var n = batchFiles.length;
    $("btnBatchClear").style.display = n ? "" : "none";
    $("batchSelInfo").textContent = "已选 " + n + " 个文件（本次新加入 " + fresh.length + "，自动跳过已传 " + (out.length - fresh.length) + " 个）";
    if (n) setBatchMsg("就绪：共 " + n + " 个文件，将分 " + Math.ceil(n / BATCH_SIZE) + " 批上传");
    this.value = "";
  });

  var dz = $("dropZone");
  dz.addEventListener("dragover", function (e) { e.preventDefault(); dz.style.borderColor = "#FF7A00"; });
  dz.addEventListener("dragleave", function () { dz.style.borderColor = ""; });
  dz.addEventListener("drop", function (e) {
    e.preventDefault(); dz.style.borderColor = "";
    if (batchUploading) { setBatchMsg("上传进行中，请先等待完成"); return; }
    var items = Array.prototype.slice.call(e.dataTransfer.items || []);
    handleDropFiles(items, true);
  });

  $("btnBatchClear").addEventListener("click", function () {
    batchFiles = []; $("batchSelInfo").textContent = ""; this.style.display = "none";
    setBatchMsg("未选择文件夹"); $("batchBar").style.width = "0%";
  });

  $("btnBatchStart").addEventListener("click", function () {
    if (batchUploading) { setBatchMsg("已有批次在上传中…"); return; }
    if (!batchFiles.length) { setBatchMsg("请先选择或拖入文件夹"); return; }
    batchUploading = true;
    var total = batchFiles.length;
    var batches = Math.ceil(total / BATCH_SIZE);
    var ok = 0, fail = 0;
    $("btnBatchStart").disabled = true;
    (function runBatch(bi) {
      var slice = batchFiles.slice(bi * BATCH_SIZE, (bi + 1) * BATCH_SIZE);
      setBatchMsg("第 " + (bi + 1) + "/" + batches + " 批 · 本批 " + slice.length + " 个文件上传解析中…（累计成功 " + ok + "，失败 " + fail + "）");
      $("batchBar").style.width = Math.round(bi / batches * 100) + "%";
      var fd = new FormData();
      fd.append("uploader", $("uploader").value.trim() || "未署名");
      for (var i = 0; i < slice.length; i++) fd.append("files", slice[i]);
      fetch("/api/upload-files", { method: "POST", body: fd })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var res = d.results || [];
          for (var j = 0; j < res.length; j++) {
            var it = res[j];
            if (it.status === "parsed" || it.status === "partial") { ok++; markDone(it.file, slice[j] ? slice[j].size : 0); }
            else fail++;
          }
          if (bi + 1 < batches) runBatch(bi + 1);
          else {
            batchUploading = false; $("btnBatchStart").disabled = false;
            $("batchBar").style.width = "100%";
            setBatchMsg("全部完成：成功 " + ok + "，失败 " + fail + "（失败文件见上方失败清单，可重试）。已传文件在关页重开后自动跳过。");
            refreshStatus(); loadFailList();
            batchFiles = [];
            $("btnBatchClear").style.display = "none";
            $("batchSelInfo").textContent = "";
          }
        })
        .catch(function (e) {
          fail += slice.length;
          if (bi + 1 < batches) runBatch(bi + 1);
          else {
            batchUploading = false; $("btnBatchStart").disabled = false;
            setBatchMsg("批次中断（" + e.message + "）。已传批次已入库；重开页面重新选择文件夹会自动跳过已传文件，继续未传部分。");
            batchFiles = [];
            $("btnBatchClear").style.display = "none";
          }
        });
    })(0);
  });

  // ---------- 竣工资料自动组卷（v0.1.24） ----------
  function loadArchive() {
    fetch("/api/archive/status").then(function (r) { return r.json(); }).then(function (d) {
      $("archiveSummary").textContent = "已归档资料 " + d.generated_total + " 份 · 卷宗齐全 " + d.ready_volumes + "/" + d.total_volumes +
        " · 资料类型 " + d.have_types + "/" + d.need_types;
      var html = "";
      d.volumes.forEach(function (v) {
        var st = v.ready ? '<span class="st parsed">齐全</span>' : '<span class="st failed">缺 ' + v.missing.join("、") + "</span>";
        html += '<div style="border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:6px">' +
          '<div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap">' +
          "<b>" + v.no + " " + esc(v.name) + "</b> " + st + "</div>";
        if (v.items.length) {
          html += '<div style="font-size:12px;color:var(--text2);margin-top:4px">' +
            v.items.map(function (it) { return esc(it.doc_type) + "×" + it.count + "（最新 " + esc(it.latest) + " " + esc(it.ts) + "）"; }).join("；") + "</div>";
        }
        html += "</div>";
      });
      $("archiveList").innerHTML = html;
    }).catch(function (e) { $("archiveList").innerHTML = '<div style="color:#C0392B">组卷状态读取失败：' + esc(e.message) + "</div>"; });
  }
  $("btnArchiveRefresh").addEventListener("click", loadArchive);
  $("btnArchiveExport").addEventListener("click", function () {
    var a = document.createElement("a");
    a.href = "/api/archive/export";
    a.download = "";
    document.body.appendChild(a); a.click(); a.remove();
  });
  loadArchive();
  // ---------- 关系网络图（v0.1.25，三列分层：车间 → 图纸 → 设备） ----------
  // 确定性布局：每次打开布局一致；点击节点高亮关联子网。
  function renderRelNet(g) {
    var box = $("relNet");
    if (!box) return;
    box.innerHTML = "";
    var ws = g.workshops || [];
    var dwgs = g.drawings || [];
    var devs = g.devices || [];
    if (!ws.length && !dwgs.length && !devs.length) {
      box.innerHTML = '<div class="msg">暂无图谱数据，先扫描/上传资料并重建图谱。</div>';
      return;
    }
    // 容量控制：设备太多时只取每车间前 40 台，其余提示
    var capDev = [];
    var perWs = {};
    devs.forEach(function (d) {
      var w = (d.workshops && d.workshops[0]) || "未归车间";
      if (!perWs[w]) perWs[w] = 0;
      if (perWs[w] < 40 && capDev.length < 260) { capDev.push(d); perWs[w]++; }
    });
    devs = capDev;
    var devNames = {};
    devs.forEach(function (d) { devNames[d.tag] = d; });

    var colW = 210, gapX = 70;
    var W = colW * 3 + gapX * 2 + 60;
    var rows = Math.max(ws.length, dwgs.length, devs.length, 6);
    var cellH = 56;
    var H = rows * cellH + 40;
    var cx = { ws: 40 + colW / 2, dwg: 40 + colW + gapX + colW / 2, dev: 40 + colW * 2 + gapX * 2 + colW / 2 };

    function yAt(i, n) { return 30 + (n <= 1 ? 0 : i * (H - 60) / (n - 1 || 1)); }

    // 节点坐标
    var wsPos = {}, dwgPos = {}, devPos = {};
    ws.forEach(function (w, i) { wsPos[w.workshop] = { x: cx.ws, y: yAt(i, ws.length), c: w.workshop }; });
    dwgs.forEach(function (d, i) { dwgPos[d.file] = { x: cx.dwg, y: yAt(i, dwgs.length), c: d.no || d.file }; });
    devs.forEach(function (d, i) { devPos[d.tag] = { x: cx.dev, y: yAt(i, devs.length), c: d.tag }; });

    // 边集：车间-图纸 / 图纸-设备 / 设备-车间
    var edges = [];
    dwgs.forEach(function (d) {
      if (d.workshop && wsPos[d.workshop]) edges.push({ a: wsPos[d.workshop], b: dwgPos[d.file], cls: "ws-dwg", aK: d.workshop, bK: d.file });
    });
    var devIdxByFile = {};
    devs.forEach(function (d) {
      (d.files || []).forEach(function (f) { if (f.indexOf(".dxf") >= 0 || f.indexOf(".dwg") >= 0) (devIdxByFile[f] = devIdxByFile[f] || []).push(d.tag); });
    });
    Object.keys(devIdxByFile).forEach(function (f) {
      if (!dwgPos[f]) return;
      devIdxByFile[f].forEach(function (t) {
        if (devPos[t]) edges.push({ a: dwgPos[f], b: devPos[t], cls: "dwg-dev", aK: f, bK: t });
      });
    });
    devs.forEach(function (d) {
      var w = (d.workshops || [])[0];
      if (w && wsPos[w]) edges.push({ a: devPos[d.tag], b: wsPos[w], cls: "dev-ws", aK: d.tag, bK: w });
    });

    var svg = '<svg id="relNetSvg" viewBox="0 0 ' + W + " " + H + '" style="width:100%;max-width:1100px;background:#FAFAF8;border-radius:10px" xmlns="http://www.w3.org/2000/svg">';
    // 边
    edges.forEach(function (e) {
      svg += '<line class="netEdge" data-a="' + esc(e.aK) + '" data-b="' + esc(e.bK) + '" x1="' + e.a.x + '" y1="' + e.a.y +
        '" x2="' + e.b.x + '" y2="' + e.b.y + '" stroke="#C9C4B8" stroke-width="1.2"/>';
    });
    // 图例
    svg += '<g font-size="11" font-family="sans-serif">';
    svg += '<rect x="14" y="10" width="12" height="12" rx="3" fill="#1E5AA8"/><text x="32" y="21" fill="#444">车间</text>';
    svg += '<rect x="86" y="10" width="12" height="12" rx="3" fill="#FF7A00"/><text x="104" y="21" fill="#444">图纸</text>';
    svg += '<rect x="158" y="10" width="12" height="12" rx="3" fill="#2E9E5B"/><text x="176" y="21" fill="#444">设备</text>';
    svg += '<line x1="238" y1="16" x2="278" y2="16" stroke="#C9C4B8" stroke-width="1.2"/><text x="286" y="21" fill="#444">关联边</text>';
    svg += "</g>";
    // 车间节点
    ws.forEach(function (w, i) {
      var p = wsPos[w.workshop];
      svg += '<g class="netNode" data-k="' + esc(w.workshop) + '" data-role="ws" transform="translate(' + p.x + "," + p.y + ')">' +
        '<rect x="-64" y="-14" width="128" height="28" rx="14" fill="#1E5AA8"/>' +
        '<text x="0" y="4" text-anchor="middle" font-size="11" fill="#fff">' + esc(w.workshop) + "(" + (w.device_count || 0) + "台)" + "</text></g>";
    });
    // 图纸节点
    dwgs.forEach(function (d, i) {
      var p = dwgPos[d.file];
      svg += '<g class="netNode" data-k="' + esc(d.file) + '" data-role="dwg" transform="translate(' + p.x + "," + p.y + ')">' +
        '<rect x="-90" y="-12" width="180" height="24" rx="12" fill="#FF7A00"/>' +
        '<text x="0" y="4" text-anchor="middle" font-size="10" fill="#fff">' + esc(d.no || d.file) + "</text></g>";
    });
    // 设备节点
    devs.forEach(function (d, i) {
      var p = devPos[d.tag];
      svg += '<g class="netNode" data-k="' + esc(d.tag) + '" data-role="dev" transform="translate(' + p.x + "," + p.y + ')">' +
        '<circle r="9" fill="#2E9E5B"/><text x="0" y="3.5" text-anchor="middle" font-size="8" fill="#fff">' + esc(d.tag.slice(-3)) + "</text></g>";
    });
    svg += "</svg>";
    svg += '<div style="font-size:12px;color:var(--text2);margin-top:4px">点击节点高亮其关联子网（车间 ↔ 图纸 ↔ 设备）；设备过多时每车间最多显示 40 台。</div>';
    box.innerHTML = svg;

    var svgEl = box.querySelector("#relNetSvg");
    function clearHigh() {
      svgEl.querySelectorAll(".netEdge").forEach(function (l) { l.setAttribute("stroke", "#C9C4B8"); l.setAttribute("stroke-width", "1.2"); });
      svgEl.querySelectorAll(".netNode").forEach(function (n) { n.setAttribute("opacity", "1"); });
    }
    svgEl.querySelectorAll(".netNode").forEach(function (n) {
      n.style.cursor = "pointer";
      n.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var k = n.getAttribute("data-k");
        clearHigh();
        // 收集关联 key：直接相连的边（含自身）
        var targets = {};
        targets[k] = 1;
        edges.forEach(function (e) {
          if (e.aK === k) targets[e.bK] = 1;
          if (e.bK === k) targets[e.aK] = 1;
        });
        svgEl.querySelectorAll(".netNode").forEach(function (x) {
          if (!targets[x.getAttribute("data-k")]) x.setAttribute("opacity", "0.18");
        });
        svgEl.querySelectorAll(".netEdge").forEach(function (l) {
          var a = l.getAttribute("data-a"), b = l.getAttribute("data-b");
          if (targets[a] && targets[b]) { l.setAttribute("stroke", "#1E5AA8"); l.setAttribute("stroke-width", "2.4"); }
        });
      });
    });
    svgEl.addEventListener("click", function (e) {
      if (e.target === svgEl) clearHigh();
    });
  }


  // ---------- 车间资料自动划分（v0.1.27） ----------
  function loadWorkshopList() {
    fetch("/api/workshop/list").then(function (r) { return r.json(); }).then(function (d) {
      var groups = d.groups || {};
      var keys = Object.keys(groups).sort(function (a, b) {
        if (a === "未归车间") return 1; if (b === "未归车间") return -1;
        return a.localeCompare(b);
      });
      var total = 0, unassigned = 0;
      keys.forEach(function (k) { total += groups[k].length; if (k === "未归车间") unassigned = groups[k].length; });
      $("wsSummary").textContent = "共 " + total + " 个文件 · 已归 " + (total - unassigned) + " · 未归 " + unassigned;
      // 下拉车间选项
      var sel = $("wsBatchSel");
      var cur = sel.value;
      sel.innerHTML = '<option value="">选择目标车间</option>' +
        keys.filter(function (k) { return k !== "未归车间"; }).map(function (k) { return '<option value="' + esc(k) + '">' + esc(k) + "</option>"; }).join("") +
        '<option value="__new">+ 新建车间</option>';
      sel.value = cur;
      var html = "";
      keys.forEach(function (k) {
        var items = groups[k];
        var st = k === "未归车间" ? '<span class="st failed">未归车间</span>' : '<span class="st parsed">' + esc(k) + "</span>";
        html += '<div style="border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:8px">' +
          '<div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:4px">' +
          "<b>" + st + " · " + items.length + " 个文件</b>" +
          (k === "未归车间" ? '<button class="btn small btnWsAssignAll" data-ws="__unassigned">全部指定车间</button>' : "") +
          "</div>";
        html += '<table><tr><th style="width:24px"></th><th>文件</th><th>识别来源</th><th>置信度</th><th>候选</th><th>操作</th></tr>';
        items.slice(0, 30).forEach(function (it) {
          var src = { manual: "人工", cad_title: "CAD标题栏", filename: "文件名", content: "正文", content_multi: "正文(多车间)", none: "未识别" }[it.source] || it.source;
          var conf = Math.round((it.confidence || 0) * 100) + "%";
          var cands = (it.candidates || []).join("、") || "—";
          html += '<tr><td><input type="checkbox" class="wsCheck" value="' + esc(it.sha256) + '"></td>' +
            '<td style="font-size:12px">' + esc(it.file_name) + "</td>" +
            '<td style="font-size:12px">' + esc(src) + "</td>" +
            '<td style="font-size:12px">' + conf + "</td>" +
            '<td style="font-size:12px">' + esc(cands) + "</td>" +
            '<td><button class="btn small btnWsAssign" data-sha="' + esc(it.sha256) + '" data-name="' + esc(it.file_name) + '">指定车间</button></td></tr>';
        });
        if (items.length > 30) html += '<tr><td colspan="6" style="font-size:12px;color:var(--text2)">仅显示前 30 个，共 ' + items.length + " 个</td></tr>";
        html += "</table></div>";
      });
      $("wsList").innerHTML = html;
      Array.prototype.forEach.call(document.querySelectorAll(".btnWsAssign"), function (b) {
        b.addEventListener("click", function () {
          var ws = prompt("指定车间（如：3号车间）：");
          if (!ws) return;
          fetch("/api/workshop/assign", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sha: b.getAttribute("data-sha"), workshop: ws }) })
            .then(function (r) { return r.json(); }).then(function () { loadWorkshopList(); })
            .catch(function (e) { alert("指定失败：" + e.message); });
        });
      });
    }).catch(function (e) { $("wsList").innerHTML = '<div style="color:#C0392B">读取失败：' + esc(e.message) + "</div>"; });
  }
  $("btnWsRefresh").addEventListener("click", loadWorkshopList);
  $("btnWsReAuto").addEventListener("click", function () {
    fetch("/api/workshop/re-auto", { method: "POST" }).then(function (r) { return r.json(); }).then(function (d) {
      alert("重新识别完成，新归车间 " + d.newly_assigned + " 个");
      loadWorkshopList();
    });
  });
  $("btnWsBatch").addEventListener("click", function () {
    var shas = Array.prototype.slice.call(document.querySelectorAll(".wsCheck:checked")).map(function (c) { return c.value; });
    if (!shas.length) { alert("请先勾选文件"); return; }
    var ws = $("wsBatchSel").value;
    if (ws === "__new") { ws = prompt("输入新车间名（如：3号车间）"); }
    if (!ws) { alert("请选择目标车间"); return; }
    fetch("/api/workshop/batch-assign", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ shas: shas, workshop: ws }) })
      .then(function (r) { return r.json(); }).then(function (d) {
        alert("已批量指定 " + d.assigned + " 个文件到 " + ws + "（重建图谱后生效）");
        loadWorkshopList();
      });
  });
  loadWorkshopList();

  // ---------- 设备级车间归属（v0.1.29） ----------
  function loadDeviceWorkshop() {
    fetch("/api/device-workshop/list").then(function (r) { return r.json(); }).then(function (d) {
      var items = d.devices || [];
      var st = d.stats || {};
      $("devWsSummary").textContent = "共 " + (st.total || 0) + " 台设备 · " +
        Object.keys(st.by_workshop || {}).map(function (w) { return w + ":" + st.by_workshop[w]; }).join(" / ");
      if (!items.length) { $("devWsList").innerHTML = '<div class="empty">暂无设备车间归属，上传设备台账后点"从台账重新提取"</div>'; return; }
      var html = '<table><tr><th>位号</th><th>车间</th><th>来源</th><th>置信度</th><th>操作</th></tr>';
      items.slice(0, 80).forEach(function (it) {
        var src = { manual: "人工", excel_row: "台账行", tag_infer: "位号推断", cad: "CAD", filename: "文件名" }[it.source] || it.source;
        var conf = Math.round((it.confidence || 0) * 100) + "%";
        html += "<tr><td>" + esc(it.tag) + "</td><td>" + esc(it.workshop) + "</td>" +
          "<td>" + esc(src) + "</td><td>" + conf + "</td>" +
          '<td><button class="btn small devWsAssign" data-tag="' + esc(it.tag) + '">修改车间</button></td></tr>';
      });
      if (items.length > 80) html += '<tr><td colspan="5" style="font-size:12px;color:var(--text2)">仅显示前 80 台，共 ' + items.length + " 台</td></tr>";
      html += "</table>";
      $("devWsList").innerHTML = html;
      Array.prototype.forEach.call(document.querySelectorAll(".devWsAssign"), function (b) {
        b.addEventListener("click", function () {
          var ws = prompt("指定设备 " + b.getAttribute("data-tag") + " 的车间（如：3号车间）：");
          if (!ws) return;
          fetch("/api/device-workshop/assign", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tag: b.getAttribute("data-tag"), workshop: ws }) })
            .then(function (r) { return r.json(); }).then(function (d) {
              if (d.ok) { loadDeviceWorkshop(); }
              else { alert("指定失败"); }
            }).catch(function (e) { alert("失败：" + e.message); });
        });
      });
    }).catch(function (e) { $("devWsList").innerHTML = '<div style="color:#C0392B">加载失败：' + esc(e.message) + "</div>"; });
  }
  $("btnDevWsRefresh").addEventListener("click", loadDeviceWorkshop);
  $("btnDevWsRebuild").addEventListener("click", function () {
    fetch("/api/device-workshop/rebuild", { method: "POST" }).then(function (r) { return r.json(); })
      .then(function (d) { alert("重新提取完成，新归车间 " + d.newly_assigned + " 台，共 " + d.total + " 台（重建图谱后生效）"); loadDeviceWorkshop(); })
      .catch(function (e) { alert("失败：" + e.message); });
  });
  loadDeviceWorkshop();

  // ---------- 设计院编号↔厂家编号映射（v0.1.31） ----------
  function loadTagAlias() {
    fetch("/api/tag-alias/list").then(function (r) { return r.json(); }).then(function (d) {
      var st = d.stats || {};
      $("aliasSummary").textContent = "已确认 " + (st.confirmed_primary || 0) + " 个主位号 / " +
        (st.total_aliases || 0) + " 个别名 · 待确认 " + (st.pending || 0);
      // 待确认
      var pending = d.pending || [];
      if (!pending.length) {
        $("aliasPending").innerHTML = '<div class="empty">暂无待确认映射</div>';
      } else {
        var html = '<b style="color:#B45309">待人工确认（确认后重建图谱生效）</b><table><tr><th>设计院位号</th><th>厂家编号</th><th>来源</th><th>置信度</th><th>证据</th><th>操作</th></tr>';
        pending.forEach(function (p) {
          var src = { cad_block: "CAD块属性", excel_row: "台账行", auto: "自动" }[p.source] || p.source;
          html += "<tr><td><b>" + esc(p.primary) + "</b></td><td>" + esc(p.alias) + "</td>" +
            "<td>" + esc(src) + "</td><td>" + Math.round((p.confidence || 0) * 100) + "%</td>" +
            "<td style='font-size:12px'>" + esc(p.evidence || "") + "</td>" +
            '<td><button class="btn small aliasConfirm" data-p="' + esc(p.primary) + '" data-a="' + esc(p.alias) +
            '" style="background:#52C41A;color:#fff">确认</button> ' +
            '<button class="btn ghost small aliasReject" data-p="' + esc(p.primary) + '" data-a="' + esc(p.alias) + '">拒绝</button></td></tr>';
        });
        html += "</table>";
        $("aliasPending").innerHTML = html;
        Array.prototype.forEach.call(document.querySelectorAll(".aliasConfirm"), function (b) {
          b.addEventListener("click", function () {
            fetch("/api/tag-alias/confirm", { method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ primary: b.getAttribute("data-p"), alias: b.getAttribute("data-a") }) })
              .then(function (r) { return r.json(); }).then(function () { loadTagAlias(); })
              .catch(function (e) { alert("确认失败：" + e.message); });
          });
        });
        Array.prototype.forEach.call(document.querySelectorAll(".aliasReject"), function (b) {
          b.addEventListener("click", function () {
            fetch("/api/tag-alias/reject", { method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ primary: b.getAttribute("data-p"), alias: b.getAttribute("data-a") }) })
              .then(function (r) { return r.json(); }).then(function () { loadTagAlias(); })
              .catch(function (e) { alert("拒绝失败：" + e.message); });
          });
        });
      }
      // 已确认
      var confirmed = d.confirmed || [];
      if (!confirmed.length) {
        $("aliasConfirmed").innerHTML = "";
      } else {
        var html2 = '<b>已确认映射</b><table><tr><th>设计院位号（主）</th><th>厂家编号（别名）</th><th>来源</th></tr>';
        confirmed.forEach(function (c) {
          var src = { cad_block: "CAD块属性", excel_row: "台账行", manual: "人工", auto: "自动" }[c.source] || c.source;
          html2 += "<tr><td><b>" + esc(c.primary) + "</b></td><td>" + (c.aliases || []).map(esc).join("、") + "</td>" +
            "<td>" + esc(src) + "</td></tr>";
        });
        html2 += "</table>";
        $("aliasConfirmed").innerHTML = html2;
      }
    }).catch(function (e) { $("aliasPending").innerHTML = '<div style="color:#C0392B">加载失败：' + esc(e.message) + "</div>"; });
  }
  $("btnAliasRefresh").addEventListener("click", loadTagAlias);
  loadTagAlias();

  // ---------- 文件版本对照与冲突合并（v0.1.32） ----------
  function loadVersions() {
    fetch("/api/versions/list").then(function (r) { return r.json(); }).then(function (d) {
      var st = d.stats || {};
      $("verSummary").textContent = "总文件 " + (st.total_files || 0) + " · 多版本文件 " +
        (st.multi_version_files || 0) + " · 待确认冲突 " + (st.conflicts || 0);
      // 冲突
      var conflicts = d.conflicts || [];
      if (!conflicts.length) {
        $("verConflicts").innerHTML = "";
      } else {
        var html = '<b style="color:#C0392B">待人工确认（指定最新版后清除冲突）</b><table><tr><th>文件名</th><th>版本</th><th>SHA256</th><th>时间</th><th>来源</th><th>操作</th></tr>';
        conflicts.forEach(function (c) {
          (c.versions || []).forEach(function (v, i) {
            var isLatest = v.is_latest ? '<span class="st parsed">最新</span>' : "";
            html += "<tr><td>" + (i === 0 ? esc(c.file_name) : "") + "</td><td>v" + (i + 1) + " " + isLatest + "</td>" +
              "<td style='font-size:11px;font-family:monospace'>" + esc(v.sha256.slice(0, 16)) + "…</td>" +
              "<td style='font-size:12px'>" + esc(v.ts || "—") + "</td>" +
              "<td style='font-size:12px'>" + esc(v.source_node || "—") + "</td>" +
              '<td><button class="btn small verSetLatest" data-f="' + esc(c.file_name) + '" data-s="' + esc(v.sha256) +
              '" style="background:#1E5AA8;color:#fff">设为最新版</button></td></tr>';
          });
        });
        html += "</table>";
        $("verConflicts").innerHTML = html;
        Array.prototype.forEach.call(document.querySelectorAll(".verSetLatest"), function (b) {
          b.addEventListener("click", function () {
            fetch("/api/versions/set-latest", { method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ file_name: b.getAttribute("data-f"), sha256: b.getAttribute("data-s") }) })
              .then(function (r) { return r.json(); }).then(function (d) {
                if (d.ok) { loadVersions(); } else { alert("操作失败"); }
              }).catch(function (e) { alert("失败：" + e.message); });
          });
        });
      }
      // 多版本列表（非冲突）
      var multi = (d.multi_version || []).filter(function (m) { return !m.conflict; });
      if (!multi.length) {
        $("verList").innerHTML = conflicts.length ? "" : '<div class="empty">暂无多版本文件</div>';
      } else {
        var html2 = '<b>多版本文件（已自动按时间戳取最新版）</b><table><tr><th>文件名</th><th>版本数</th><th>最新版 SHA</th><th>最新时间</th><th>最新来源</th></tr>';
        multi.forEach(function (m) {
          html2 += "<tr><td>" + esc(m.file_name) + "</td><td>" + m.version_count + "</td>" +
            "<td style='font-size:11px;font-family:monospace'>" + esc(m.latest_sha256.slice(0, 16)) + "…</td>" +
            "<td style='font-size:12px'>" + esc(m.latest_ts || "—") + "</td>" +
            "<td style='font-size:12px'>" + esc(m.latest_source || "—") + "</td></tr>";
        });
        html2 += "</table>";
        $("verList").innerHTML = html2;
      }
    }).catch(function (e) { $("verList").innerHTML = '<div style="color:#C0392B">加载失败：' + esc(e.message) + "</div>"; });
  }
  $("btnVerRefresh").addEventListener("click", loadVersions);
  loadVersions();

  // ---------- 现场记录快速生成（v0.1.33） ----------
  var frCurrentType = "";
  var frCurrentData = {};
  $("btnFrAnalyze").addEventListener("click", function () {
    var text = $("frText").value.trim();
    if (!text) { alert("请先粘贴现场记录文字"); return; }
    $("frType").textContent = "分析中…";
    $("frMissing").textContent = "";
    fetch("/api/field-record/analyze", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.doc_type) {
          $("frType").textContent = "未能自动识别类型，请手动选择";
          $("frForm").innerHTML = '<select id="frTypeSel" style="padding:6px 10px;border:1px solid var(--line);border-radius:6px">' +
            dgTypes.map(function (t) { return '<option value="' + esc(t.key) + '">' + esc(t.label) + "</option>"; }).join("") + "</select>";
          frCurrentType = dgTypes[0].key;
          frCurrentData = d.data || {};
          $("btnFrGen").style.display = "inline-block";
          return;
        }
        frCurrentType = d.doc_type;
        frCurrentData = d.data || {};
        $("frType").textContent = "识别为：" + d.doc_type + "（置信 " + Math.round((d.confidence || 0) * 100) + "%，关键词：" + (d.matched_keywords || []).join("、") + "）";
        if (d.missing && d.missing.length) {
          $("frMissing").textContent = "⚠ 缺失字段（生成时标红待补充）：" + d.missing.join("、");
        } else {
          $("frMissing").textContent = "✓ 必填字段齐全";
          $("frMissing").style.color = "#52C41A";
        }
        // 渲染可编辑表单
        var t = dgTypes.find(function (x) { return x.key === d.doc_type; });
        var html = "";
        if (t) {
          var allFields = (t.required || []).concat((t.optional || []).filter(function (k) { return (t.required || []).indexOf(k) < 0; }));
          allFields.forEach(function (k) {
            var val = frCurrentData[k] || "";
            var isMissing = (d.missing || []).indexOf(k) >= 0;
            html += '<div style="margin-bottom:4px"><label style="font-size:12px;color:' + (isMissing ? "#C0392B" : "var(--text2)") + '">' + esc(k) + (isMissing ? " ⚠" : "") + "</label>" +
              '<input class="fr-in" data-k="' + esc(k) + '" value="' + esc(val) + '" style="width:100%;padding:5px 8px;border:1px solid ' + (isMissing ? "#C0392B" : "var(--line)") + ';border-radius:6px;box-sizing:border-box;font-size:13px"></div>';
          });
        }
        $("frForm").innerHTML = html;
        $("btnFrGen").style.display = "inline-block";
      })
      .catch(function (e) { $("frType").textContent = "分析失败：" + e.message; });
  });
  $("btnFrGen").addEventListener("click", function () {
    if (!frCurrentType) { alert("请先分析或选择记录类型"); return; }
    // 收集表单输入
    document.querySelectorAll(".fr-in").forEach(function (inp) {
      frCurrentData[inp.getAttribute("data-k")] = inp.value.trim();
    });
    // 手动选择类型
    var sel = document.getElementById("frTypeSel");
    if (sel) frCurrentType = sel.value;
    $("btnFrGen").textContent = "生成中…";
    fetch("/api/field-record/generate", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_type: frCurrentType, data: frCurrentData }) })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "生成失败"); });
        return r.blob();
      })
      .then(function (blob) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url; a.download = "繁工AI_" + frCurrentType + "_" + new Date().toISOString().slice(0, 10) + ".docx";
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        URL.revokeObjectURL(url);
        $("btnFrGen").textContent = "生成 Word 记录";
      })
      .catch(function (e) { $("btnFrGen").textContent = "生成 Word 记录"; alert("生成失败：" + e.message); });
  });

  // ---------- 群聊文件关联（v0.1.34） ----------
  function loadChatList() {
    fetch("/api/chat/list").then(function (r) { return r.json(); }).then(function (d) {
      var items = d.items || [];
      $("chatCount").textContent = "已解析群聊 " + items.length + " 个";
      if (!items.length) { $("chatList").innerHTML = '<div class="msg">暂无群聊文件。在①页上传群聊导出文件（TXT/HTML/CSV）后自动解析。</div>'; return; }
      var html = '<table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr>' +
        '<th style="text-align:left;padding:4px 6px;border-bottom:1px solid var(--line)">文件</th>' +
        '<th style="text-align:left;padding:4px 6px;border-bottom:1px solid var(--line)">消息数</th>' +
        '<th style="text-align:left;padding:4px 6px;border-bottom:1px solid var(--line)">提及设备</th>' +
        '<th style="text-align:left;padding:4px 6px;border-bottom:1px solid var(--line)">车间</th>' +
        '<th style="text-align:left;padding:4px 6px;border-bottom:1px solid var(--line)">事项</th></tr></thead><tbody>';
      items.forEach(function (it) {
        html += '<tr>' +
          '<td style="padding:4px 6px;border-bottom:1px solid var(--line2)">' + esc(it.file_name || "") + '</td>' +
          '<td style="padding:4px 6px;border-bottom:1px solid var(--line2)">' + (it.message_count || 0) + '</td>' +
          '<td style="padding:4px 6px;border-bottom:1px solid var(--line2)">' + ((it.tags || []).slice(0, 5).join("、") || "-") + ((it.tags || []).length > 5 ? "…" : "") + '</td>' +
          '<td style="padding:4px 6px;border-bottom:1px solid var(--line2)">' + ((it.workshops || []).join("、") || "-") + '</td>' +
          '<td style="padding:4px 6px;border-bottom:1px solid var(--line2)">' + ((it.topics || []).join("、") || "-") + '</td>' +
          '</tr>';
      });
      html += '</tbody></table>';
      $("chatList").innerHTML = html;
    }).catch(function (e) { $("chatList").innerHTML = '<div class="msg" style="color:#C0392B">加载失败：' + e.message + "</div>"; });
  }
  $("btnChatList").addEventListener("click", loadChatList);
  loadChatList();

  // ---------- 设备空间结构（v0.1.35） ----------
  $("btnSpatialLoad").addEventListener("click", function () {
    fetch("/api/spatial/structure").then(function (r) { return r.json(); }).then(function (d) {
      if (!d.ok) { $("spatialTree").innerHTML = '<div class="msg" style="color:#C0392B">' + esc(d.message || "加载失败") + "</div>"; return; }
      var st = d.stats || {};
      var elevInfo = st.with_elevation ? " / 已提取标高 " + st.with_elevation + " 台" : "";
      $("spatialStats").textContent = "共 " + st.workshops + " 车间 / " + st.total_devices + " 设备（图纸标注 " + st.cad_annotated + " / 台账未标注 " + st.excel_only + " / 待确认 " + st.pending_location + elevInfo + "）";
      var html = "";
      for (var wsName in d.workshops) {
        if (!d.workshops.hasOwnProperty(wsName)) continue;
        var ws = d.workshops[wsName];
        html += '<div style="margin-bottom:8px;border:1px solid var(--line);border-radius:8px;overflow:hidden">';
        html += '<div style="background:rgba(30,90,168,0.08);padding:6px 10px;font-weight:600;font-size:13px;cursor:pointer" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==\'none\'?\'block\':\'none\'">' +
          esc(wsName) + '（' + ws.device_count + ' 台：图纸标注 ' + ws.cad_annotated + ' / 台账未标注 ' + ws.excel_only + ' / 待确认 ' + ws.pending + '）▼</div>';
        html += '<div style="padding:6px 10px">';
        ws.devices.forEach(function (dev) {
          var statusColor = dev.coord_status === "图纸标注" ? "#52C41A" : (dev.coord_status === "台账记录（图纸未标注）" ? "#FAAD14" : "#C0392B");
          var coord = dev.x != null ? ("x=" + dev.x + " y=" + dev.y) : "无坐标";
          // v0.1.38：标高 z 坐标
          var elevStr = "";
          if (dev.z != null) {
            var zColor = dev.z_confidence >= 0.8 ? "#52C41A" : (dev.z_confidence >= 0.5 ? "#FAAD14" : "#C0392B");
            elevStr = ' <span style="color:' + zColor + '">z=' + dev.z + 'm</span>';
            if (dev.z_note) elevStr += ' <span style="color:var(--text2);font-size:11px">(' + esc(dev.z_note) + ')</span>';
          }
          var nb = (dev.neighbors || []).length ? (" 相邻:" + (dev.neighbors || []).map(function (n) { return n.tag + "(" + n.distance_m + "m)"; }).join("、")) : "";
          var editBtn = dev.coord_status === "位置待确认"
            ? ' <button style="font-size:11px;padding:1px 6px;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer" onclick="spatialEditDevice(\'' + esc(dev.tag) + '\')">编辑</button>'
            : '';
          html += '<div style="font-size:12px;padding:3px 0;border-bottom:1px solid var(--line2)">' +
            '<span style="font-weight:600">' + esc(dev.tag) + '</span> ' +
            '<span style="color:' + statusColor + '">[' + esc(dev.coord_status) + ']</span> ' +
            '<span style="color:var(--text2)">' + coord + elevStr + nb + '</span>' + editBtn + '</div>';
        });
        html += '</div></div>';
      }
      $("spatialTree").innerHTML = html;
    }).catch(function (e) { $("spatialTree").innerHTML = '<div class="msg" style="color:#C0392B">加载失败：' + e.message + '</div>'; });
  });
  $("btnSpatialSummary").addEventListener("click", function () {
    fetch("/api/spatial/ai-summary").then(function (r) { return r.json(); }).then(function (d) {
      if (!d.ok) { alert(d.message || "生成失败"); return; }
      $("spatialSummary").textContent = d.summary;
      $("spatialSummary").style.display = "block";
    }).catch(function (e) { alert("生成失败：" + e.message); });
  });

  // ---------- 资料完整性检查（v0.1.36） ----------
  $("btnCompletenessCheck").addEventListener("click", function () {
    $("completenessStats").textContent = "检查中…";
    fetch("/api/completeness/check").then(function (r) { return r.json(); }).then(function (d) {
      var st = d.stats || {};
      $("completenessStats").textContent = "总体完成度 " + st.overall_completion + "% | 缺失 " + st.total_missing + " 项（高优 " + st.high_priority + " / 中优 " + st.medium_priority + "）| 设备 " + st.devices + " 台 / 车间 " + st.workshops + " 个";
      // 阶段进度条
      var html = "";
      (d.phases || []).forEach(function (p) {
        var color = p.completion >= 80 ? "#52C41A" : (p.completion >= 40 ? "#FAAD14" : "#EA6668");
        html += '<div style="margin-bottom:6px">';
        html += '<div style="font-size:13px;font-weight:600;margin-bottom:2px">' + esc(p.phase) +
          ' <span style="color:' + color + ';font-weight:700">' + p.completion + '%</span>' +
          ' <span style="color:var(--text2);font-weight:400;font-size:12px">（' + p.completed + '/' + p.total_required + '，缺' + p.missing.length + '）</span></div>';
        html += '<div style="background:var(--line);border-radius:4px;height:8px;overflow:hidden"><div style="background:' + color + ';height:100%;width:' + p.completion + '%"></div></div>';
        if (p.missing.length) {
          html += '<div style="font-size:11px;color:var(--text2);margin-top:2px">缺：' + p.missing.map(function (m) {
            return esc(m.type) + (m.device ? '(' + esc(m.device) + ')' : (m.workshop ? '(' + esc(m.workshop) + ')' : ''));
          }).join("、") + '</div>';
        }
        html += '</div>';
      });
      $("completenessPhases").innerHTML = html;
      // 待办清单
      var todo = d.missing || [];
      if (todo.length) {
        var thtml = '<div style="font-size:13px;font-weight:600;margin-bottom:4px">待补充清单（按优先级）</div>';
        thtml += '<table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr>' +
          '<th style="text-align:left;padding:3px 6px;border-bottom:1px solid var(--line)">优先级</th>' +
          '<th style="text-align:left;padding:3px 6px;border-bottom:1px solid var(--line)">资料类型</th>' +
          '<th style="text-align:left;padding:3px 6px;border-bottom:1px solid var(--line)">级别</th>' +
          '<th style="text-align:left;padding:3px 6px;border-bottom:1px solid var(--line)">对象</th></tr></thead><tbody>';
        todo.slice(0, 30).forEach(function (m) {
          var pc = m.priority === "高" ? "#EA6668" : (m.priority === "中" ? "#FAAD14" : "var(--text2)");
          thtml += '<tr><td style="padding:3px 6px;border-bottom:1px solid var(--line2);color:' + pc + ';font-weight:600">' + esc(m.priority) + '</td>' +
            '<td style="padding:3px 6px;border-bottom:1px solid var(--line2)">' + esc(m.type) + '</td>' +
            '<td style="padding:3px 6px;border-bottom:1px solid var(--line2)">' + esc(m.level) + '</td>' +
            '<td style="padding:3px 6px;border-bottom:1px solid var(--line2)">' + esc(m.device || m.workshop || "项目") + '</td></tr>';
        });
        thtml += '</tbody></table>';
        if (todo.length > 30) thtml += '<div style="font-size:11px;color:var(--text2);margin-top:4px">… 另有 ' + (todo.length - 30) + ' 项</div>';
        $("completenessTodo").innerHTML = thtml;
      } else {
        $("completenessTodo").innerHTML = '<div class="msg" style="color:#52C41A">✓ 资料完整，无待补充项</div>';
      }
    }).catch(function (e) { $("completenessStats").textContent = "检查失败：" + e.message; });
  });

// v0.1.39：资料关联到设备/车间
function docRelLoad() {
  fetch("/api/doc-relations/list").then(function (r) { return r.json(); }).then(function (d) {
    if (!d.ok) { $("docRelList").innerHTML = '<div class="empty">加载失败</div>'; return; }
    var st = d.stats || {};
    $("docRelStats").textContent = "共 " + st.total_docs + " 份资料，关联设备 " + st.with_devices + " 份，关联车间 " + st.with_workshops + " 份";
    var docs = d.docs || {};
    var keys = Object.keys(docs);
    if (!keys.length) { $("docRelList").innerHTML = '<div class="empty">暂无资料关联，点"扫描已生成资料"</div>'; return; }
    var html = '<table><tr><th>资料类型</th><th>文件</th><th>关联设备</th><th>关联车间</th></tr>';
    keys.slice(0, 30).forEach(function (k) {
      var rec = docs[k];
      var devs = (rec.devices || []).join("、") || '<span style="color:var(--text2)">—</span>';
      var wss = (rec.workshops || []).join("、") || '<span style="color:var(--text2)">—</span>';
      html += '<tr><td>' + esc(rec.doc_type) + '</td><td style="font-size:11px">' + esc(rec.doc_id) + '</td><td>' + devs + '</td><td>' + wss + '</td></tr>';
    });
    html += '</table>';
    if (keys.length > 30) html += '<div style="font-size:11px;color:var(--text2);margin-top:4px">仅显示前30份，共' + keys.length + '份</div>';
    $("docRelList").innerHTML = html;
  }).catch(function () { $("docRelList").innerHTML = '<div class="empty">加载失败</div>'; });
}
document.addEventListener("DOMContentLoaded", function () {
  if ($("btnDocRelScan")) $("btnDocRelScan").addEventListener("click", function () {
    fetch("/api/doc-relations/scan", { method: "POST" }).then(function (r) { return r.json(); }).then(function (d) {
      alert("扫描完成，共登记 " + d.scanned + " 份资料");
      docRelLoad();
    });
  });
  if ($("btnDocRelRefresh")) $("btnDocRelRefresh").addEventListener("click", docRelLoad);
});

// v0.1.41：设备位置人工确认
var _editTag = "";
function spatialEditDevice(tag) {
  _editTag = tag;
  document.getElementById("editDeviceTag").textContent = tag;
  // 加载当前设备信息
  fetch("/api/spatial/device/" + encodeURIComponent(tag)).then(function (r) { return r.json(); }).then(function (d) {
    if (d.ok && d.device) {
      document.getElementById("editX").value = d.device.x != null ? d.device.x : "";
      document.getElementById("editY").value = d.device.y != null ? d.device.y : "";
      document.getElementById("editZ").value = d.device.z != null ? d.device.z : "";
      document.getElementById("editWorkshop").value = d.device.workshop || "";
    }
  }).catch(function () {});
  document.getElementById("spatialEditModal").style.display = "flex";
}
function spatialEditClose() {
  document.getElementById("spatialEditModal").style.display = "none";
}
function spatialEditConfirm() {
  var payload = {};
  var x = document.getElementById("editX").value;
  var y = document.getElementById("editY").value;
  var z = document.getElementById("editZ").value;
  var ws = document.getElementById("editWorkshop").value;
  var note = document.getElementById("editNote").value;
  if (x !== "") payload.x = parseFloat(x);
  if (y !== "") payload.y = parseFloat(y);
  if (z !== "") payload.z = parseFloat(z);
  if (ws) payload.workshop = ws;
  if (note) payload.note = note;
  payload.coord_status = "人工确认";
  fetch("/api/spatial/device/" + encodeURIComponent(_editTag) + "/update", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.ok) {
      alert("设备 " + _editTag + " 位置已确认");
      spatialEditClose();
      // 刷新空间结构
      if (typeof spatialLoad === "function") spatialLoad();
    } else {
      alert("更新失败：" + (d.message || "未知错误"));
    }
  }).catch(function (e) { alert("更新失败：" + e.message); });
}


// v0.1.43：群聊提及设备候选（人工确认/拒绝）
function chatCandLoad() {
  fetch("/api/chat/candidates").then(function (r) { return r.json(); }).then(function (d) {
    var box = document.getElementById("chatCandidates");
    var countEl = document.getElementById("chatCandCount");
    if (!d.ok) { box.innerHTML = '<div class="empty">加载失败</div>'; return; }
    var cands = d.candidates || [];
    countEl.textContent = cands.length ? ("共 " + cands.length + " 台待确认") : "暂无待确认设备";
    if (!cands.length) { box.innerHTML = '<div class="empty">群聊中未发现待确认设备</div>'; return; }
    var html = "";
    cands.forEach(function (c) {
      var tag = c.tag || "";
      var topics = (c.topics || []).join("、") || "—";
      var evidence = (c.evidence || []).slice(0, 3).join("、") || "—";
      html += '<div style="padding:6px 8px;border:1px solid var(--line);border-radius:6px;margin-bottom:4px;background:#fff">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px">';
      html += '<span style="font-weight:600;color:var(--accent)">' + esc(tag) + '</span>';
      html += '<div style="display:flex;gap:4px">';
      html += '<input id="candWs_' + esc(tag) + '" placeholder="归属车间" style="padding:3px 6px;font-size:11px;border:1px solid var(--line);border-radius:4px;width:100px">';
      html += '<button data-tag="' + esc(tag) + '" data-action="confirm" style="padding:3px 8px;font-size:11px;background:#52C41A;color:#fff;border:none;border-radius:4px;cursor:pointer">确认</button>';
      html += '<button data-tag="' + esc(tag) + '" data-action="reject" style="padding:3px 8px;font-size:11px;background:#C0392B;color:#fff;border:none;border-radius:4px;cursor:pointer">拒绝</button>';
      html += '</div></div>';
      html += '<div style="font-size:11px;color:var(--text2);margin-top:2px">话题：' + esc(topics) + ' | 证据：' + esc(evidence) + '</div>';
      html += '</div>';
    });
    box.innerHTML = html;
    // 事件委托
    box.querySelectorAll("button[data-action]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var tag = this.getAttribute("data-tag");
        var action = this.getAttribute("data-action");
        if (action === "confirm") chatCandConfirm(tag);
        else chatCandReject(tag);
      });
    });
  }).catch(function () { document.getElementById("chatCandidates").innerHTML = '<div class="empty">加载失败</div>'; });
}
function chatCandConfirm(tag) {
  var wsInput = document.getElementById("candWs_" + tag);
  var ws = wsInput ? wsInput.value.trim() : "";
  if (!ws) { alert("请先填写归属车间"); wsInput.focus(); return; }
  fetch("/api/chat/candidate/" + encodeURIComponent(tag) + "/confirm", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workshop: ws, note: "前端人工确认" })
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.ok) { alert("设备 " + tag + " 已确认归属 " + ws); chatCandLoad(); }
    else { alert("确认失败：" + (d.message || "未知错误")); }
  }).catch(function (e) { alert("确认失败：" + e.message); });
}
function chatCandReject(tag) {
  if (!confirm("确认拒绝设备 " + tag + "？拒绝后不再提示。")) return;
  fetch("/api/chat/candidate/" + encodeURIComponent(tag) + "/reject", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: "前端人工拒绝" })
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.ok) { alert("设备 " + tag + " 已拒绝"); chatCandLoad(); }
    else { alert("拒绝失败"); }
  }).catch(function (e) { alert("拒绝失败：" + e.message); });
}
document.addEventListener("DOMContentLoaded", function () {
  var btn = document.getElementById("btnChatCandRefresh");
  if (btn) btn.addEventListener("click", chatCandLoad);
});


// v0.1.45：设备台账合并去重
function eqMergeRun() {
  fetch("/api/equipment-merge/run", { method: "POST" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.ok) {
        alert("合并完成：共" + d.total_equipment + "条记录，合并为" + d.merged_count + "台设备，去重" + d.duplicate_removed + "条，待确认" + d.pending_count + "项");
        eqMergeLoad();
      } else { alert("合并失败"); }
    }).catch(function (e) { alert("合并失败：" + e.message); });
}
function eqMergeLoad() {
  fetch("/api/equipment-merge/stats").then(function (r) { return r.json(); }).then(function (d) {
    var el = document.getElementById("eqMergeStats");
    if (el) el.textContent = "合并" + d.total_merged + "台 | 多版本" + d.multi_version_devices + "台 | 去重" + d.duplicate_removed + "条 | 待确认" + d.pending_confirm + "项 | 字段冲突" + d.field_conflicts + "个";
  }).catch(function () {});
  fetch("/api/equipment-merge/list").then(function (r) { return r.json(); }).then(function (d) {
    var box = document.getElementById("eqMergeList");
    var items = d.items || [];
    if (!items.length) { box.innerHTML = '<div class="empty">暂无合并数据，请先执行合并</div>'; return; }
    var html = "";
    items.forEach(function (dev) {
      var tag = dev.canonical_tag || "";
      var name = dev.name || "—";
      var model = dev.model || "—";
      var ws = dev.workshop || "—";
      var srcCount = dev.source_count || 1;
      var conflicts = dev.conflicts || [];
      var badge = srcCount > 1 ? '<span style="background:#FF7A00;color:#fff;padding:1px 5px;border-radius:3px;font-size:10px;margin-left:4px">' + srcCount + '版本</span>' : "";
      var conflictBadge = conflicts.length ? '<span style="background:#C0392B;color:#fff;padding:1px 5px;border-radius:3px;font-size:10px;margin-left:4px">冲突' + conflicts.length + '</span>' : "";
      html += '<div style="padding:5px 8px;border:1px solid var(--line);border-radius:5px;margin-bottom:3px;background:#fff">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:3px">';
      html += '<span><strong style="color:var(--accent)">' + esc(tag) + '</strong> ' + esc(name) + badge + conflictBadge + '</span>';
      html += '<span style="font-size:11px;color:var(--text2)">' + esc(ws) + ' | ' + esc(model) + '</span>';
      html += '</div>';
      if (conflicts.length) {
        conflicts.forEach(function (c) {
          html += '<div style="font-size:11px;color:#C0392B;margin-top:2px;padding-left:8px">';
          html += esc(c.field) + ': 旧="' + esc(c.old_value) + '" 新="' + esc(c.new_value) + '" ';
          html += '<button data-tag="' + esc(tag) + '" data-field="' + esc(c.field) + '" data-choose="old" class="eq-conflict-btn" style="font-size:10px;padding:1px 5px;border:1px solid #52C41A;background:#fff;color:#52C41A;border-radius:3px;cursor:pointer">用旧</button> ';
          html += '<button data-tag="' + esc(tag) + '" data-field="' + esc(c.field) + '" data-choose="new" class="eq-conflict-btn" style="font-size:10px;padding:1px 5px;border:1px solid #FF7A00;background:#fff;color:#FF7A00;border-radius:3px;cursor:pointer">用新</button>';
          html += '</div>';
        });
      }
      html += '</div>';
    });
    box.innerHTML = html;
    box.querySelectorAll(".eq-conflict-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        eqMergeResolveConflict(this.getAttribute("data-tag"), this.getAttribute("data-field"), this.getAttribute("data-choose"));
      });
    });
  }).catch(function () { document.getElementById("eqMergeList").innerHTML = '<div class="empty">加载失败</div>'; });
  fetch("/api/equipment-merge/pending").then(function (r) { return r.json(); }).then(function (d) {
    var box = document.getElementById("eqMergePending");
    var items = d.items || [];
    if (!items.length) { box.innerHTML = '<div class="empty">暂无待确认项</div>'; return; }
    var html = "";
    items.forEach(function (p, i) {
      var mr = p.match_result || {};
      var ne = p.new_eq || {};
      html += '<div style="padding:5px 8px;border:1px solid #FF7A00;border-radius:5px;margin-bottom:3px;background:#FFF8F0">';
      html += '<div style="font-size:12px"><strong>' + esc(p.existing_tag) + '</strong> (' + esc(p.existing_name) + ') ↔ <strong>' + esc(ne.tag || ne.name || "?") + '</strong> (' + esc(ne.name || "") + ')</div>';
      html += '<div style="font-size:11px;color:var(--text2);margin:2px 0">' + esc(mr.reason || "") + ' (置信度' + (mr.confidence ? Math.round(mr.confidence * 100) + '%' : '?') + ')</div>';
      html += '<div style="display:flex;gap:4px;margin-top:3px">';
      html += '<button data-index="' + i + '" data-action="confirm" class="eq-pending-btn" style="font-size:11px;padding:2px 8px;border:none;background:#52C41A;color:#fff;border-radius:4px;cursor:pointer">确认合并</button>';
      html += '<button data-index="' + i + '" data-action="reject" class="eq-pending-btn" style="font-size:11px;padding:2px 8px;border:none;background:#C0392B;color:#fff;border-radius:4px;cursor:pointer">保持独立</button>';
      html += '</div></div>';
    });
    box.innerHTML = html;
    box.querySelectorAll(".eq-pending-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        eqMergeConfirm(parseInt(this.getAttribute("data-index")), this.getAttribute("data-action"));
      });
    });
  }).catch(function () { document.getElementById("eqMergePending").innerHTML = '<div class="empty">加载失败</div>'; });
}
function eqMergeConfirm(index, action) {
  fetch("/api/equipment-merge/confirm/" + index, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: action })
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.ok) { alert("操作成功"); eqMergeLoad(); }
    else { alert("操作失败：" + (d.error || "")); }
  }).catch(function (e) { alert("操作失败：" + e.message); });
}
function eqMergeResolveConflict(tag, field, choose) {
  fetch("/api/equipment-merge/resolve-conflict", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ canonical_tag: tag, field: field, choose: choose })
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.ok) eqMergeLoad();
    else alert("解决冲突失败");
  }).catch(function () { alert("解决冲突失败"); });
}
document.addEventListener("DOMContentLoaded", function () {
  var b1 = document.getElementById("btnEqMergeRun");
  if (b1) b1.addEventListener("click", eqMergeRun);
  var b2 = document.getElementById("btnEqMergeRefresh");
  if (b2) b2.addEventListener("click", eqMergeLoad);
});

// v0.1.46：施工日志自动生成
var currentLogDate = null;
function logAggregate() {
  fetch("/api/construction-log/aggregate", { method: "POST" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.ok) { alert("汇总完成：" + d.days + "天有现场记录"); logLoad(); }
      else { alert("汇总失败"); }
    }).catch(function (e) { alert("汇总失败：" + e.message); });
}
function logLoad() {
  fetch("/api/construction-log/stats").then(function (r) { return r.json(); }).then(function (d) {
    var el = document.getElementById("logStats");
    if (el) el.textContent = d.days_with_records + "天有记录 | 共" + d.total_field_records + "条现场记录 | 已编辑" + d.edited_logs + "天";
  }).catch(function () {});
  fetch("/api/construction-log/list").then(function (r) { return r.json(); }).then(function (d) {
    var box = document.getElementById("logList");
    var items = d.items || [];
    if (!items.length) { box.innerHTML = '<div class="empty">暂无施工日志，请先汇总现场记录</div>'; return; }
    var html = "";
    items.forEach(function (item) {
      var badge = item.status === "edited" ? '<span style="background:#52C41A;color:#fff;padding:1px 5px;border-radius:3px;font-size:10px">已编辑</span>' : '<span style="background:#999;color:#fff;padding:1px 5px;border-radius:3px;font-size:10px">自动生成</span>';
      var content = (item.施工内容 || []).join("、") || "—";
      html += '<div style="padding:5px 8px;border:1px solid var(--line);border-radius:5px;margin-bottom:3px;background:#fff;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px;cursor:pointer" class="log-item" data-date="' + item.date + '">';
      html += '<div><strong style="color:var(--accent)">' + item.date + '</strong> ' + badge + ' <span style="font-size:11px;color:var(--text2)">(' + item.record_count + '条记录)</span></div>';
      html += '<div style="font-size:11px;color:var(--text2);max-width:60%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(content) + '</div>';
      html += '</div>';
    });
    box.innerHTML = html;
    box.querySelectorAll(".log-item").forEach(function (el) {
      el.addEventListener("click", function () { logOpen(this.getAttribute("data-date")); });
    });
  }).catch(function () { document.getElementById("logList").innerHTML = '<div class="empty">加载失败</div>'; });
}
function logOpen(date) {
  currentLogDate = date;
  fetch("/api/construction-log/" + date).then(function (r) { return r.json(); }).then(function (d) {
    if (!d.ok) { alert("加载失败"); return; }
    var data = d.data || {};
    document.getElementById("logEditDate").textContent = date;
    document.getElementById("logProject").value = data["项目名称"] || "";
    document.getElementById("logWorkshop").value = data["车间"] || "";
    document.getElementById("logRecorder").value = data["记录人"] || "";
    document.getElementById("logWeather").value = data["天气"] || "";
    document.getElementById("logContent").value = data["当日工作内容"] || "";
    document.getElementById("logPersonnel").value = data["到场人员"] || "";
    document.getElementById("logMaterials").value = data["进场材料"] || "";
    document.getElementById("logMachinery").value = data["机械使用"] || "";
    document.getElementById("logTemp").value = data["温度"] || "";
    document.getElementById("logQuality").value = data["安全质量情况"] || "";
    document.getElementById("logIssues").value = data["问题及处理"] || "";
    document.getElementById("logEditor").style.display = "block";
    if (d.missing && d.missing.length) {
      alert("以下字段待补充：" + d.missing.join("、"));
    }
  }).catch(function (e) { alert("加载失败：" + e.message); });
}
function logSave() {
  if (!currentLogDate) return;
  var data = {
    "项目名称": document.getElementById("logProject").value,
    "车间": document.getElementById("logWorkshop").value,
    "记录人": document.getElementById("logRecorder").value,
    "记录日期": currentLogDate,
    "天气": document.getElementById("logWeather").value,
    "当日工作内容": document.getElementById("logContent").value,
    "到场人员": document.getElementById("logPersonnel").value,
    "进场材料": document.getElementById("logMaterials").value,
    "机械使用": document.getElementById("logMachinery").value,
    "温度": document.getElementById("logTemp").value,
    "安全质量情况": document.getElementById("logQuality").value,
    "问题及处理": document.getElementById("logIssues").value,
  };
  fetch("/api/construction-log/" + currentLogDate + "/save", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data: data })
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.ok) { alert("保存成功"); logLoad(); }
    else { alert("保存失败"); }
  }).catch(function (e) { alert("保存失败：" + e.message); });
}
function logExport() {
  if (!currentLogDate) return;
  var data = {
    project_name: document.getElementById("logProject").value,
    workshop: document.getElementById("logWorkshop").value,
  };
  fetch("/api/construction-log/" + currentLogDate + "/generate", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data)
  }).then(function (r) { return r.blob(); }).then(function (blob) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url; a.download = "施工日志_" + currentLogDate + ".docx";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }).catch(function (e) { alert("导出失败：" + e.message); });
}
document.addEventListener("DOMContentLoaded", function () {
  var b1 = document.getElementById("btnLogAggregate");
  if (b1) b1.addEventListener("click", logAggregate);
  var b2 = document.getElementById("btnLogRefresh");
  if (b2) b2.addEventListener("click", logLoad);
  var b3 = document.getElementById("btnLogSave");
  if (b3) b3.addEventListener("click", logSave);
  var b4 = document.getElementById("btnLogExport");
  if (b4) b4.addEventListener("click", logExport);
  var b5 = document.getElementById("btnLogClose");
  if (b5) b5.addEventListener("click", function () { document.getElementById("logEditor").style.display = "none"; });
});

// v0.1.47：设备间管线/连接关系
function pipingBuild() {
  fetch("/api/piping/build", { method: "POST" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.ok) {
        alert("管线网络构建完成：" + d.total_pipes + "条管线，" + d.total_connections + "个连接，" + d.devices_with_pipes + "台设备有管线");
        pipingLoad();
      } else { alert("构建失败"); }
    }).catch(function (e) { alert("构建失败：" + e.message); });
}
function pipingLoad() {
  fetch("/api/piping/stats").then(function (r) { return r.json(); }).then(function (d) {
    var el = document.getElementById("pipingStats");
    if (el) el.textContent = d.total_pipes + "条管线 | " + d.total_connections + "个连接 | " + d.devices_with_pipes + "台设备";
  }).catch(function () {});
  fetch("/api/piping/pipes").then(function (r) { return r.json(); }).then(function (d) {
    var box = document.getElementById("pipingPipeList");
    var items = d.items || [];
    if (!items.length) { box.innerHTML = '<div class="empty">暂无管线，请先构建</div>'; return; }
    var html = "";
    items.slice(0, 50).forEach(function (p) {
      var conf = p.confidence || 0;
      var confColor = conf >= 0.7 ? "#52C41A" : conf >= 0.5 ? "#FAAD14" : "#C0392B";
      html += '<div style="padding:3px 6px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:4px">';
      html += '<span><strong style="color:var(--accent)">' + esc(p.pipe_no) + '</strong> ' + esc(p.medium || "") + (p.size ? ' DN' + p.size : "") + '</span>';
      html += '<span style="color:' + confColor + ';font-size:10px">' + Math.round(conf * 100) + '%</span>';
      html += '</div>';
    });
    if (items.length > 50) html += '<div style="padding:3px;color:var(--text2);font-size:10px">...共' + items.length + '条，仅显示前50条</div>';
    box.innerHTML = html;
  }).catch(function () { document.getElementById("pipingPipeList").innerHTML = '<div class="empty">加载失败</div>'; });
  fetch("/api/piping/connections").then(function (r) { return r.json(); }).then(function (d) {
    var box = document.getElementById("pipingConnList");
    var items = d.items || [];
    if (!items.length) { box.innerHTML = '<div class="empty">暂无连接关系</div>'; return; }
    var html = "";
    items.slice(0, 50).forEach(function (c) {
      var from = c.from_device || "?";
      var to = c.to_device || "图纸外";
      html += '<div style="padding:3px 6px;border-bottom:1px solid var(--line);font-size:11px">';
      html += '<strong>' + esc(from) + '</strong> ←[' + esc(c.pipe_no) + '/' + esc(c.medium || "") + ']→ <strong>' + esc(to) + '</strong>';
      html += '</div>';
    });
    if (items.length > 50) html += '<div style="padding:3px;color:var(--text2);font-size:10px">...共' + items.length + '个，仅显示前50个</div>';
    box.innerHTML = html;
  }).catch(function () { document.getElementById("pipingConnList").innerHTML = '<div class="empty">加载失败</div>'; });
}
document.addEventListener("DOMContentLoaded", function () {
  var b1 = document.getElementById("btnPipingBuild");
  if (b1) b1.addEventListener("click", pipingBuild);
  var b2 = document.getElementById("btnPipingRefresh");
  if (b2) b2.addEventListener("click", pipingLoad);
});

// v0.1.48：竣工资料自动组卷增强
function archiveEnhancedLoad() {
  fetch("/api/archive/status-enhanced").then(function (r) { return r.json(); }).then(function (d) {
    if (!d.ok) return;
    var el = document.getElementById("archiveEnhancedStats");
    if (el) el.textContent = d.ready_volumes + "/" + d.total_volumes + "卷就绪 | " + d.total_files + "份文件 | 齐全度" + d.completeness + "%";
    var box = document.getElementById("archiveEnhancedVolumes");
    var html = "";
    (d.volumes || []).forEach(function (v) {
      var readyBadge = v.ready ? '<span style="background:#52C41A;color:#fff;padding:1px 5px;border-radius:3px;font-size:10px">齐全</span>' : '<span style="background:#C0392B;color:#fff;padding:1px 5px;border-radius:3px;font-size:10px">缺' + v.missing.length + '</span>';
      html += '<div style="padding:5px 8px;border:1px solid var(--line);border-radius:5px;margin-bottom:4px;background:#fff">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px">';
      html += '<span><strong style="color:var(--accent)">' + v.no + ' ' + esc(v.name) + '</strong> ' + readyBadge + ' <span style="font-size:11px;color:var(--text2)">(' + v.file_count + '份)</span></span>';
      html += '</div>';
      // 专业分类
      var profs = Object.keys(v.professions || {});
      if (profs.length) {
        html += '<div style="margin-top:4px;padding-left:8px;font-size:11px">';
        profs.forEach(function (prof) {
          var workshops = Object.keys(v.professions[prof] || {});
          html += '<div style="margin-bottom:2px"><strong>' + esc(prof) + '</strong>：' + workshops.map(function (ws) {
            var devs = Object.keys(v.professions[prof][ws] || {});
            return esc(ws) + '(' + devs.length + '类)';
          }).join("、") + '</div>';
        });
        html += '</div>';
      }
      if (v.missing && v.missing.length) {
        html += '<div style="margin-top:3px;font-size:11px;color:#C0392B">缺失：' + v.missing.map(esc).join("、") + '</div>';
      }
      html += '</div>';
    });
    box.innerHTML = html || '<div class="empty">暂无归档资料</div>';
  }).catch(function () {});
}
function archiveCompletenessCheck() {
  fetch("/api/archive/completeness").then(function (r) { return r.json(); }).then(function (d) {
    if (!d.ok) return;
    document.getElementById("archiveCompletenessReport").style.display = "block";
    var html = "";
    html += '<div style="margin-bottom:4px">整体齐全度：<strong>' + d.overall_completeness + '%</strong> | 就绪卷：' + d.ready_volumes + '/' + d.total_volumes + ' | 设备完整：' + (d.total_devices - d.devices_with_missing) + '/' + d.total_devices + '</div>';
    var missing = d.missing_by_volume || {};
    var missingKeys = Object.keys(missing);
    if (missingKeys.length) {
      html += '<div style="margin-bottom:4px"><strong>卷级缺失：</strong></div>';
      missingKeys.forEach(function (volNo) {
        var v = missing[volNo];
        html += '<div style="padding-left:8px;color:#C0392B">' + volNo + ' ' + esc(v.name) + '：缺' + v.missing_docs.map(esc).join("、") + '</div>';
      });
    }
    var devComp = d.device_completeness || {};
    var incompleteDevs = Object.keys(devComp).filter(function (tag) { return !devComp[tag].complete; });
    if (incompleteDevs.length) {
      html += '<div style="margin-top:4px"><strong>设备级缺失（前10台）：</strong></div>';
      incompleteDevs.slice(0, 10).forEach(function (tag) {
        html += '<div style="padding-left:8px;color:#FAAD14">' + esc(tag) + '：缺' + devComp[tag].missing.map(esc).join("、") + '</div>';
      });
      if (incompleteDevs.length > 10) html += '<div style="padding-left:8px;color:var(--text2)">...共' + incompleteDevs.length + '台设备有缺失</div>';
    }
    document.getElementById("completenessContent").innerHTML = html;
  }).catch(function () {});
}
function archiveExportEnhanced() {
  fetch("/api/archive/export-enhanced").then(function (r) { return r.blob(); }).then(function (blob) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url; a.download = "繁工AI_竣工资料归档包_增强版.zip";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }).catch(function (e) { alert("导出失败：" + e.message); });
}
document.addEventListener("DOMContentLoaded", function () {
  var b1 = document.getElementById("btnArchiveEnhanced");
  if (b1) b1.addEventListener("click", archiveEnhancedLoad);
  var b2 = document.getElementById("btnArchiveCompleteness");
  if (b2) b2.addEventListener("click", archiveCompletenessCheck);
  var b3 = document.getElementById("btnArchiveExportEnhanced");
  if (b3) b3.addEventListener("click", archiveExportEnhanced);
});

// v0.1.58：设备安装位置与管线联动可视化
function loadSpatialVizStats() {
  fetch("/api/spatial-visualization/stats").then(function (r) { return r.json(); }).then(function (d) {
    if (!d.ok) return;
    var el = document.getElementById("spatialVizStats");
    if (el) el.textContent = d.total_devices + "台设备 | " + d.devices_with_coords + "台有坐标 | " + d.piping_connections + "条管线连接 | " + d.workshops + "个车间";
    var ws = document.getElementById("vizWorkshop");
    if (ws && d.workshop_list) {
      d.workshop_list.forEach(function (w) {
        var opt = document.createElement("option");
        opt.value = w; opt.textContent = w;
        ws.appendChild(opt);
      });
    }
    var tp = document.getElementById("vizEqType");
    if (tp && d.type_list) {
      d.type_list.forEach(function (t) {
        var opt = document.createElement("option");
        opt.value = t; opt.textContent = t;
        tp.appendChild(opt);
      });
    }
  }).catch(function () {});
}
function generateSpatialViz() {
  var w = document.getElementById("vizWorkshop").value;
  var t = document.getElementById("vizEqType").value;
  var url = "/api/spatial-visualization/svg?";
  if (w) url += "workshop=" + encodeURIComponent(w) + "&";
  if (t) url += "eq_type=" + encodeURIComponent(t);
  fetch(url).then(function (r) { return r.text(); }).then(function (svg) {
    var container = document.getElementById("spatialVizContainer");
    container.style.display = "block";
    container.innerHTML = svg;
  }).catch(function (e) { alert("生成可视化图失败：" + e.message); });
}
document.addEventListener("DOMContentLoaded", function () {
  var b1 = document.getElementById("btnSpatialViz");
  if (b1) b1.addEventListener("click", generateSpatialViz);
  var b2 = document.getElementById("btnSpatialVizHtml");
  if (b2) b2.addEventListener("click", function () {
    var w = document.getElementById("vizWorkshop").value;
    var t = document.getElementById("vizEqType").value;
    var url = "/api/spatial-visualization/html?";
    if (w) url += "workshop=" + encodeURIComponent(w) + "&";
    if (t) url += "eq_type=" + encodeURIComponent(t);
    window.open(url, "_blank");
  });
  loadSpatialVizStats();
});

// v0.1.59：多电脑并库竣工资料合并
function mergeScan() {
  var path = document.getElementById("mergeSourcePath").value;
  if (!path) { alert("请输入源文件夹路径"); return; }
  fetch("/api/archive-merge/scan", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({source_path: path})}).then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("mergeScanResult");
    el.style.display = "block";
    if (d.error) { el.innerHTML = '<span style="color:#C0392B">' + esc(d.error) + '</span>'; return; }
    var html = '<strong>扫描结果：</strong>' + d.total_files + '个文件，' + (d.total_size/1024/1024).toFixed(1) + 'MB';
    if (d.type_count) {
      html += '<br>类型：';
      for (var ext in d.type_count) { html += ext + ':' + d.type_count[ext] + ' '; }
    }
    el.innerHTML = html;
  }).catch(function(e){ alert("扫描失败：" + e.message); });
}
function mergeRun() {
  var path = document.getElementById("mergeSourcePath").value;
  var node = document.getElementById("mergeNodeName").value || "unknown";
  var strategy = document.getElementById("mergeStrategy").value;
  if (!path) { alert("请输入源文件夹路径"); return; }
  if (!confirm("确认开始合并？冲突策略：" + strategy)) return;
  fetch("/api/archive-merge/merge", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({source_path: path, node_name: node, conflict_strategy: strategy})}).then(function(r){return r.json();}).then(function(d){
    if (d.ok) {
      var l = d.log;
      alert("合并完成！\\n扫描：" + l.total_scanned + "个\\n合并：" + l.merged + "个\\n跳过重复：" + l.skipped_duplicate + "个\\n冲突：" + l.conflicts + "个\\n错误：" + l.errors + "个");
      mergeLoadStats();
      mergeLoadPending();
      mergeLoadLog();
    } else {
      alert("合并失败：" + JSON.stringify(d));
    }
  }).catch(function(e){ alert("合并失败：" + e.message); });
}
function mergeLoadStats() {
  fetch("/api/archive-merge/stats").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("mergeStats");
    el.style.display = "block";
    el.innerHTML = '<strong>合并统计：</strong>操作' + d.total_merge_operations + '次 | 合并' + d.total_files_merged + '个 | 跳过' + d.total_files_skipped + '个 | 待处理冲突' + d.pending_conflicts + '个 | 当前库' + d.current_archive_files + '个文件';
  }).catch(function(){});
}
function mergeLoadPending() {
  fetch("/api/archive-merge/pending").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("mergePending");
    var pending = d.pending || [];
    var active = pending.filter(function(p){return p.status === "pending";});
    if (active.length === 0) { el.style.display = "none"; return; }
    el.style.display = "block";
    var html = '<strong>待处理冲突（' + active.length + '个）：</strong><br>';
    active.forEach(function(p, i) {
      html += '<div style="padding:4px;border-bottom:1px solid var(--line)">';
      html += esc(p.file) + '（来源：' + esc(p.node) + '）<br>';
      html += '<button class="btn" style="padding:2px 6px;font-size:10px" onclick="mergeResolve(' + i + ',\'use_source\')">用源文件</button> ';
      html += '<button class="btn" style="padding:2px 6px;font-size:10px" onclick="mergeResolve(' + i + ',\'keep_existing\')">保留现有</button> ';
      html += '<button class="btn" style="padding:2px 6px;font-size:10px" onclick="mergeResolve(' + i + ',\'skip\')">跳过</button>';
      html += '</div>';
    });
    el.innerHTML = html;
  }).catch(function(){});
}
function mergeResolve(index, decision) {
  fetch("/api/archive-merge/resolve", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({index: index, decision: decision})}).then(function(r){return r.json();}).then(function(d){
    if (d.ok) { alert("处理完成：" + d.result); mergeLoadPending(); mergeLoadStats(); }
    else { alert("处理失败：" + JSON.stringify(d)); }
  }).catch(function(e){ alert("处理失败：" + e.message); });
}
function mergeLoadLog() {
  fetch("/api/archive-merge/log?limit=10").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("mergeLog");
    var log = d.log || [];
    if (log.length === 0) { el.style.display = "none"; return; }
    el.style.display = "block";
    var html = '<strong>最近合并记录：</strong><br>';
    log.reverse().forEach(function(l) {
      html += l.timestamp.substring(0,16) + ' | ' + esc(l.node_name) + ' | 扫描' + l.total_scanned + ' 合并' + l.merged + ' 跳过' + l.skipped_duplicate + ' 冲突' + l.conflicts + '<br>';
    });
    el.innerHTML = html;
  }).catch(function(){});
}
document.addEventListener("DOMContentLoaded", function () {
  var b1 = document.getElementById("btnMergeScan");
  if (b1) b1.addEventListener("click", mergeScan);
  var b2 = document.getElementById("btnMergeRun");
  if (b2) b2.addEventListener("click", mergeRun);
  var b3 = document.getElementById("btnMergeStats");
  if (b3) b3.addEventListener("click", function() { mergeLoadStats(); mergeLoadPending(); mergeLoadLog(); });
});

// v0.1.61：设备位置按标高分层可视化
function elevationLoadList() {
  fetch("/api/spatial-visualization/elevation/list").then(function(r){return r.json();}).then(function(d){
    var sel = document.getElementById("elevationSelect");
    if (!sel) return;
    sel.innerHTML = '<option value="">全部标高</option>';
    (d.elevations || []).forEach(function(e) {
      var opt = document.createElement("option");
      opt.value = e;
      opt.textContent = "标高 " + e + "m";
      sel.appendChild(opt);
    });
    // 无标高选项
    var optNone = document.createElement("option");
    optNone.value = "none";
    optNone.textContent = "无标高设备";
    sel.appendChild(optNone);
  }).catch(function(){});
}
function elevationShowLayer() {
  var elev = document.getElementById("elevationSelect").value;
  var url = "/api/spatial-visualization/elevation/layer";
  if (elev === "none") url += "?elevation=";
  else if (elev) url += "?elevation=" + elev;
  fetch(url).then(function(r){return r.text();}).then(function(svg){
    var el = document.getElementById("elevationSvgContainer");
    el.style.display = "block";
    el.innerHTML = svg;
  }).catch(function(e){ alert("加载失败：" + e.message); });
}
function elevationShowStack() {
  fetch("/api/spatial-visualization/elevation/stack").then(function(r){return r.text();}).then(function(svg){
    var el = document.getElementById("elevationSvgContainer");
    el.style.display = "block";
    el.innerHTML = svg;
  }).catch(function(e){ alert("加载失败：" + e.message); });
}
document.addEventListener("DOMContentLoaded", function () {
  var b1 = document.getElementById("btnElevationLayer");
  if (b1) b1.addEventListener("click", elevationShowLayer);
  var b2 = document.getElementById("btnElevationStack");
  if (b2) b2.addEventListener("click", elevationShowStack);
  var b3 = document.getElementById("btnElevationList");
  if (b3) b3.addEventListener("click", elevationLoadList);
  elevationLoadList();
});

// v0.1.62：设备安装位置三维可视化
function view3dGenerate() {
  var view = document.getElementById("view3dSelect").value;
  var showPiping = document.getElementById("showPiping3d").checked;
  var url = "/api/spatial-visualization/3d/isometric?view=" + view + "&show_piping=" + showPiping;
  fetch(url).then(function(r){return r.text();}).then(function(svg){
    var el = document.getElementById("view3dSvgContainer");
    el.style.display = "block";
    el.innerHTML = svg;
  }).catch(function(e){ alert("加载失败：" + e.message); });
}
document.addEventListener("DOMContentLoaded", function () {
  var b = document.getElementById("btn3dGenerate");
  if (b) b.addEventListener("click", view3dGenerate);
});

// v0.1.63：多电脑并库设备关系合并
function relMergeFromFile() {
  var path = document.getElementById("relMergeFilePath").value;
  var node = document.getElementById("relMergeNodeName").value || "unknown";
  var strategy = document.getElementById("relMergeStrategy").value;
  if (!path) { alert("请输入关系图谱文件路径"); return; }
  if (!confirm("确认从文件合并关系图谱？冲突策略：" + strategy)) return;
  fetch("/api/relations-merge/merge-file", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({filepath: path, node_name: node, conflict_strategy: strategy})}).then(function(r){return r.json();}).then(function(d){
    if (d.ok) {
      var l = d.log;
      alert("合并完成！\\n源设备: " + l.source_devices + "台\\n合并: " + l.merged_devices + "台\\n跳过: " + l.skipped_duplicate + "台\\n冲突: " + l.conflicts + "个\\n合并后设备: " + l.total_devices_after + "台");
      relMergeLoadStats();
      relMergeLoadPending();
      relMergeLoadLog();
    } else {
      alert("合并失败：" + JSON.stringify(d));
    }
  }).catch(function(e){ alert("合并失败：" + e.message); });
}
function relMergeLoadStats() {
  fetch("/api/relations-merge/stats").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("relMergeStats");
    el.style.display = "block";
    el.innerHTML = '<strong>合并统计：</strong>操作' + d.total_merge_operations + '次 | 合并' + d.total_devices_merged + '台 | 跳过' + d.total_devices_skipped + '台 | 冲突' + d.total_conflicts + '个 | 当前设备' + d.current_total_devices + '台 | 待处理' + d.pending_conflicts + '个';
  }).catch(function(){});
}
function relMergeLoadPending() {
  fetch("/api/relations-merge/pending").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("relMergePending");
    var pending = d.pending || [];
    var active = pending.filter(function(p){return p.status === "pending";});
    if (active.length === 0) { el.style.display = "none"; return; }
    el.style.display = "block";
    var html = '<strong>待处理冲突（' + active.length + '个）：</strong><br>';
    active.forEach(function(p, i) {
      html += '<div style="padding:4px;border-bottom:1px solid var(--line)">';
      html += '设备: ' + esc(p.device_tag) + ' | 类型: ' + esc(p.conflict_type) + '（来源：' + esc(p.node) + '）<br>';
      html += '<button class="btn" style="padding:2px 6px;font-size:10px" onclick="relMergeResolve(' + i + ',\'use_source\')">用源数据</button> ';
      html += '<button class="btn" style="padding:2px 6px;font-size:10px" onclick="relMergeResolve(' + i + ',\'keep_existing\')">保留现有</button> ';
      html += '<button class="btn" style="padding:2px 6px;font-size:10px" onclick="relMergeResolve(' + i + ',\'skip\')">跳过</button>';
      html += '</div>';
    });
    el.innerHTML = html;
  }).catch(function(){});
}
function relMergeResolve(index, decision) {
  fetch("/api/relations-merge/resolve", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({index: index, decision: decision})}).then(function(r){return r.json();}).then(function(d){
    if (d.ok) { alert("处理完成：" + d.result); relMergeLoadPending(); relMergeLoadStats(); }
    else { alert("处理失败：" + JSON.stringify(d)); }
  }).catch(function(e){ alert("处理失败：" + e.message); });
}
function relMergeCheckIntegrity() {
  fetch("/api/relations-merge/integrity").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("relMergeIntegrity");
    el.style.display = "block";
    var html = '<strong>完整性检查：</strong>设备' + d.total_devices + '台 | 问题' + d.issues_count + '个<br>';
    html += '无文件设备: ' + d.devices_without_files + ' | 无车间设备: ' + d.devices_without_workshop + ' | 孤立设备: ' + d.isolated_devices + ' | 待人工确认: ' + d.pending_human_confirm;
    if (d.issues && d.issues.length > 0) {
      html += '<br><strong>问题详情：</strong><br>';
      d.issues.forEach(function(issue) {
        html += '- ' + esc(issue.type) + ': ' + (issue.devices ? issue.devices.join(', ') : issue.count || '') + '<br>';
      });
    }
    el.innerHTML = html;
  }).catch(function(e){ alert("检查失败：" + e.message); });
}
function relMergeLoadLog() {
  fetch("/api/relations-merge/log?limit=10").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("relMergeLog");
    var log = d.log || [];
    if (log.length === 0) { el.style.display = "none"; return; }
    el.style.display = "block";
    var html = '<strong>最近合并记录：</strong><br>';
    log.reverse().forEach(function(l) {
      html += l.timestamp.substring(0,16) + ' | ' + esc(l.node_name) + ' | 源' + l.source_devices + '台 合并' + l.merged_devices + ' 跳过' + l.skipped_duplicate + ' 冲突' + l.conflicts + '<br>';
    });
    el.innerHTML = html;
  }).catch(function(){});
}
document.addEventListener("DOMContentLoaded", function () {
  var b1 = document.getElementById("btnRelMergeFile");
  if (b1) b1.addEventListener("click", relMergeFromFile);
  var b2 = document.getElementById("btnRelMergeStats");
  if (b2) b2.addEventListener("click", function() { relMergeLoadStats(); relMergeLoadPending(); relMergeLoadLog(); });
  var b3 = document.getElementById("btnRelMergeIntegrity");
  if (b3) b3.addEventListener("click", relMergeCheckIntegrity);
});

// v0.1.64：设备安装位置与施工进度联动
function scheduleAuto() {
  var startDate = document.getElementById("scheduleStartDate").value;
  var days = parseInt(document.getElementById("scheduleDaysPerDevice").value) || 2;
  var body = {days_per_device: days};
  if (startDate) body.start_date = startDate;
  fetch("/api/construction-schedule/auto", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify(body)}).then(function(r){return r.json();}).then(function(d){
    if (d.ok) {
      alert("自动排程完成！\\n设备总数: " + d.total_devices + "台\\n开始日期: " + d.start_date + "\\n结束日期: " + d.end_date + "\\n总工期: " + d.total_days + "天\\n关键设备: " + d.critical_path_count + "台");
      scheduleLoadStats();
      document.getElementById("scheduleStatusUpdate").style.display = "block";
    } else {
      alert("排程失败：" + JSON.stringify(d));
    }
  }).catch(function(e){ alert("排程失败：" + e.message); });
}
function scheduleLoadStats() {
  fetch("/api/construction-schedule/stats").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("scheduleStats");
    if (!d.ok || d.total_devices === 0) {
      el.style.display = "block";
      el.innerHTML = '<span style="color:#888">' + (d.message || "暂无数据") + '</span>';
      return;
    }
    el.style.display = "block";
    var html = '<strong>施工进度统计：</strong>总设备' + d.total_devices + '台 | ';
    html += '待施工<span style="color:#95a5a6">' + d.pending + '</span> | ';
    html += '进行中<span style="color:#f39c12">' + d.in_progress + '</span> | ';
    html += '已完成<span style="color:#27ae60">' + d.completed + '</span> | ';
    html += '进度<strong>' + d.progress_percent + '%</strong> | ';
    html += '工期' + d.start_date + ' 至 ' + d.end_date + '（' + d.total_days + '天）';
    if (d.workshop_stats) {
      html += '<br><strong>按车间：</strong>';
      for (var ws in d.workshop_stats) {
        var s = d.workshop_stats[ws];
        html += ws + '(' + s.completed + '/' + s.total + ') ';
      }
    }
    el.innerHTML = html;
  }).catch(function(){});
}
function scheduleShowGantt() {
  fetch("/api/construction-schedule/gantt").then(function(r){return r.text();}).then(function(svg){
    var el = document.getElementById("scheduleGantt");
    el.style.display = "block";
    el.innerHTML = svg;
  }).catch(function(e){ alert("加载甘特图失败：" + e.message); });
}
function scheduleUpdateStatus() {
  var tag = document.getElementById("scheduleStatusTag").value;
  var status = document.getElementById("scheduleStatusSelect").value;
  var notes = document.getElementById("scheduleStatusNotes").value;
  if (!tag) { alert("请输入设备位号"); return; }
  fetch("/api/construction-schedule/status", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({tag: tag, status: status, notes: notes})}).then(function(r){return r.json();}).then(function(d){
    if (d.ok) {
      alert("设备 " + tag + " 状态已更新为：" + status);
      scheduleLoadStats();
      scheduleShowGantt();
    } else {
      alert("更新失败：" + JSON.stringify(d));
    }
  }).catch(function(e){ alert("更新失败：" + e.message); });
}
document.addEventListener("DOMContentLoaded", function () {
  var b1 = document.getElementById("btnScheduleAuto");
  if (b1) b1.addEventListener("click", scheduleAuto);
  var b2 = document.getElementById("btnScheduleStats");
  if (b2) b2.addEventListener("click", scheduleLoadStats);
  var b3 = document.getElementById("btnScheduleGantt");
  if (b3) b3.addEventListener("click", scheduleShowGantt);
  var b4 = document.getElementById("btnScheduleStatusUpdate");
  if (b4) b4.addEventListener("click", scheduleUpdateStatus);
});

// v0.1.65：设备安装位置与施工方案联动
function planGenerate() {
  var tag = document.getElementById("planDeviceTag").value.trim();
  if (!tag) { alert("请输入设备位号"); return; }
  fetch("/api/installation-plan/generate?tag=" + encodeURIComponent(tag)).then(function(r){return r.json();}).then(function(d){
    if (d.error) { alert("生成失败：" + d.error); return; }
    var el = document.getElementById("planDetail");
    el.style.display = "block";
    var html = '<strong>设备安装施工方案 - ' + esc(d.tag) + ' ' + esc(d.name || '') + '</strong><br>';
    html += '类型: ' + esc(d.type || '未知') + ' | 车间: ' + esc(d.workshop || '未分配') + ' | 标高: ' + (d.elevation != null ? d.elevation + 'm' : '未知') + '<br>';
    if (d.adjacent_devices && d.adjacent_devices.length > 0) {
      html += '<strong>相邻设备：</strong>' + d.adjacent_devices.map(function(a){return a.tag + '(' + a.distance + 'm)';}).join(', ') + '<br>';
    }
    html += '<hr style="margin:6px 0">';
    html += '<strong>一、施工环境分析</strong><br>';
    (d.construction_environment || []).forEach(function(p, i){ html += (i+1) + '. ' + esc(p) + '<br>'; });
    html += '<strong>二、施工顺序建议</strong><br>';
    (d.construction_sequence || []).forEach(function(p, i){ html += (i+1) + '. ' + esc(p) + '<br>'; });
    html += '<strong>三、安全注意事项</strong><br>';
    (d.safety_points || []).forEach(function(p, i){ html += (i+1) + '. ' + esc(p) + '<br>'; });
    html += '<strong>四、质量控制要点</strong><br>';
    (d.quality_points || []).forEach(function(p, i){ html += (i+1) + '. ' + esc(p) + '<br>'; });
    el.innerHTML = html;
  }).catch(function(e){ alert("生成失败：" + e.message); });
}
function planLoadList() {
  fetch("/api/installation-plan/list").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("planList");
    var plans = d.plans || [];
    if (plans.length === 0) { el.style.display = "block"; el.innerHTML = '<span style="color:#888">暂无已生成的方案</span>'; return; }
    el.style.display = "block";
    var html = '<strong>已生成方案（' + plans.length + '个）：</strong><br>';
    plans.forEach(function(p){
      html += '<a href="javascript:void(0)" onclick="document.getElementById(\'planDeviceTag\').value=\'' + p.tag + '\';planGenerate();" style="color:#1E5AA8">' + p.tag + '</a> ' + esc(p.name || '') + ' (' + esc(p.type || '') + '/' + esc(p.workshop || '') + ')<br>';
    });
    el.innerHTML = html;
  }).catch(function(){});
}
function planLoadStats() {
  fetch("/api/installation-plan/stats").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("planStats");
    el.style.display = "block";
    var html = '<strong>方案统计：</strong>已生成' + d.total_plans + '个 / 总设备' + d.total_devices + '台（覆盖率' + d.coverage_percent + '%）';
    if (d.type_count) {
      html += ' | 按类型: ';
      for (var t in d.type_count) { html += t + ':' + d.type_count[t] + ' '; }
    }
    el.innerHTML = html;
  }).catch(function(){});
}
document.addEventListener("DOMContentLoaded", function () {
  var b1 = document.getElementById("btnPlanGenerate");
  if (b1) b1.addEventListener("click", planGenerate);
  var b2 = document.getElementById("btnPlanList");
  if (b2) b2.addEventListener("click", planLoadList);
  var b3 = document.getElementById("btnPlanStats");
  if (b3) b3.addEventListener("click", planLoadStats);
});

// v0.1.66：多电脑并库空间模型合并
function spatialMergeFromFile() {
  var path = document.getElementById("spatialMergeFilePath").value;
  var node = document.getElementById("spatialMergeNodeName").value || "unknown";
  var strategy = document.getElementById("spatialMergeStrategy").value;
  if (!path) { alert("请输入空间模型文件路径"); return; }
  if (!confirm("确认从文件合并空间模型？冲突策略：" + strategy)) return;
  fetch("/api/spatial-merge/merge-file", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({filepath: path, node_name: node, conflict_strategy: strategy})}).then(function(r){return r.json();}).then(function(d){
    if (d.ok) {
      var l = d.log;
      alert("合并完成！\\n源设备: " + l.source_devices + "台\\n合并: " + l.merged_devices + "台\\n跳过: " + l.skipped_duplicate + "台\\n冲突: " + l.conflicts + "个\\n坐标更新: " + l.coord_updated + "台\\n标高更新: " + l.elevation_updated + "台\\n合并后设备: " + l.total_devices_after + "台");
      spatialMergeLoadStats();
      spatialMergeLoadPending();
      spatialMergeLoadLog();
    } else {
      alert("合并失败：" + JSON.stringify(d));
    }
  }).catch(function(e){ alert("合并失败：" + e.message); });
}
function spatialMergeLoadStats() {
  fetch("/api/spatial-merge/stats").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("spatialMergeStats");
    el.style.display = "block";
    el.innerHTML = '<strong>合并统计：</strong>操作' + d.total_merge_operations + '次 | 合并' + d.total_devices_merged + '台 | 跳过' + d.total_devices_skipped + '台 | 冲突' + d.total_conflicts + '个 | 当前设备' + d.current_total_devices + '台 | 有坐标' + d.current_devices_with_coords + '台 | 有标高' + d.current_devices_with_elevation + '台 | 待处理' + d.pending_conflicts + '个';
  }).catch(function(){});
}
function spatialMergeLoadPending() {
  fetch("/api/spatial-merge/pending").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("spatialMergePending");
    var pending = d.pending || [];
    var active = pending.filter(function(p){return p.status === "pending";});
    if (active.length === 0) { el.style.display = "none"; return; }
    el.style.display = "block";
    var html = '<strong>待处理冲突（' + active.length + '个）：</strong><br>';
    active.forEach(function(p, i) {
      html += '<div style="padding:4px;border-bottom:1px solid var(--line)">';
      html += '设备: ' + esc(p.device_tag) + ' | 冲突: ' + esc(p.conflict_type) + '（来源：' + esc(p.node) + '）<br>';
      if (p.details) {
        for (var k in p.details) {
          var det = p.details[k];
          html += '- ' + k + ': 源[' + (det.source ? JSON.stringify(det.source) : '') + '] vs 现[' + (det.current ? JSON.stringify(det.current) : '') + ']<br>';
        }
      }
      html += '<button class="btn" style="padding:2px 6px;font-size:10px" onclick="spatialMergeResolve(' + i + ',\'use_source\')">用源数据</button> ';
      html += '<button class="btn" style="padding:2px 6px;font-size:10px" onclick="spatialMergeResolve(' + i + ',\'keep_existing\')">保留现有</button> ';
      html += '<button class="btn" style="padding:2px 6px;font-size:10px" onclick="spatialMergeResolve(' + i + ',\'skip\')">跳过</button>';
      html += '</div>';
    });
    el.innerHTML = html;
  }).catch(function(){});
}
function spatialMergeResolve(index, decision) {
  fetch("/api/spatial-merge/resolve", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({index: index, decision: decision})}).then(function(r){return r.json();}).then(function(d){
    if (d.ok) { alert("处理完成：" + d.result); spatialMergeLoadPending(); spatialMergeLoadStats(); }
    else { alert("处理失败：" + JSON.stringify(d)); }
  }).catch(function(e){ alert("处理失败：" + e.message); });
}
function spatialMergeCheckIntegrity() {
  fetch("/api/spatial-merge/integrity").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("spatialMergeIntegrity");
    el.style.display = "block";
    var html = '<strong>空间完整性：</strong>设备' + d.total_devices + '台 | 坐标覆盖率' + d.coord_coverage_percent + '% | 标高覆盖率' + d.elevation_coverage_percent + '% | 问题' + d.issues_count + '个<br>';
    if (d.issues && d.issues.length > 0) {
      d.issues.forEach(function(issue) {
        html += '- ' + esc(issue.type) + ': ' + issue.count + '个';
        if (issue.devices) html += ' (' + issue.devices.slice(0,5).join(',') + (issue.devices.length > 5 ? '...' : '') + ')';
        html += '<br>';
      });
    }
    el.innerHTML = html;
  }).catch(function(e){ alert("检查失败：" + e.message); });
}
function spatialMergeLoadLog() {
  fetch("/api/spatial-merge/log?limit=10").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("spatialMergeLog");
    var log = d.log || [];
    if (log.length === 0) { el.style.display = "none"; return; }
    el.style.display = "block";
    var html = '<strong>最近合并记录：</strong><br>';
    log.reverse().forEach(function(l) {
      html += l.timestamp.substring(0,16) + ' | ' + esc(l.node_name) + ' | 源' + l.source_devices + '台 合并' + l.merged_devices + ' 跳过' + l.skipped_duplicate + ' 冲突' + l.conflicts + '<br>';
    });
    el.innerHTML = html;
  }).catch(function(){});
}
document.addEventListener("DOMContentLoaded", function () {
  var b1 = document.getElementById("btnSpatialMergeFile");
  if (b1) b1.addEventListener("click", spatialMergeFromFile);
  var b2 = document.getElementById("btnSpatialMergeStats");
  if (b2) b2.addEventListener("click", function() { spatialMergeLoadStats(); spatialMergeLoadPending(); spatialMergeLoadLog(); });
  var b3 = document.getElementById("btnSpatialMergeIntegrity");
  if (b3) b3.addEventListener("click", spatialMergeCheckIntegrity);
});

// v0.1.67：设备安装位置与竣工资料联动
function archiveLoadDevice() {
  var tag = document.getElementById("archiveDeviceTag").value.trim();
  if (!tag) { alert("请输入设备位号"); return; }
  fetch("/api/completion-archive/device?tag=" + encodeURIComponent(tag)).then(function(r){return r.json();}).then(function(d){
    if (d.error) { alert("加载失败：" + d.error); return; }
    var el = document.getElementById("archiveDeviceDetail");
    el.style.display = "block";
    var html = '<strong>设备竣工资料 - ' + esc(d.tag) + ' ' + esc(d.name || '') + '</strong><br>';
    html += '类型: ' + esc(d.type || '未知') + ' | 车间: ' + esc(d.workshop || '未分配') + ' | 标高: ' + (d.elevation != null ? d.elevation + 'm' : '未知') + ' | 施工状态: ' + esc(d.construction_status || 'pending') + '<br>';
    html += '完整度: <strong>' + d.completeness_percent + '%</strong>（' + d.completed_count + '/' + d.total_requirements + '项）<br>';
    if (d.missing_required && d.missing_required.length > 0) {
      html += '<span style="color:#e74c3c"><strong>缺失必选资料：</strong>' + d.missing_required.map(esc).join(', ') + '</span><br>';
    }
    if (d.missing_optional && d.missing_optional.length > 0) {
      html += '<span style="color:#f39c12"><strong>缺失可选资料：</strong>' + d.missing_optional.map(esc).join(', ') + '</span><br>';
    }
    html += '<hr style="margin:6px 0"><strong>资料清单：</strong><br>';
    (d.requirements || []).forEach(function(req) {
      var statusColor = req.status === 'completed' ? '#27ae60' : '#e74c3c';
      var statusText = req.status === 'completed' ? '✓ 已完成' : '✗ 缺失';
      html += '<span style="color:' + statusColor + '">' + (req.required ? '[必选]' : '[可选]') + ' ' + esc(req.type) + ' - ' + statusText;
      if (req.existing_file) html += ' (' + esc(req.existing_file) + ')';
      html += '</span><br>';
    });
    el.innerHTML = html;
  }).catch(function(e){ alert("加载失败：" + e.message); });
}
function archiveLoadAll() {
  fetch("/api/completion-archive/all", {method:"POST"}).then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("archiveStats");
    el.style.display = "block";
    var html = '<strong>竣工资料汇总：</strong>总设备' + d.total_devices + '台 | 完整' + d.complete_devices + '台 | 不完整' + d.incomplete_devices + '台 | 平均完整度' + d.avg_completeness_percent + '%<br>';
    if (d.by_workshop) {
      html += '<strong>按车间：</strong>';
      for (var ws in d.by_workshop) { html += esc(ws) + ':' + d.by_workshop[ws] + '台 '; }
      html += '<br>';
    }
    if (d.missing_summary) {
      html += '<strong>缺失资料汇总：</strong><br>';
      for (var dt in d.missing_summary) {
        html += '- ' + esc(dt) + ': ' + d.missing_summary[dt] + '台设备缺失<br>';
      }
    }
    el.innerHTML = html;
  }).catch(function(e){ alert("加载失败：" + e.message); });
}
function archiveLoadStats() {
  fetch("/api/completion-archive/stats").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("archiveStats");
    el.style.display = "block";
    if (d.total_devices === 0) { el.innerHTML = '<span style="color:#888">' + (d.message || '暂无数据') + '</span>'; return; }
    var html = '<strong>归档统计：</strong>总设备' + d.total_devices + '台 | 完整' + d.complete_devices + '台 | 不完整' + d.incomplete_devices + '台 | 平均完整度' + d.avg_completeness_percent + '%';
    if (d.by_workshop) {
      html += '<br><strong>按车间：</strong>';
      for (var ws in d.by_workshop) {
        var s = d.by_workshop[ws];
        html += esc(ws) + '(' + s.complete + '/' + s.total + ') ';
      }
    }
    el.innerHTML = html;
  }).catch(function(){});
}
function archiveLoadMissing() {
  fetch("/api/completion-archive/missing").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("archiveMissing");
    var missing = d.missing || [];
    if (missing.length === 0) { el.style.display = "block"; el.innerHTML = '<span style="color:#27ae60">所有资料齐全！</span>'; return; }
    el.style.display = "block";
    var html = '<strong>缺失资料清单（' + missing.length + '项）：</strong><br>';
    missing.slice(0, 30).forEach(function(m) {
      var color = m.required ? '#e74c3c' : '#f39c12';
      html += '<span style="color:' + color + '">' + (m.required ? '[必选]' : '[可选]') + ' ' + esc(m.tag) + ' ' + esc(m.name || '') + ' (' + esc(m.workshop || '') + ') - ' + esc(m.doc_type) + '</span><br>';
    });
    if (missing.length > 30) html += '... 还有 ' + (missing.length - 30) + ' 项';
    el.innerHTML = html;
  }).catch(function(e){ alert("加载失败：" + e.message); });
}
document.addEventListener("DOMContentLoaded", function () {
  var b1 = document.getElementById("btnArchiveDevice");
  if (b1) b1.addEventListener("click", archiveLoadDevice);
  var b2 = document.getElementById("btnArchiveAll");
  if (b2) b2.addEventListener("click", archiveLoadAll);
  var b3 = document.getElementById("btnArchiveStats");
  if (b3) b3.addEventListener("click", archiveLoadStats);
  var b4 = document.getElementById("btnArchiveMissing");
  if (b4) b4.addEventListener("click", archiveLoadMissing);
});

// v0.1.68：设备安装位置与吊装方案联动
function liftingGenerate() {
  var tag = document.getElementById("liftingDeviceTag").value.trim();
  if (!tag) { alert("请输入设备位号"); return; }
  fetch("/api/lifting-plan/generate?tag=" + encodeURIComponent(tag)).then(function(r){return r.json();}).then(function(d){
    if (d.error) { alert("生成失败：" + d.error); return; }
    var el = document.getElementById("liftingDetail");
    el.style.display = "block";
    var html = '<strong>设备吊装方案 - ' + esc(d.tag) + ' ' + esc(d.name || '') + '</strong><br>';
    html += '类型: ' + esc(d.type || '未知') + ' | 车间: ' + esc(d.workshop || '未分配') + ' | 标高: ' + (d.elevation != null ? d.elevation + 'm' : '未知');
    if (d.x != null && d.y != null) html += ' | 坐标: (' + d.x + ', ' + d.y + ')';
    html += '<br>';
    if (d.lifting_params) {
      var p = d.lifting_params;
      html += '<hr style="margin:6px 0"><strong>吊装参数：</strong><br>';
      html += '估算重量: ' + p.estimated_weight + 't | 估算高度: ' + p.estimated_height + 'm | 安装标高: ' + p.installation_elevation + 'm<br>';
      html += '计算吊装高度: <strong>' + p.calculated_lifting_height + 'm</strong> | 所需吊车能力: ' + p.required_crane_capacity + 't<br>';
      html += '建议吊车吨位: <strong style="color:#FF7A00">' + p.recommended_crane_tons + 't</strong> | 建议吊装半径: ' + p.recommended_lifting_radius + 'm | 吊装方法: ' + esc(p.recommended_lifting_method) + '<br>';
      if (p.special_requirements && p.special_requirements.length > 0) {
        html += '<strong>特殊要求：</strong>' + p.special_requirements.map(esc).join('；') + '<br>';
      }
    }
    html += '<hr style="margin:6px 0"><strong>吊装环境分析：</strong><br>';
    (d.lifting_environment || []).forEach(function(p, i){ html += (i+1) + '. ' + esc(p) + '<br>'; });
    html += '<strong>吊装顺序建议：</strong><br>';
    (d.lifting_sequence || []).forEach(function(s, i){ html += (i+1) + '. ' + esc(s) + '<br>'; });
    html += '<strong>安全注意事项：</strong><br>';
    (d.safety_points || []).forEach(function(s, i){ html += (i+1) + '. ' + esc(s) + '<br>'; });
    el.innerHTML = html;
  }).catch(function(e){ alert("生成失败：" + e.message); });
}
function liftingLoadList() {
  fetch("/api/lifting-plan/list").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("liftingList");
    var plans = d.plans || [];
    if (plans.length === 0) { el.style.display = "block"; el.innerHTML = '<span style="color:#888">暂无已生成的方案</span>'; return; }
    el.style.display = "block";
    var html = '<strong>已生成方案（' + plans.length + '个）：</strong><br>';
    plans.forEach(function(p){
      html += '<a href="javascript:void(0)" onclick="document.getElementById(\'liftingDeviceTag\').value=\'' + p.tag + '\';liftingGenerate();" style="color:#1E5AA8">' + p.tag + '</a> ' + esc(p.name || '') + ' (' + esc(p.type || '') + '/' + esc(p.workshop || '') + '/' + p.crane_tons + 't)<br>';
    });
    el.innerHTML = html;
  }).catch(function(){});
}
function liftingLoadStats() {
  fetch("/api/lifting-plan/stats").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("liftingStats");
    el.style.display = "block";
    if (d.total_plans === 0) { el.innerHTML = '<span style="color:#888">暂无数据</span>'; return; }
    var html = '<strong>吊装方案统计：</strong>已生成' + d.total_plans + '个 / 总设备' + d.total_devices + '台（覆盖率' + d.coverage_percent + '%）<br>';
    if (d.crane_distribution) {
      html += '<strong>吊车吨位分布：</strong>';
      for (var k in d.crane_distribution) { html += esc(k) + ':' + d.crane_distribution[k] + '台 '; }
    }
    el.innerHTML = html;
  }).catch(function(){});
}
document.addEventListener("DOMContentLoaded", function () {
  var b1 = document.getElementById("btnLiftingGenerate");
  if (b1) b1.addEventListener("click", liftingGenerate);
  var b2 = document.getElementById("btnLiftingList");
  if (b2) b2.addEventListener("click", liftingLoadList);
  var b3 = document.getElementById("btnLiftingStats");
  if (b3) b3.addEventListener("click", liftingLoadStats);
});

// v0.1.69：多电脑并库施工进度合并
function scheduleMergeFile() {
  var file = document.getElementById("scheduleMergeFile").value.trim();
  var pc = document.getElementById("scheduleMergePC").value.trim();
  var strategy = document.getElementById("scheduleMergeStrategy").value;
  if (!file) { alert("请输入源进度JSON文件路径"); return; }
  fetch("/api/schedule-merge/merge-file", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({file_path: file, source_pc: pc, conflict_strategy: strategy})
  }).then(function(r){return r.json();}).then(function(d){
    if (d.detail) { alert("合并失败：" + d.detail); return; }
    var log = d.log || {};
    alert("合并完成！源设备:" + log.source_devices + " 合并:" + log.merged_devices + " 跳过:" + log.skipped_duplicate + " 冲突:" + log.conflicts);
    scheduleMergeLoadStats();
  }).catch(function(e){ alert("合并失败：" + e.message); });
}
function scheduleMergeLoadStats() {
  fetch("/api/schedule-merge/stats").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("scheduleMergeStats");
    el.style.display = "block";
    var html = '<strong>合并统计：</strong>操作' + d.total_merge_operations + '次 | 合并' + d.total_devices_merged + '台 | 跳过' + d.total_devices_skipped + '台 | 冲突' + d.total_conflicts + '次<br>';
    html += '待处理冲突:' + d.pending_conflicts + ' | 已解决:' + d.resolved_conflicts + ' | 当前设备:' + d.current_total_devices + '台<br>';
    if (d.current_status_distribution) {
      html += '<strong>状态分布：</strong>';
      for (var k in d.current_status_distribution) { html += esc(k) + ':' + d.current_status_distribution[k] + ' '; }
    }
    el.innerHTML = html;
  }).catch(function(){});
}
function scheduleMergeLoadPending() {
  fetch("/api/schedule-merge/pending").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("scheduleMergePending");
    var pending = d.pending || [];
    if (pending.length === 0) { el.style.display = "block"; el.innerHTML = '<span style="color:#27ae60">无待处理冲突</span>'; return; }
    el.style.display = "block";
    var html = '<strong>待处理冲突（' + pending.length + '个）：</strong><br>';
    pending.slice(0, 10).forEach(function(p, i) {
      html += '<div style="margin-bottom:4px;padding:4px;background:rgba(231,76,60,0.05);border-radius:4px">';
      html += '<strong>' + esc(p.tag) + '</strong> 来源:' + esc(p.source_pc || '') + '<br>';
      html += '源状态:' + esc(p.source_status) + ' vs 当前:' + esc(p.current_status) + '<br>';
      html += '<button onclick="scheduleMergeResolve(' + i + ',\'use_source\')" style="font-size:11px;padding:2px 6px;margin-right:4px">用源数据</button>';
      html += '<button onclick="scheduleMergeResolve(' + i + ',\'keep_existing\')" style="font-size:11px;padding:2px 6px;margin-right:4px">保留现有</button>';
      html += '<button onclick="scheduleMergeResolve(' + i + ',\'skip\')" style="font-size:11px;padding:2px 6px">跳过</button>';
      html += '</div>';
    });
    el.innerHTML = html;
  }).catch(function(){});
}
function scheduleMergeResolve(index, decision) {
  fetch("/api/schedule-merge/resolve", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({index: index, decision: decision})
  }).then(function(r){return r.json();}).then(function(d){
    if (d.ok) { alert("已处理：" + d.decision); scheduleMergeLoadPending(); scheduleMergeLoadStats(); }
    else alert("处理失败：" + (d.error || ""));
  }).catch(function(e){ alert("处理失败：" + e.message); });
}
function scheduleMergeLoadIntegrity() {
  fetch("/api/schedule-merge/integrity").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("scheduleMergeIntegrity");
    el.style.display = "block";
    var html = '<strong>进度完整性：</strong>总设备' + d.total_devices + '台 | 有状态' + d.devices_with_status + '台 | 已完成' + d.completed_devices + '台 | 进行中' + d.in_progress_devices + '台 | 完成率' + d.completion_percent + '%<br>';
    if (d.issues && d.issues.length > 0) {
      html += '<strong>问题（' + d.issues_count + '个）：</strong><br>';
      d.issues.forEach(function(iss) {
        html += '- ' + esc(iss.type) + ': ' + iss.count + '台' + (iss.devices ? ' (' + iss.devices.slice(0,5).map(esc).join(',') + '...)' : '') + '<br>';
      });
    } else {
      html += '<span style="color:#27ae60">无问题</span>';
    }
    el.innerHTML = html;
  }).catch(function(){});
}
document.addEventListener("DOMContentLoaded", function () {
  var b1 = document.getElementById("btnScheduleMergeFile");
  if (b1) b1.addEventListener("click", scheduleMergeFile);
  var b2 = document.getElementById("btnScheduleMergeStats");
  if (b2) b2.addEventListener("click", scheduleMergeLoadStats);
  var b3 = document.getElementById("btnScheduleMergePending");
  if (b3) b3.addEventListener("click", scheduleMergeLoadPending);
  var b4 = document.getElementById("btnScheduleMergeIntegrity");
  if (b4) b4.addEventListener("click", scheduleMergeLoadIntegrity);
});

// v0.1.70：设备安装位置与技术交底联动
function disclosureGenerate() {
  var tag = document.getElementById("disclosureDeviceTag").value.trim();
  if (!tag) { alert("请输入设备位号"); return; }
  fetch("/api/technical-disclosure/generate?tag=" + encodeURIComponent(tag)).then(function(r){return r.json();}).then(function(d){
    if (d.error) { alert("生成失败：" + d.error); return; }
    var el = document.getElementById("disclosureDetail");
    el.style.display = "block";
    var html = '<strong>技术交底 - ' + esc(d.tag) + ' ' + esc(d.name || '') + '</strong><br>';
    html += '类型: ' + esc(d.type || '未知') + ' | 车间: ' + esc(d.workshop || '未分配');
    if (d.elevation != null) html += ' | 标高: ' + d.elevation + 'm';
    html += '<br>';
    html += '<hr style="margin:6px 0"><strong>一、工程概况</strong><br>';
    (d.project_overview || []).forEach(function(p, i){ html += (i+1) + '. ' + esc(p) + '<br>'; });
    html += '<strong>二、施工准备</strong><br>';
    (d.construction_preparation || []).forEach(function(p, i){ html += (i+1) + '. ' + esc(p) + '<br>'; });
    html += '<strong>三、施工工艺</strong><br>';
    (d.construction_process || []).forEach(function(p, i){ html += (i+1) + '. ' + esc(p) + '<br>'; });
    html += '<strong>四、质量标准</strong><br>';
    (d.quality_standards || []).forEach(function(p, i){ html += (i+1) + '. ' + esc(p) + '<br>'; });
    html += '<strong>五、安全注意事项</strong><br>';
    (d.safety_points || []).forEach(function(p, i){ html += (i+1) + '. ' + esc(p) + '<br>'; });
    html += '<strong>六、环保要求</strong><br>';
    (d.environmental_points || []).forEach(function(p, i){ html += (i+1) + '. ' + esc(p) + '<br>'; });
    el.innerHTML = html;
  }).catch(function(e){ alert("生成失败：" + e.message); });
}
function disclosureLoadList() {
  fetch("/api/technical-disclosure/list").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("disclosureList");
    var list = d.disclosures || [];
    if (list.length === 0) { el.style.display = "block"; el.innerHTML = '<span style="color:#888">暂无已生成的交底</span>'; return; }
    el.style.display = "block";
    var html = '<strong>已生成交底（' + list.length + '个）：</strong><br>';
    list.forEach(function(item) {
      html += '<a href="javascript:void(0)" onclick="document.getElementById(\'disclosureDeviceTag\').value=\'' + item.tag + '\';disclosureGenerate();" style="color:#1E5AA8">' + item.tag + '</a> ' + esc(item.name || '') + ' (' + esc(item.type || '') + '/' + esc(item.workshop || '') + ')<br>';
    });
    el.innerHTML = html;
  }).catch(function(){});
}
function disclosureLoadStats() {
  fetch("/api/technical-disclosure/stats").then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById("disclosureStats");
    el.style.display = "block";
    if (d.total_disclosures === 0) { el.innerHTML = '<span style="color:#888">暂无数据</span>'; return; }
    var html = '<strong>交底统计：</strong>已生成' + d.total_disclosures + '个 / 总设备' + d.total_devices + '台（覆盖率' + d.coverage_percent + '%）<br>';
    if (d.type_count) {
      html += '<strong>按类型：</strong>';
      for (var k in d.type_count) { html += esc(k) + ':' + d.type_count[k] + ' '; }
    }
    el.innerHTML = html;
  }).catch(function(){});
}
document.addEventListener("DOMContentLoaded", function () {
  var b1 = document.getElementById("btnDisclosureGenerate");
  if (b1) b1.addEventListener("click", disclosureGenerate);
  var b2 = document.getElementById("btnDisclosureList");
  if (b2) b2.addEventListener("click", disclosureLoadList);
  var b3 = document.getElementById("btnDisclosureStats");
  if (b3) b3.addEventListener("click", disclosureLoadStats);
});
