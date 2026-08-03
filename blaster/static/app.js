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
  const errorEl = $("error");
  const commandsEl = $("commands");
  const btnReconnect = $("btn-reconnect");
  const configForm = $("config-form");
  const configMsg = $("config-msg");
  const deviceNameInput = $("device_name_input");

  const EVENT_CONTAINERS = {
    OnConnect: $("onconnect-rows"),
    HeartbeatStopped: $("heartbeat-rows"),
    Active: $("active-rows"),
    Idle: $("idle-rows"),
  };

  let configCache = null;
  let commandsLoaded = false;

  function setMsg(text, kind) {
    configMsg.textContent = text || "";
    configMsg.className = "form-msg" + (kind ? ` ${kind}` : "");
  }

  function onOff(v) {
    return v ? "on" : "off";
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
    HeartbeatStopped: {
      delay: "Timeout (sec)",
      delayTitle: "Seconds without a heartbeat before the ESP32 runs this command",
      heartbeat: "Heartbeat interval (sec)",
      heartbeatTitle: "How often the Mac sends a heartbeat while connected",
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
    row.className = "event-row" + (opts.showHeartbeat ? " event-row-hb" : "");
    const showHb = !!opts.showHeartbeat;
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
      ${showHb ? `
      <label class="field">
        <span class="field-label">${escapeAttr(labels.heartbeat)}</span>
        <input type="number" data-field="HeartbeatInterval" min="0" step="1" value="${spec.HeartbeatInterval ?? ""}" title="${escapeAttr(labels.heartbeatTitle)}" aria-label="${escapeAttr(labels.heartbeat)}">
      </label>` : ""}
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

  function renderEventRows(key, specs) {
    const container = EVENT_CONTAINERS[key];
    container.innerHTML = "";
    const showHeartbeat = key === "HeartbeatStopped";
    const canRemove = key !== "HeartbeatStopped";
    (specs || []).forEach((spec) => {
      container.appendChild(specRow(spec, { showHeartbeat, canRemove, eventKey: key }));
    });
    if (!specs || specs.length === 0) {
      container.appendChild(
        specRow(
          { NamedCommand: "", Delay: key === "Idle" ? 120 : 0 },
          { showHeartbeat, canRemove, eventKey: key }
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
      if (key === "HeartbeatStopped") {
        const hbRaw = row.querySelector('[data-field="HeartbeatInterval"]').value;
        if (hbRaw !== "") {
          out.HeartbeatInterval = Number.parseInt(hbRaw, 10);
        }
      }
      return out;
    }).filter((s) => s.NamedCommand);
  }

  function renderConfig(cfg) {
    configCache = cfg;
    deviceNameInput.value = cfg.ble?.device_name || "";
    renderEventRows("OnConnect", cfg.events?.OnConnect);
    renderEventRows("HeartbeatStopped", cfg.events?.HeartbeatStopped);
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
          { showHeartbeat: false, canRemove: true, eventKey: key }
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
        HeartbeatStopped: readEventRows("HeartbeatStopped"),
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
