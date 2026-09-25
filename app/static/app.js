/* 深海观测网归因前端：草稿录入 + 调用真实业务 API + 结果展示。 */
(function () {
  "use strict";

  const state = {
    name: "",
    nodes: [],
    source: "",
    cables: [], // {a,b,risk}
    rounds: [], // {closed:Set<number>, readings:{node:bool}}
    everDiagnosed: false,
    lastResultStale: false,
  };

  const LIMITS = { nodes: [5, 10], cables: [6, 14], rounds: [2, 7] };

  const $ = (id) => document.getElementById(id);

  // ---------------------------------------------------------------- 渲染 ----

  function renderSource() {
    const sel = $("source-select");
    sel.innerHTML = "";
    state.nodes.forEach((n) => {
      const opt = document.createElement("option");
      opt.value = n;
      opt.textContent = n;
      sel.appendChild(opt);
    });
    if (state.source && state.nodes.includes(state.source)) {
      sel.value = state.source;
    } else {
      state.source = state.nodes[0] || "";
      sel.value = state.source;
    }
  }

  function renderCables() {
    const body = $("cables-body");
    body.innerHTML = "";
    state.cables.forEach((c, i) => {
      const tr = document.createElement("tr");

      const tdIdx = document.createElement("td");
      tdIdx.textContent = "#" + (i + 1);

      const mkNodeCell = (key) => {
        const td = document.createElement("td");
        const sel = document.createElement("select");
        state.nodes.forEach((n) => {
          const o = document.createElement("option");
          o.value = n;
          o.textContent = n;
          sel.appendChild(o);
        });
        sel.value = c[key] || "";
        sel.addEventListener("change", () => { c[key] = sel.value; markDirty(); });
        td.appendChild(sel);
        return td;
      };

      const tdRisk = document.createElement("td");
      const risk = document.createElement("input");
      risk.type = "number";
      risk.min = "0";
      risk.step = "any";
      risk.value = c.risk;
      risk.addEventListener("change", () => {
        c.risk = risk.value === "" ? 0 : Number(risk.value);
        markDirty();
      });
      tdRisk.appendChild(risk);

      const tdDel = document.createElement("td");
      const del = document.createElement("button");
      del.className = "btn danger small";
      del.textContent = "删除";
      del.addEventListener("click", () => {
        state.cables.splice(i, 1);
        // 重编号后同步各轮闭合集合
        renumberCablesAfterDelete(i);
        renderAll();
        markDirty();
      });
      tdDel.appendChild(del);

      tr.append(tdIdx, mkNodeCell("a"), mkNodeCell("b"), tdRisk, tdDel);
      body.appendChild(tr);
    });
    $("cables-count").textContent =
      `共 ${state.cables.length} 条（允许 ${LIMITS.cables[0]}–${LIMITS.cables[1]}）`;
  }

  function renumberCablesAfterDelete(delIdx) {
    // 闭合集合存的是编号；删除后 >delIdx 的编号前移
    state.rounds.forEach((r) => {
      const next = new Set();
      r.closed.forEach((n) => {
        if (n === delIdx + 1) return;
        next.add(n > delIdx + 1 ? n - 1 : n);
      });
      r.closed = next;
    });
  }

  function renderRounds() {
    const box = $("rounds-container");
    box.innerHTML = "";
    state.rounds.forEach((rnd, ri) => {
      const card = document.createElement("div");
      card.className = "round-card";

      const head = document.createElement("div");
      head.className = "round-head";
      const title = document.createElement("strong");
      title.textContent = `第 ${ri + 1} 轮`;
      const meta = document.createElement("span");
      meta.className = "round-meta";
      meta.textContent = `闭合 ${rnd.closed.size}/${state.cables.length} 条`;
      const del = document.createElement("button");
      del.className = "btn danger small";
      del.textContent = "删除本轮";
      del.addEventListener("click", () => {
        state.rounds.splice(ri, 1);
        renderRounds();
        markDirty();
      });
      head.append(title, meta, del);

      const closedLabel = document.createElement("div");
      closedLabel.className = "hint";
      closedLabel.textContent = "本轮闭合（投入）的电缆：";

      const toggleWrap = document.createElement("div");
      state.cables.forEach((c, ci) => {
        const num = ci + 1;
        const chip = document.createElement("span");
        chip.className = "cable-toggle" + (rnd.closed.has(num) ? " on" : "");
        chip.textContent = `#${num} ${c.a}–${c.b}`;
        chip.addEventListener("click", () => {
          if (rnd.closed.has(num)) rnd.closed.delete(num);
          else rnd.closed.add(num);
          renderRounds();
          markDirty();
        });
        toggleWrap.appendChild(chip);
      });

      const readLabel = document.createElement("div");
      readLabel.className = "hint";
      readLabel.style.marginTop = ".5rem";
      readLabel.textContent = "各传感器读数：";

      const readWrap = document.createElement("div");
      readWrap.className = "readings";
      state.nodes.forEach((n) => {
        if (!(n in rnd.readings)) rnd.readings[n] = true;
        const chip = document.createElement("span");
        chip.className = "reading-chip";
        const name = document.createElement("span");
        name.textContent = n + (n === state.source ? "（电源）" : "");
        const sel = document.createElement("select");
        [["通电", true], ["断电", false]].forEach(([txt, val]) => {
          const o = document.createElement("option");
          o.value = val ? "1" : "0";
          o.textContent = txt;
          sel.appendChild(o);
        });
        sel.value = rnd.readings[n] ? "1" : "0";
        sel.addEventListener("change", () => {
          rnd.readings[n] = sel.value === "1";
          markDirty();
        });
        chip.append(name, sel);
        readWrap.appendChild(chip);
      });

      card.append(head, closedLabel, toggleWrap, readLabel, readWrap);
      box.appendChild(card);
    });
    $("rounds-count").textContent =
      `共 ${state.rounds.length} 轮（允许 ${LIMITS.rounds[0]}–${LIMITS.rounds[1]}）`;
  }

  function renderAll() {
    renderSource();
    renderCables();
    renderRounds();
    $("nodes-count").textContent =
      `共 ${state.nodes.length} 个（允许 ${LIMITS.nodes[0]}–${LIMITS.nodes[1]}）`;
  }

  // --------------------------------------------------------------- 草稿 ----

  function applyNodes() {
    const text = $("nodes-input").value;
    const nextNodes = text.split("\n").map((s) => s.trim()).filter(Boolean);
    if (nextNodes.length !== new Set(nextNodes).size) {
      showError("节点名称存在重复，请检查。");
      return false;
    }
    if (nextNodes.length < LIMITS.nodes[0] || nextNodes.length > LIMITS.nodes[1]) {
      showError(`节点数量必须在 ${LIMITS.nodes[0]} 至 ${LIMITS.nodes[1]} 个之间，当前 ${nextNodes.length} 个。`);
      return false;
    }
    const alive = new Set(nextNodes);
    state.nodes.forEach((old) => {
      if (!alive.has(old)) {
        // 旧节点被移除：清理电缆与读数
        state.cables = state.cables.filter((c) => c.a !== old && c.b !== old);
        state.rounds.forEach((r) => { delete r.readings[old]; });
      }
    });
    state.nodes = nextNodes;
    if (!state.nodes.includes(state.source)) state.source = state.nodes[0];
    // 修复可能的悬空选择
    state.cables.forEach((c) => {
      if (!alive.has(c.a)) c.a = state.nodes[0];
      if (!alive.has(c.b)) c.b = state.nodes[0];
    });
    hideError();
    renderAll();
    markDirty();
    return true;
  }

  function addCable() {
    if (state.cables.length >= LIMITS.cables[1]) {
      showError(`电缆最多 ${LIMITS.cables[1]} 条。`);
      return;
    }
    const a = state.nodes[0] || "";
    const b = state.nodes[1] || state.nodes[0] || "";
    state.cables.push({ a, b, risk: 1 });
    renderCables();
    renderRounds();
    markDirty();
  }

  function addRound() {
    if (state.rounds.length >= LIMITS.rounds[1]) {
      showError(`试验轮次最多 ${LIMITS.rounds[1]} 轮。`);
      return;
    }
    const readings = {};
    state.nodes.forEach((n) => { readings[n] = true; });
    state.rounds.push({ closed: new Set(state.cables.map((_, i) => i + 1)), readings });
    renderRounds();
    markDirty();
  }

  function markDirty() {
    state.lastResultStale = true;
    if (state.everDiagnosed) {
      $("dirty-hint").classList.remove("hidden");
    }
    $("result-container").innerHTML = "";
  }

  function markClean() {
    state.everDiagnosed = true;
    state.lastResultStale = false;
    $("dirty-hint").classList.add("hidden");
  }

  function showError(msg) {
    const el = $("form-error");
    el.textContent = msg;
    el.classList.remove("hidden");
  }
  function hideError() { $("form-error").classList.add("hidden"); }

  function collectPayload() {
    if (state.nodes.length < LIMITS.nodes[0] || state.nodes.length > LIMITS.nodes[1]) {
      throw new Error(`节点数量必须在 ${LIMITS.nodes[0]}–${LIMITS.nodes[1]} 个之间。`);
    }
    if (state.cables.length < LIMITS.cables[0] || state.cables.length > LIMITS.cables[1]) {
      throw new Error(`电缆数量必须在 ${LIMITS.cables[0]}–${LIMITS.cables[1]} 条之间。`);
    }
    if (state.rounds.length < LIMITS.rounds[0] || state.rounds.length > LIMITS.rounds[1]) {
      throw new Error(`试验轮次必须在 ${LIMITS.rounds[0]}–${LIMITS.rounds[1]} 轮之间。`);
    }
    return {
      name: $("name-input").value.trim() || "未命名方案",
      nodes: state.nodes,
      source: state.source,
      cables: state.cables.map((c) => ({ a: c.a, b: c.b, risk: Number(c.risk) })),
      rounds: state.rounds.map((r) => ({
        closed: Array.from(r.closed).sort((a, b) => a - b),
        readings: r.readings,
      })),
    };
  }

  // --------------------------------------------------------------- 结果 ----

  function powerText(on) {
    return `<span class="dot ${on ? "on" : "off"}"></span>${on ? "通电" : "断电"}`;
  }

  function renderResult(data) {
    const box = $("result-container");
    box.innerHTML = "";

    const banner = document.createElement("div");
    if (data.feasible) {
      banner.className = "banner ok";
      banner.innerHTML =
        `<span class="icon">✅</span>
         <div>
           <h2>归因完成：找到与全部 ${data.explanation.rounds.length} 轮读数吻合的永久故障组合</h2>
           <p>已在 ${data.candidates_evaluated} 组故障组合中逐轮校验电源可达性，并按「故障数量 → 修复风险和 → 录入序列」择优。</p>
         </div>`;
      box.appendChild(banner);

      const exp = data.explanation;

      const statCard = document.createElement("div");
      statCard.className = "result-card";
      statCard.innerHTML =
        `<h3>长期失效（永久故障）电缆</h3>
         <div class="failed-list">
           ${exp.failed_cables.length === 0
             ? '<span class="hint">结论为无永久故障电缆（网络本身完好）。</span>'
             : exp.failed_cables.map((idx) => {
                 const c = exp.cables[idx - 1];
                 return `<span class="failed-chip">电缆 #${idx}：${esc(c.a)} – ${esc(c.b)}<span class="risk">修复风险 ${formatRisk(c.risk)}</span></span>`;
               }).join("")}
         </div>
         <div class="stat-row">
           <div class="stat"><div class="k">故障电缆数量</div><div class="v">${exp.failed_count}</div></div>
           <div class="stat"><div class="k">修复风险总和</div><div class="v">${formatRisk(exp.total_risk)}</div></div>
           <div class="stat"><div class="k">枚举校验组合数</div><div class="v">${data.candidates_evaluated}</div></div>
         </div>`;
      box.appendChild(statCard);

      const roundCard = document.createElement("div");
      roundCard.className = "result-card";
      roundCard.innerHTML = "<h3>逐轮可达传感器与读数比对</h3>";
      exp.rounds.forEach((rr) => {
        const div = document.createElement("div");
        div.className = "round-result " + (rr.matched ? "match" : "mismatch");
        const rows = rr.readings.map((row) => `
          <tr class="${row.match ? "" : "bad-row"}">
            <td>${esc(row.node)}${row.node === state.source ? "（电源）" : ""}</td>
            <td>${powerText(row.expected)}</td>
            <td>${powerText(row.actual)}</td>
            <td>${row.match ? '<span class="tag ok">一致</span>' : '<span class="tag bad">矛盾</span>'}</td>
          </tr>`).join("");
        div.innerHTML = `
          <h4>第 ${rr.round_index + 1} 轮
            ${rr.matched ? '<span class="tag ok">读数全部吻合</span>' : '<span class="tag bad">存在矛盾</span>'}
          </h4>
          <div class="reachable-line">本轮闭合电缆：<b>${rr.closed.length ? rr.closed.map((n) => "#" + n).join("、") : "（无）"}</b></div>
          <div class="reachable-line">电源可达传感器（通电）：<b>${rr.reachable_sensors.length ? rr.reachable_sensors.map(esc).join("、") : "（无）"}</b></div>
          <table class="compare-table">
            <thead><tr><th>传感器</th><th>录入读数</th><th>推导读数</th><th>比对</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>`;
        roundCard.appendChild(div);
      });
      box.appendChild(roundCard);
    } else {
      banner.className = "banner fail";
      banner.innerHTML =
        `<span class="icon">⚠️</span>
         <div>
           <h2>不存在共同解释</h2>
           <p>${data.message}</p>
           <p>已穷举 ${data.candidates_evaluated} 组永久故障组合并逐轮比对，无任何一组能同时满足全部轮次读数。请修改草稿后重新发起归因。</p>
         </div>`;
      box.appendChild(banner);
    }
  }

  function formatRisk(v) {
    return Number.isInteger(v) ? String(v) : Number(v).toFixed(2).replace(/\.?0+$/, "");
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (ch) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
    ));
  }

  async function diagnose() {
    hideError();
    // 用户可能改了节点文本但未点"应用节点"，提交前先同步
    const typedNodes = $("nodes-input").value.split("\n").map((s) => s.trim()).filter(Boolean);
    const sameNodes = typedNodes.length === state.nodes.length &&
      typedNodes.every((n, i) => n === state.nodes[i]);
    if (!sameNodes && !applyNodes()) return;
    let payload;
    try {
      payload = collectPayload();
    } catch (e) {
      showError(e.message);
      return;
    }
    const btn = $("diagnose-btn");
    btn.disabled = true;
    btn.textContent = "归因计算中…";
    try {
      const resp = await fetch("/api/diagnose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok) {
        showError(data.detail || `服务返回错误（${resp.status}）`);
        return;
      }
      // 修改草稿前不得保留旧结论：渲染前先清空，再展示本次结论
      $("result-container").innerHTML = "";
      renderResult(data);
      markClean();
    } catch (e) {
      showError("请求归因服务失败：" + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "发起归因";
    }
  }

  // --------------------------------------------------------------- 示例 ----

  function loadSample() {
    // 环网示例：电源 P，传感器 A/B/C/D；电缆 #4(B–C) 长期失效。
    // 第 1 轮全部闭合时环网替代通路使所有传感器仍通电（单轮读数会漏判）；
    // 联合 3 轮读数后唯一最少故障解释指向 #4。
    $("name-input").value = "南海三号环网 · 9 月维护";
    const nodes = ["P", "A", "B", "C", "D"];
    $("nodes-input").value = nodes.join("\n");
    state.nodes = nodes;
    state.source = "P";
    state.cables = [
      { a: "P", b: "A", risk: 5 },
      { a: "P", b: "B", risk: 9 },
      { a: "A", b: "B", risk: 2 },
      { a: "B", b: "C", risk: 3 },
      { a: "C", b: "D", risk: 4 },
      { a: "A", b: "D", risk: 6 },
    ];
    state.rounds = [
      { closed: new Set([1, 2, 3, 4, 5, 6]),
        readings: { P: true, A: true, B: true, C: true, D: true } },
      { closed: new Set([1, 3, 4, 5]),
        readings: { P: true, A: true, B: true, C: false, D: false } },
      { closed: new Set([2, 4, 6]),
        readings: { P: true, A: false, B: true, C: false, D: false } },
    ];
    hideError();
    renderAll();
    markDirty();
  }

  // --------------------------------------------------------------- 绑定 ----

  function init() {
    $("apply-nodes-btn").addEventListener("click", applyNodes);
    $("source-select").addEventListener("change", (e) => {
      state.source = e.target.value;
      renderRounds();
      markDirty();
    });
    $("add-cable-btn").addEventListener("click", addCable);
    $("add-round-btn").addEventListener("click", addRound);
    $("diagnose-btn").addEventListener("click", diagnose);
    $("sample-btn").addEventListener("click", loadSample);
    $("name-input").addEventListener("input", markDirty);

    loadSample();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
