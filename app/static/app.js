const state = {
  documents: [],
  selectedDocIds: new Set(),
  activeInsightDocId: null,
  sessionId: null,
};

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  if (res.status === 204) return null;
  return res.json();
}

async function loadHealthAndMetrics() {
  const [health, docStats, procStats] = await Promise.all([
    api("/api/v1/health"),
    api("/api/v1/metrics/documents"),
    api("/api/v1/metrics/processing"),
  ]);
  document.getElementById("aiModeBadge").textContent =
    `AI: ${health.ai_mode.toUpperCase()} (${health.chat_model}) · DB: ${health.database_backend}`;

  const pipeAvg = procStats.stage_latency_ms.full_pipeline
    ? `${procStats.stage_latency_ms.full_pipeline.avg_duration_ms} ms`
    : "—";

  const grid = document.getElementById("metricsGrid");
  grid.innerHTML = `
    <div class="metric-box"><div class="metric-val">${docStats.total_documents}</div><div class="metric-lbl">Documents</div></div>
    <div class="metric-box"><div class="metric-val">${docStats.total_chunks}</div><div class="metric-lbl">Indexed Chunks</div></div>
    <div class="metric-box"><div class="metric-val">${pipeAvg}</div><div class="metric-lbl">Avg Pipeline</div></div>
    <div class="metric-box"><div class="metric-val">${procStats.cache_stats.hit_rate_pct}%</div><div class="metric-lbl">Cache Hit Rate</div></div>
  `;
}

function updateScopeLabel() {
  const count = state.selectedDocIds.size;
  document.getElementById("scopeLabel").textContent =
    count === 0 ? "Chat scope: All completed docs" : `Chat scope: ${count} selected doc(s)`;
}

async function loadDocuments() {
  const data = await api("/api/v1/documents");
  state.documents = data.items;
  const list = document.getElementById("docList");
  if (!state.documents.length) {
    list.innerHTML = `<p class="muted">No documents uploaded yet.</p>`;
    return;
  }

  list.innerHTML = "";
  for (const doc of state.documents) {
    const card = document.createElement("div");
    card.className = `doc-card ${state.activeInsightDocId === doc.id ? "active" : ""}`;
    const checked = state.selectedDocIds.has(doc.id) ? "checked" : "";
    card.innerHTML = `
      <div class="doc-row">
        <label style="display:flex;align-items:center;gap:0.4rem;overflow:hidden;cursor:pointer;">
          <input type="checkbox" data-check="${doc.id}" ${checked} />
          <span class="doc-title" title="${doc.filename}">${doc.filename}</span>
        </label>
        <button class="ghost-btn" data-del="${doc.id}" style="padding:0.1rem 0.4rem;font-size:0.7rem;">✕</button>
      </div>
      <div class="doc-meta">
        <span>v${doc.version} · ${doc.page_count}p · ${doc.word_count}w</span>
        <span class="status-${doc.status}">${doc.status}</span>
      </div>
    `;
    card.addEventListener("click", (e) => {
      if (e.target.dataset.check || e.target.dataset.del) return;
      selectDocumentForInsights(doc.id);
    });
    list.appendChild(card);
  }

  list.querySelectorAll("input[data-check]").forEach((cb) => {
    cb.addEventListener("change", (e) => {
      const id = Number(e.target.dataset.check);
      if (e.target.checked) state.selectedDocIds.add(id);
      else state.selectedDocIds.delete(id);
      state.sessionId = null;
      updateScopeLabel();
    });
  });

  list.querySelectorAll("button[data-del]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = Number(e.target.dataset.del);
      await api(`/api/v1/documents/${id}`, { method: "DELETE" });
      state.selectedDocIds.delete(id);
      if (state.activeInsightDocId === id) state.activeInsightDocId = null;
      await refreshAll();
    });
  });

  if (!state.activeInsightDocId && state.documents[0]?.status === "completed") {
    selectDocumentForInsights(state.documents[0].id);
  }
}

async function selectDocumentForInsights(docId) {
  state.activeInsightDocId = docId;
  const pane = document.getElementById("insightsPane");
  const customBox = document.getElementById("customSummaryBox");
  try {
    const ins = await api(`/api/v1/documents/${docId}/insights`);
    const tags = [...ins.categories, ...ins.topics.slice(0, 3)]
      .map((t) => `<span class="tag">${t}</span>`)
      .join("");
    const bullets = ins.key_insights.map((b) => `<li>${b}</li>`).join("");
    pane.innerHTML = `
      <p><strong>Sentiment:</strong> ${ins.sentiment} · <span class="muted">${ins.model_used}</span></p>
      <div class="tag-list">${tags}</div>
      <p style="margin-top:0.4rem;">${ins.summary}</p>
      <ul class="insight-bullets">${bullets}</ul>
    `;
    customBox.hidden = false;
    document.getElementById("customSummaryOut").textContent = "";
  } catch (err) {
    pane.innerHTML = `<p class="muted">${err.message}</p>`;
    customBox.hidden = true;
  }
  await loadDocuments();
}

