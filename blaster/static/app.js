(() => {
  const $ = (id) => document.getElementById(id);

  const connPill = $("conn-pill");
  const connLabel = $("conn-label");
  const light = $("light");
  const lightLabel = $("light-label");
  const deviceName = $("device-name");
  const smState = $("sm-state");
  const camEl = $("cam");
  const micEl = $("mic");
  const disconnectTimeoutEl = $("disconnect-timeout");
  const errorEl = $("error");
  const commandsEl = $("commands");
  const btnReconnect = $("btn-reconnect");
  const configForm = $("config-form");
  const configMsg = $("config-msg");
  const deviceNameInput = $("device_name_input");
  const activityLog = $("activity-log");
  const activityEmpty = $("activity-empty");

  const EVENT_CONTAINERS = {
    OnConnect: $("onconnect-rows"),
    OnDisconnect: $("ondisconnect-rows"),
    Active: $("active-rows"),
    Idle: $("idle-rows"),
  };

  const ACTIVITY_MAX = 100;
  let configCache = null;
  let commandsLoaded = false;
  // Anchor to current seq on first poll so only events while the page is open are shown.
  let lastEventId = null;

  function setMsg(text, kind) {
    configMsg.textContent = text || "";
    configMsg.className = "form-msg" + (kind ? ` ${kind}` : "");
  }

  function onOff(v) {
    return v ? "on" : "off";
  }

  function formatDuration(totalSeconds) {
    const seconds = Math.max(0, Number(totalSeconds) || 0);
    const minutes = Math.floor(seconds / 60);
    return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
  }

  function formatDisconnectTimeout(timeout) {
    if (!timeout || timeout.state === "unknown") {
      return "unavailable (firmware update needed)";
    }
    if (timeout.state === "interrupted") {
      const command = timeout.command || "command";
      return `${command} canceled with ${formatDuration(timeout.remaining_seconds)} remaining`;
    }
    if (timeout.state === "expired") {
      return `${timeout.command || "scheduled command"} timeout elapsed`;
    }
    return "no countdown";
  }

  function renderStatus(s) {
    let state = "disconnected";
    let label = "Disconnected";
    if (s.reconnecting) {
      state = "reconnecting";
      label = "Reconnecting…";
    } else if (s.connected) {
      state = "connected";
      label = "Connected";
    }
    connPill.dataset.state = state;
    connLabel.textContent = label;

    const cmd = s.last_command || "—";
    light.dataset.color = s.last_command || "unknown";
    lightLabel.textContent = cmd;
    light.title = s.last_status ? `Status: ${s.last_status}` : "Last command";

    deviceName.textContent = s.device_name || "—";
    smState.textContent = s.state || "—";
    camEl.textContent = onOff(!!s.cam);
    micEl.textContent = onOff(!!s.mic);
    disconnectTimeoutEl.textContent = formatDisconnectTimeout(s.disconnect_timeout);

    if (s.error) {
      errorEl.hidden = false;
      errorEl.textContent = s.error;
    } else {
      errorEl.hidden = true;
      errorEl.textContent = "";
    }

    btnReconnect.disabled = !!s.connected || !!s.reconnecting;
  }

  const EVENT_FIELD_LABELS = {
    OnConnect: {
      delay: "Delay (sec)",
      delayTitle: "Seconds to wait before sending this command after connect",
    },
    OnDisconnect: {
      delay: "Timeout (sec)",
      delayTitle: "Seconds after BLE disconnect before the ESP32 runs this command",
    },
    Active: {
      delay: "Delay (sec)",
      delayTitle: "Seconds to wait before sending this command when cam/mic turns on",
    },
    Idle: {
      delay: "Cooldown / delay (sec)",
      delayTitle: "First row: cooldown with cam+mic off. Other rows: wait before that command",
    },
  };

  function specRow(spec, opts) {
    const row = document.createElement("div");
    row.className = "event-row";
    const canRemove = opts.canRemove !== false;
    const labels = EVENT_FIELD_LABELS[opts.eventKey] || EVENT_FIELD_LABELS.Active;

    row.innerHTML = `
      <label class="field">
        <span class="field-label">Command</span>
        <input type="text" data-field="NamedCommand" placeholder="e.g. Red" value="${escapeAttr(spec.NamedCommand || "")}" required>
      </label>
      <label class="field">
        <span class="field-label">${escapeAttr(labels.delay)}</span>
        <input type="number" data-field="Delay" min="0" step="1" value="${spec.Delay ?? ""}" title="${escapeAttr(labels.delayTitle)}" aria-label="${escapeAttr(labels.delay)}">
      </label>
      ${canRemove ? '<button type="button" class="remove" aria-label="Remove">Remove</button>' : '<span class="remove-spacer"></span>'}
    `;

    const removeBtn = row.querySelector(".remove");
    if (removeBtn) {
      removeBtn.addEventListener("click", () => row.remove());
    }
    return row;
  }

  function escapeAttr(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatTs(iso) {
    try {
      return new Date(iso).toLocaleTimeString(undefined, { hour12: false });
    } catch {
      return iso || "";
    }
  }

  function appendActivity(events) {
    if (!Array.isArray(events)) return;
    if (lastEventId === null) {
      lastEventId = events.length ? events[events.length - 1].id : 0;
      return;
    }
    const fresh = events.filter((e) => e.id > lastEventId);
    if (!fresh.length) return;
    lastEventId = fresh[fresh.length - 1].id;
    if (activityEmpty) activityEmpty.hidden = true;
    // Oldest of the batch first so prepend keeps newest on top.
    for (let i = fresh.length - 1; i >= 0; i--) {
      const e = fresh[i];
      const row = document.createElement("div");
      row.className = "activity-entry";
      row.dataset.kind = e.kind || "info";
      row.innerHTML =
        `<span class="activity-ts">${escapeHtml(formatTs(e.ts))}</span>` +
        `<span class="activity-msg">${escapeHtml(e.message || "")}</span>`;
      activityLog.prepend(row);
    }
    while (activityLog.querySelectorAll(".activity-entry").length > ACTIVITY_MAX) {
      const last = activityLog.querySelector(".activity-entry:last-of-type");
      if (!last) break;
      last.remove();
    }
  }

  function renderEventRows(key, specs) {
    const container = EVENT_CONTAINERS[key];
    container.innerHTML = "";
    const canRemove = key !== "OnDisconnect";
    (specs || []).forEach((spec) => {
      container.appendChild(specRow(spec, { canRemove, eventKey: key }));
    });
    if (!specs || specs.length === 0) {
      container.appendChild(
        specRow(
          { NamedCommand: "", Delay: key === "Idle" ? 120 : 0 },
          { canRemove, eventKey: key }
        )
      );
    }
  }

  function readEventRows(key) {
    const container = EVENT_CONTAINERS[key];
    const rows = [...container.querySelectorAll(".event-row")];
    return rows.map((row) => {
      const named = row.querySelector('[data-field="NamedCommand"]').value.trim();
      const delayRaw = row.querySelector('[data-field="Delay"]').value;
      const out = { NamedCommand: named };
      if (delayRaw !== "") {
        out.Delay = Number.parseInt(delayRaw, 10);
      }
      return out;
    }).filter((s) => s.NamedCommand);
  }

  function renderConfig(cfg) {
    configCache = cfg;
    deviceNameInput.value = cfg.ble?.device_name || "";
    renderEventRows("OnConnect", cfg.events?.OnConnect);
    renderEventRows("OnDisconnect", cfg.events?.OnDisconnect);
    renderEventRows("Active", cfg.events?.Active);
    renderEventRows("Idle", cfg.events?.Idle);
  }

  function renderCommands(names) {
    commandsEl.innerHTML = "";
    if (!names || names.length === 0) {
      commandsEl.innerHTML = '<p class="hint">No saved commands (connect to load).</p>';
      return;
    }
    names.forEach((name) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cmd-btn";
      btn.textContent = name;
      btn.addEventListener("click", () => sendCommand(name, btn));
      commandsEl.appendChild(btn);
    });
  }

  async function api(path, options) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
      ...options,
    });
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { error: text };
    }
    if (!res.ok) {
      const msg = (data && (data.error || data.message)) || text || res.statusText;
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return data;
  }

  async function pollStatus() {
    try {
      const s = await api("/api/status");
      renderStatus(s);
      appendActivity(s.events);
      if (s.connected && !commandsLoaded) {
        await loadCommands();
      }
      if (!s.connected) {
        commandsLoaded = false;
      }
    } catch (e) {
      connPill.dataset.state = "disconnected";
      connLabel.textContent = "UI offline";
      errorEl.hidden = false;
      errorEl.textContent = String(e.message || e);
    }
  }

  async function loadCommands() {
    try {
      const data = await api("/api/commands");
      renderCommands(data.commands || []);
      commandsLoaded = true;
    } catch {
      renderCommands([]);
    }
  }

  async function loadConfig() {
    const cfg = await api("/api/config");
    renderConfig(cfg);
  }

  async function sendCommand(name, btn) {
    if (btn) btn.disabled = true;
    try {
      const result = await api("/api/command", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      renderStatus(result);
      appendActivity(result.events);
    } catch (e) {
      setMsg(String(e.message || e), "err");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  btnReconnect.addEventListener("click", async () => {
    btnReconnect.disabled = true;
    try {
      const result = await api("/api/reconnect", { method: "POST", body: "{}" });
      renderStatus(result);
      appendActivity(result.events);
      if (result.connected) {
        await loadCommands();
      }
    } catch (e) {
      errorEl.hidden = false;
      errorEl.textContent = String(e.message || e);
    }
  });

  document.querySelectorAll("[data-add]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.getAttribute("data-add");
      EVENT_CONTAINERS[key].appendChild(
        specRow(
          { NamedCommand: "", Delay: 0 },
          { canRemove: true, eventKey: key }
        )
      );
    });
  });

  configForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    setMsg("Saving…");
    const payload = {
      ble: { device_name: deviceNameInput.value.trim() },
      events: {
        OnConnect: readEventRows("OnConnect"),
        OnDisconnect: readEventRows("OnDisconnect"),
        Active: readEventRows("Active"),
        Idle: readEventRows("Idle"),
      },
    };
    try {
      const result = await api("/api/config", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      renderConfig(result.config);
      renderStatus(result);
      appendActivity(result.events);
      setMsg("Saved and applied.", "ok");
      if (result.connected) {
        await loadCommands();
      }
    } catch (e) {
      setMsg(String(e.message || e), "err");
    }
  });

  loadConfig().catch((e) => setMsg(String(e.message || e), "err"));
  pollStatus();
  setInterval(pollStatus, 1000);
})();