function appendMessage(role, content, citations = []) {
  const container = document.getElementById("chatMessages");
  container.querySelector(".empty-state")?.remove();

  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = content;

  if (citations.length) {
    const citeWrap = document.createElement("div");
    citeWrap.className = "citations";
    for (const c of citations) {
      const item = document.createElement("div");
      item.className = "citation-item";
      item.innerHTML = `<strong>[Source ${c.source_index}]</strong> ${c.filename} (p.${c.page_number}, score ${c.score}) — ${c.excerpt}`;
      citeWrap.appendChild(item);
    }
    div.appendChild(citeWrap);
  }
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function renderFollowUps(questions = []) {
  const bar = document.getElementById("followUpBar");
  bar.innerHTML = "";
  for (const q of questions) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip";
    btn.textContent = q;
    btn.addEventListener("click", () => {
      document.getElementById("questionInput").value = q;
      document.getElementById("chatForm").requestSubmit();
    });
    bar.appendChild(btn);
  }
}

document.getElementById("uploadForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fileInput = document.getElementById("fileInput");
  if (!fileInput.files.length) return;
  const btn = document.getElementById("uploadBtn");
  btn.disabled = true;
  btn.textContent = "Processing...";
  try {
    const files = Array.from(fileInput.files);
    let createdIds = [];
    if (files.length === 1) {
      const fd = new FormData();
      fd.append("file", files[0]);
      const created = await api("/api/v1/documents/upload", { method: "POST", body: fd });
      createdIds = [created.id];
    } else {
      const fd = new FormData();
      for (const f of files) {
        fd.append("files", f);
      }
      const batch = await api("/api/v1/documents/upload/batch", { method: "POST", body: fd });
      createdIds = batch.documents.map((d) => d.id);
    }
    fileInput.value = "";
    // Poll briefly if background task is still running
    for (let i = 0; i < 25; i++) {
      const statuses = await Promise.all(
        createdIds.map((id) => api(`/api/v1/documents/${id}`).then((d) => d.status))
      );
      if (statuses.every((s) => s === "completed" || s === "failed")) break;
      await new Promise((r) => setTimeout(r, 350));
    }
    if (createdIds.length) {
      state.activeInsightDocId = createdIds[0];
      await refreshAll();
      await selectDocumentForInsights(createdIds[0]);
    }
  } catch (err) {
    alert(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Upload & Analyze";
  }
});

document.getElementById("chatForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("questionInput");
  const question = input.value.trim();
  if (!question) return;
  input.value = "";
  appendMessage("user", question);

  const askBtn = document.getElementById("askBtn");
  askBtn.disabled = true;
  try {
    if (!state.sessionId) {
      const sess = await api("/api/v1/chat/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_ids: Array.from(state.selectedDocIds) }),
      });
      state.sessionId = sess.id;
      document.getElementById("sessionLabel").textContent = `Session #${sess.id}`;
    }
    const res = await api(`/api/v1/chat/sessions/${state.sessionId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const msg = res.assistant_message;
    appendMessage("assistant", msg.content, msg.citations);
    renderFollowUps(msg.follow_up_questions);
    await loadHealthAndMetrics();
  } catch (err) {
    appendMessage("assistant", `Error: ${err.message}`);
  } finally {
    askBtn.disabled = false;
  }
});

document.getElementById("newSessionBtn").addEventListener("click", () => {
  state.sessionId = null;
  document.getElementById("sessionLabel").textContent = "Multi-turn RAG with source citations";
  document.getElementById("chatMessages").innerHTML =
    `<div class="empty-state">Started a fresh chat session. Ask a question below.</div>`;
  renderFollowUps([]);
});

document.getElementById("runSummaryBtn").addEventListener("click", async () => {
  if (!state.activeInsightDocId) return;
  const out = document.getElementById("customSummaryOut");
  out.textContent = "Generating...";
  const res = await api(`/api/v1/documents/${state.activeInsightDocId}/summarize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      length: document.getElementById("sumLength").value,
      focus: document.getElementById("sumFocus").value,
      tone: document.getElementById("sumTone").value,
    }),
  });
  out.textContent = res.summary;
  await loadHealthAndMetrics();
});

document.getElementById("refreshBtn").addEventListener("click", refreshAll);

async function refreshAll() {
  await Promise.all([loadHealthAndMetrics(), loadDocuments()]);
}

function connectDocumentStatusSocket() {
  try {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/api/v1/ws/documents`);
    ws.onmessage = (evt) => {
      const data = JSON.parse(evt.data);
      if (data && data.event === "status" && (data.status === "completed" || data.status === "failed")) {
        refreshAll();
      }
    };
    ws.onclose = () => {
      setTimeout(connectDocumentStatusSocket, 5000);
    };
  } catch {
    // Graceful fallback to manual refresh if WebSocket is unavailable
  }
}

refreshAll();
connectDocumentStatusSocket();
