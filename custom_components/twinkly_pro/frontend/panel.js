/**
 * Twinkly Studio — Embedded Custom Web Panel for Home Assistant (Twinkly Pro)
 * Zero external runtime dependencies; communicates directly via Home Assistant WebSocket API.
 */

class TwinklyProPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._initialized = false;
    this._loading = false;
    this._statusMsg = "";
    this._statusType = "info";

    this._devices = [];
    this._presets = {};
    this._gallery = [];
    this._selectedEntryId = null;
    this._activeTab = "studio"; // "studio" | "gallery" | "playlist" | "groups"

    // Studio generator state
    this._genPreset = "rainbow_wave";
    this._genName = "Aurora Custom";
    this._genPrimary = "#ff007f";
    this._genSecondary = "#00e5ff";
    this._genTertiary = "#7c00ff";
    this._genSpeed = 1.0;
    this._genScale = 1.0;
    this._genFps = 24;
    this._genDuration = 6;
    this._orbitAngle = 0.0;
    this._autoRotate = true;

    // Playlist editor draft
    this._playlistDraft = [];
    this._playlistDirty = false;

    // Group builder state
    this._groupMasterId = "";
    this._groupSlaveIds = new Set();

    this._animFrameId = null;
    this._startTime = performance.now();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized && hass) {
      this._initialized = true;
      this._renderShell();
      this._fetchState();
      this._startVisualizerLoop();
    }
  }

  connectedCallback() {
    if (this._initialized && !this._animFrameId) {
      this._startVisualizerLoop();
    }
  }

  disconnectedCallback() {
    if (this._animFrameId) {
      cancelAnimationFrame(this._animFrameId);
      this._animFrameId = null;
    }
  }

  get _currentDevice() {
    if (!this._devices.length) return null;
    return (
      this._devices.find((d) => d.entry_id === this._selectedEntryId) ||
      this._devices[0]
    );
  }

  async _fetchState() {
    if (!this._hass) return;
    this._loading = true;
    this._updateStatus("Загрузка данных контроллеров Twinkly...", "info");
    try {
      const res = await this._hass.callWS({ type: "twinkly_pro/get_state" });
      this._devices = res.devices || [];
      this._presets = res.presets || {};
      this._gallery = res.gallery || [];

      if (this._devices.length && !this._selectedEntryId) {
        this._selectedEntryId = this._devices[0].entry_id;
        this._syncDraftFromDevice(this._devices[0]);
      } else if (this._currentDevice && !this._playlistDirty) {
        this._syncDraftFromDevice(this._currentDevice);
      }

      if (!this._groupMasterId && this._devices.length) {
        this._groupMasterId = this._devices[0].entry_id;
      }

      this._loading = false;
      this._updateStatus("Готово", "ok");
      this._renderContent();
    } catch (err) {
      this._loading = false;
      this._updateStatus(`Ошибка связи: ${err.message || err}`, "error");
      this._renderContent();
    }
  }

  _syncDraftFromDevice(dev) {
    if (!dev || !dev.playlist) return;
    this._playlistDraft = (dev.playlist.entries || []).map((e) => ({
      unique_id: e.unique_id,
      duration: e.duration || 30,
      name: e.name || "Effect",
    }));
    this._playlistDirty = false;
  }

  _updateStatus(msg, type = "info") {
    this._statusMsg = msg;
    this._statusType = type;
    const badge = this.shadowRoot?.querySelector("#status-pill");
    if (badge) {
      badge.textContent = msg;
      badge.className = `status-pill status-${type}`;
    }
  }

  async _callControl(action, payload = {}) {
    const dev = this._currentDevice;
    if (!dev || !this._hass) return;
    this._updateStatus(`Выполнение: ${action}...`, "info");
    try {
      const res = await this._hass.callWS({
        type: "twinkly_pro/control_device",
        entry_id: dev.entry_id,
        action,
        payload,
      });
      if (res && res.device) {
        this._replaceDevice(res.device);
      }
      this._updateStatus("Команда выполнена", "ok");
      this._renderContent();
    } catch (err) {
      this._updateStatus(`Ошибка: ${err.message || err}`, "error");
    }
  }

  async _applyStudioEffect(targetMode) {
    const dev = this._currentDevice;
    if (!dev || !this._hass) return;
    const actionLabel =
      targetMode === "rt"
        ? "Запуск Live UDP RT стриминга..."
        : "Компиляция 2D/3D кадров и запись во флеш-память...";
    this._updateStatus(actionLabel, "info");
    try {
      const res = await this._hass.callWS({
        type: "twinkly_pro/apply_effect",
        entry_id: dev.entry_id,
        target_mode: targetMode,
        preset: this._genPreset,
        name: this._genName || "Studio Effect",
        fps: Number(this._genFps),
        duration: Number(this._genDuration),
        params: {
          primary_color: this._genPrimary,
          secondary_color: this._genSecondary,
          tertiary_color: this._genTertiary,
          speed: Number(this._genSpeed),
          scale: Number(this._genScale),
        },
      });
      if (res && res.device) {
        this._replaceDevice(res.device);
      }
      this._updateStatus(
        targetMode === "rt"
          ? "Live UDP поток активен!"
          : `Эффект "${this._genName}" загружен в память гирлянды!`,
        "ok"
      );
      this._renderContent();
    } catch (err) {
      this._updateStatus(`Ошибка: ${err.message || err}`, "error");
    }
  }

  async _savePlaylist() {
    const dev = this._currentDevice;
    if (!dev || !this._hass) return;
    this._updateStatus("Сохранение плейлиста в контроллер...", "info");
    try {
      const res = await this._hass.callWS({
        type: "twinkly_pro/save_playlist",
        entry_id: dev.entry_id,
        entries: this._playlistDraft.map((item) => ({
          unique_id: item.unique_id,
          duration: Number(item.duration) || 30,
        })),
        activate: true,
      });
      if (res && res.device) {
        this._replaceDevice(res.device);
        this._syncDraftFromDevice(res.device);
      }
      this._updateStatus("Плейлист сохранён и запущен!", "ok");
      this._renderContent();
    } catch (err) {
      this._updateStatus(`Ошибка сохранения плейлиста: ${err.message || err}`, "error");
    }
  }

  async _configureGroup(disband = false) {
    if (!this._hass || !this._groupMasterId) return;
    const slaveIds = disband ? [] : Array.from(this._groupSlaveIds);
    this._updateStatus(
      disband ? "Роспуск синхрогруппы..." : "Синхронизация Master/Slave группы...",
      "info"
    );
    try {
      const res = await this._hass.callWS({
        type: "twinkly_pro/configure_group",
        master_entry_id: this._groupMasterId,
        slave_entry_ids: slaveIds,
      });
      if (res && res.devices) {
        this._devices = res.devices;
      }
      this._updateStatus(
        disband ? "Группа расформирована" : "Группа синхронизации успешно создана!",
        "ok"
      );
      this._renderContent();
    } catch (err) {
      this._updateStatus(`Ошибка группы: ${err.message || err}`, "error");
    }
  }

  _replaceDevice(updated) {
    const idx = this._devices.findIndex((d) => d.entry_id === updated.entry_id);
    if (idx >= 0) {
      this._devices[idx] = updated;
    }
  }

  // ---------------------------------------------------------------------------
  // 2D/3D Real-Time Canvas LED Preview Engine
  // ---------------------------------------------------------------------------

  _startVisualizerLoop() {
    const step = (now) => {
      this._drawLedCanvas(now);
      this._animFrameId = requestAnimationFrame(step);
    };
    this._animFrameId = requestAnimationFrame(step);
  }

  _hexToRgb(hex) {
    const clean = (hex || "#ff007f").replace("#", "");
    if (clean.length === 6) {
      return [
        parseInt(clean.slice(0, 2), 16) || 0,
        parseInt(clean.slice(2, 4), 16) || 0,
        parseInt(clean.slice(4, 6), 16) || 0,
      ];
    }
    return [255, 0, 127];
  }

  _hsvToRgb(h, s, v) {
    h = ((h % 1) + 1) % 1;
    const i = Math.floor(h * 6);
    const f = h * 6 - i;
    const p = v * (1 - s);
    const q = v * (1 - f * s);
    const t = v * (1 - (1 - f) * s);
    let r = 0, g = 0, b = 0;
    switch (i % 6) {
      case 0: r = v; g = t; b = p; break;
      case 1: r = q; g = v; b = p; break;
      case 2: r = p; g = v; b = t; break;
      case 3: r = p; g = q; b = v; break;
      case 4: r = t; g = p; b = v; break;
      case 5: r = v; g = p; b = q; break;
    }
    return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
  }

  _computeLedColor(idx, nx, ny, nz, phase) {
    const preset = this._genPreset;
    const speed = Number(this._genSpeed) || 1.0;
    const scale = Number(this._genScale) || 1.0;
    const t = phase * speed;
    const c1 = this._hexToRgb(this._genPrimary);
    const c2 = this._hexToRgb(this._genSecondary);
    const c3 = this._hexToRgb(this._genTertiary);

    const lerp = (a, b, u) => [
      Math.round(a[0] + (b[0] - a[0]) * u),
      Math.round(a[1] + (b[1] - a[1]) * u),
      Math.round(a[2] + (b[2] - a[2]) * u),
    ];

    if (preset === "rainbow_wave") {
      const hue = nx * 0.6 * scale + ny * 0.8 * scale + nz * 0.3 - t;
      return this._hsvToRgb(hue, 0.92, 1.0);
    }
    if (preset === "gradient_flow") {
      const w = 0.5 + 0.5 * Math.sin((ny * 3.5 * scale + nx * 1.5 * scale - t) * Math.PI * 2);
      return w < 0.5 ? lerp(c1, c2, w * 2) : lerp(c2, c3, (w - 0.5) * 2);
    }
    if (preset === "plasma_2d") {
      const v1 = Math.sin((nx * 4 * scale + t) * Math.PI * 2);
      const v2 = Math.sin((ny * 4 * scale - t * 0.8) * Math.PI * 2);
      const v3 = Math.sin(((nx + ny + nz) * 2.5 * scale + t * 0.5) * Math.PI * 2);
      const p = (v1 + v2 + v3) / 6 + 0.5;
      return this._hsvToRgb(p * 0.75 + t * 0.2, 0.9, 1.0);
    }
    if (preset === "sparkle_twinkle") {
      const seed = ((idx * 2654435761) >>> 0) / 0xffffffff;
      const lw = Math.sin((t * 1.5 + seed) * Math.PI * 2);
      const sp = Math.max(0, (lw - 0.72) / 0.28);
      const base = lerp(c1, [255, 255, 255], sp);
      const f = 0.25 + 0.75 * sp;
      return [Math.round(base[0] * f), Math.round(base[1] * f), Math.round(base[2] * f)];
    }
    if (preset === "fire_flame") {
      const flick = 0.5 + 0.5 * Math.sin((nx * 6 + ny * 3 - t * 3 + (idx % 7) * 0.4) * Math.PI * 2);
      const heat = Math.max(0, Math.min(1, 1 - ny * 0.85 + (flick - 0.5) * 0.35));
      return this._hsvToRgb(heat * 0.12, 1 - Math.max(0, (heat - 0.85) * 3), Math.min(1, heat * 1.25));
    }
    if (preset === "equalizer_bars") {
      const band = Math.floor(nx * 7.99);
      const freq = 1 + (band % 4) * 0.5;
      const barH = 0.2 + 0.75 * (0.5 + 0.5 * Math.sin((t * freq + band * 0.37) * Math.PI * 2));
      if (ny <= barH) return this._hsvToRgb(0.45 - ny * 0.45, 0.95, 1.0);
      if (Math.abs(ny - barH) < 0.06) return [255, 255, 255];
      return [15, 18, 34];
    }
    if (preset === "matrix_rain") {
      const col = Math.floor(nx * 12);
      const offset = ((col * 1597334677) & 0xffff) / 0xffff;
      const dropY = 1 - ((t * 1.2 + offset) % 1);
      const dist = ((ny - dropY) % 1 + 1) % 1;
      if (dist < 0.28) {
        const inten = 1 - dist / 0.28;
        return dist < 0.04 ? [200, 255, 200] : [0, Math.round(255 * inten), Math.round(60 * inten)];
      }
      return [4, 20, 8];
    }
    // aurora_borealis
    const curtain = Math.sin((nx * 2.5 * scale + nz * 1.5 + t * 0.7) * Math.PI * 2);
    const center = 0.5 + 0.25 * curtain;
    const glow = Math.max(0.1, 1 - Math.abs(ny - center) * 2.5);
    return this._hsvToRgb(0.38 + ny * 0.28 + 0.08 * curtain, 0.88, glow);
  }

  _drawLedCanvas(now) {
    const canvas = this.shadowRoot?.querySelector("#led-preview-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;

    ctx.fillStyle = "#0b0f19";
    ctx.fillRect(0, 0, w, h);

    const dev = this._currentDevice;
    const rawCoords = dev?.layout?.coordinates || [];
    if (!rawCoords.length) {
      ctx.fillStyle = "#64748b";
      ctx.font = "13px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Нет данных геометрии диодов", w / 2, h / 2);
      return;
    }

    if (this._autoRotate) {
      this._orbitAngle = ((now - this._startTime) * 0.0004) % (Math.PI * 2);
    }

    // Normalize coordinates
    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;
    let minZ = Infinity, maxZ = -Infinity;
    for (const c of rawCoords) {
      if (c.x < minX) minX = c.x;
      if (c.x > maxX) maxX = c.x;
      if (c.y < minY) minY = c.y;
      if (c.y > maxY) maxY = c.y;
      if (c.z < minZ) minZ = c.z;
      if (c.z > maxZ) maxZ = c.z;
    }
    const spanX = maxX - minX || 1;
    const spanY = maxY - minY || 1;
    const spanZ = maxZ - minZ || 1;

    const cosA = Math.cos(this._orbitAngle);
    const sinA = Math.sin(this._orbitAngle);
    const phase = (now - this._startTime) / 4000.0;
    const pad = 28;
    const drawW = w - pad * 2;
    const drawH = h - pad * 2;

    for (let i = 0; i < rawCoords.length; i++) {
      const c = rawCoords[i];
      const nx = (c.x - minX) / spanX;
      const ny = (c.y - minY) / spanY;
      const nz = (c.z - minZ) / spanZ;

      // Rotate around vertical Y axis
      const cx = nx - 0.5;
      const cz = nz - 0.5;
      const rx = cx * cosA - cz * sinA + 0.5;
      const rz = cx * sinA + cz * cosA + 0.5;

      const px = pad + rx * drawW;
      const py = h - pad - ny * drawH;
      const [r, g, b] = this._computeLedColor(i, nx, ny, nz, phase);
      const radius = 2.6 + rz * 1.8;

      ctx.beginPath();
      ctx.arc(px, py, radius, 0, Math.PI * 2);
      ctx.fillStyle = `rgb(${r}, ${g}, ${b})`;
      ctx.shadowColor = `rgba(${r}, ${g}, ${b}, 0.8)`;
      ctx.shadowBlur = 6;
      ctx.fill();
    }
    ctx.shadowBlur = 0;
  }

  // ---------------------------------------------------------------------------
  // UI Rendering
  // ---------------------------------------------------------------------------

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          min-height: 100vh;
          background: #0f172a;
          color: #f8fafc;
          font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          box-sizing: border-box;
        }
        .studio-wrap {
          max-width: 1400px;
          margin: 0 auto;
          padding: 20px 24px 48px;
        }
        .top-bar {
          display: flex;
          flex-wrap: wrap;
          justify-content: space-between;
          align-items: center;
          gap: 16px;
          padding-bottom: 18px;
          border-bottom: 1px solid #1e293b;
          margin-bottom: 20px;
        }
        .brand {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .brand-logo {
          width: 40px;
          height: 40px;
          border-radius: 12px;
          background: linear-gradient(135deg, #ec4899, #8b5cf6, #06b6d4);
          display: flex;
          align-items: center;
          justify-content: center;
          font-weight: 800;
          font-size: 20px;
        }
        .brand h1 {
          margin: 0;
          font-size: 22px;
          font-weight: 700;
          letter-spacing: -0.02em;
        }
        .brand p {
          margin: 2px 0 0;
          font-size: 12px;
          color: #94a3b8;
        }
        .status-pill {
          padding: 6px 14px;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 600;
          background: #1e293b;
          color: #cbd5e1;
        }
        .status-ok { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
        .status-error { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
        .status-info { background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); }

        .main-grid {
          display: grid;
          grid-template-columns: 360px 1fr;
          gap: 24px;
        }
        @media (max-width: 960px) {
          .main-grid { grid-template-columns: 1fr; }
        }

        .card {
          background: #1e293b;
          border: 1px solid #334155;
          border-radius: 16px;
          padding: 18px;
          margin-bottom: 18px;
        }
        .card-title {
          font-size: 14px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: #94a3b8;
          margin: 0 0 14px;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .device-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .device-item {
          padding: 12px;
          border-radius: 12px;
          background: #0f172a;
          border: 1px solid #334155;
          cursor: pointer;
          transition: all 0.15s ease;
        }
        .device-item.active {
          border-color: #38bdf8;
          background: rgba(56, 189, 248, 0.08);
        }
        .device-item-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          font-weight: 600;
          font-size: 14px;
        }
        .device-meta {
          font-size: 12px;
          color: #94a3b8;
          margin-top: 4px;
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }
        .badge {
          padding: 2px 8px;
          border-radius: 6px;
          font-size: 11px;
          font-weight: 600;
          background: #334155;
          color: #e2e8f0;
        }
        .badge-master { background: #7c3aed; color: #fff; }
        .badge-slave { background: #0284c7; color: #fff; }
        .badge-rt { background: #ec4899; color: #fff; }

        #led-preview-canvas {
          width: 100%;
          height: 300px;
          border-radius: 12px;
          border: 1px solid #334155;
          display: block;
        }

        .tabs {
          display: flex;
          gap: 8px;
          margin-bottom: 18px;
          flex-wrap: wrap;
        }
        .tab-btn {
          padding: 10px 18px;
          border-radius: 10px;
          border: 1px solid #334155;
          background: #1e293b;
          color: #cbd5e1;
          font-weight: 600;
          font-size: 13px;
          cursor: pointer;
        }
        .tab-btn.active {
          background: linear-gradient(135deg, #2563eb, #7c3aed);
          color: #ffffff;
          border-color: transparent;
        }

        .form-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 14px;
          margin-bottom: 16px;
        }
        .field {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .field label {
          font-size: 12px;
          color: #94a3b8;
          font-weight: 600;
        }
        .field input[type="text"],
        .field input[type="number"],
        .field select {
          padding: 9px 12px;
          border-radius: 8px;
          border: 1px solid #475569;
          background: #0f172a;
          color: #f8fafc;
          font-size: 13px;
        }
        .field input[type="color"] {
          width: 100%;
          height: 38px;
          border-radius: 8px;
          border: 1px solid #475569;
          background: #0f172a;
          cursor: pointer;
        }

        .btn-row {
          display: flex;
          gap: 10px;
          flex-wrap: wrap;
        }
        .btn {
          padding: 10px 16px;
          border-radius: 10px;
          border: none;
          font-weight: 600;
          font-size: 13px;
          cursor: pointer;
          background: #334155;
          color: #f8fafc;
          transition: opacity 0.15s;
        }
        .btn:hover { opacity: 0.9; }
        .btn-primary {
          background: linear-gradient(135deg, #ec4899, #8b5cf6);
          color: #fff;
        }
        .btn-accent {
          background: linear-gradient(135deg, #06b6d4, #2563eb);
          color: #fff;
        }
        .btn-danger {
          background: #dc2626;
          color: #fff;
        }
        .btn-sm {
          padding: 6px 10px;
          font-size: 12px;
          border-radius: 7px;
        }

        .gallery-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
          gap: 14px;
        }
        .gallery-card {
          background: #0f172a;
          border: 1px solid #334155;
          border-radius: 12px;
          padding: 14px;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          gap: 10px;
        }
        .swatch-row {
          display: flex;
          gap: 6px;
        }
        .swatch {
          width: 22px;
          height: 22px;
          border-radius: 6px;
          border: 1px solid rgba(255,255,255,0.2);
        }

        .playlist-table {
          width: 100%;
          border-collapse: collapse;
          margin-bottom: 14px;
        }
        .playlist-table th,
        .playlist-table td {
          text-align: left;
          padding: 10px 8px;
          border-bottom: 1px solid #334155;
          font-size: 13px;
        }
        .mem-bar {
          height: 10px;
          background: #0f172a;
          border-radius: 999px;
          overflow: hidden;
          margin: 8px 0 14px;
          border: 1px solid #334155;
        }
        .mem-fill {
          height: 100%;
          background: linear-gradient(90deg, #06b6d4, #8b5cf6);
        }
      </style>

      <div class="studio-wrap">
        <div class="top-bar">
          <div class="brand">
            <div class="brand-logo">✦</div>
            <div>
              <h1>Twinkly Studio Pro</h1>
              <p>Управление синхрогруппами, 2D/3D генератор эффектов, плейлисты и светомузыка</p>
            </div>
          </div>
          <div style="display:flex; gap:10px; align-items:center;">
            <span id="status-pill" class="status-pill status-info">Инициализация...</span>
            <button class="btn btn-sm" id="btn-refresh">↻ Обновить</button>
          </div>
        </div>

        <div id="studio-body"></div>
      </div>
    `;

    this.shadowRoot
      .querySelector("#btn-refresh")
      ?.addEventListener("click", () => this._fetchState());
  }

  _renderContent() {
    const container = this.shadowRoot?.querySelector("#studio-body");
    if (!container) return;

    const dev = this._currentDevice;
    if (!dev) {
      container.innerHTML = `
        <div class="card">
          <h3>Контроллеры Twinkly ещё не добавлены</h3>
          <p>Перейдите в <b>Настройки → Устройства и службы → Добавить интеграцию → Twinkly Pro</b> и укажите IP вашей гирлянды.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = `
      <div class="main-grid">
        <!-- Left column: Device selector, Quick Controls, and 3D LED Visualizer -->
        <div>
          <div class="card">
            <div class="card-title">
              <span>Контроллеры (${this._devices.length})</span>
            </div>
            <div class="device-list">
              ${this._devices
                .map((d) => {
                  const isSel = d.entry_id === dev.entry_id;
                  const role = d.sync?.mode || "none";
                  const roleBadge =
                    role === "master"
                      ? `<span class="badge badge-master">MASTER</span>`
                      : role === "slave"
                      ? `<span class="badge badge-slave">SLAVE</span>`
                      : `<span class="badge">Standalone</span>`;
                  return `
                    <div class="device-item ${isSel ? "active" : ""}" data-select-entry="${d.entry_id}">
                      <div class="device-item-header">
                        <span>${d.name || d.host}</span>
                        ${roleBadge}
                      </div>
                      <div class="device-meta">
                        <span>IP: ${d.host}</span>
                        <span>• ${d.number_of_led} ${d.led_profile}</span>
                        <span>• Режим: <b>${d.mode}</b></span>
                        ${d.is_rt_streaming ? `<span class="badge badge-rt">LIVE UDP</span>` : ""}
                      </div>
                    </div>
                  `;
                })
                .join("")}
            </div>
          </div>

          <div class="card">
            <div class="card-title">
              <span>3D/2D Маппинг (${dev.number_of_led} диодов, ${dev.layout?.source || "2d"})</span>
              <label style="font-size:11px; cursor:pointer;">
                <input type="checkbox" id="chk-autorotate" ${this._autoRotate ? "checked" : ""}/> Вращать 3D
              </label>
            </div>
            <canvas id="led-preview-canvas" width="340" height="300"></canvas>
            <div style="margin-top:12px;">
              <div class="field">
                <label>Яркость (${dev.brightness?.value ?? 100}%)</label>
                <input type="range" id="quick-bri" min="0" max="100" value="${dev.brightness?.value ?? 100}" />
              </div>
              <div class="btn-row" style="margin-top:10px;">
                ${["off", "color", "movie", "playlist", "music", "rt"]
                  .map(
                    (m) => `
                  <button class="btn btn-sm ${dev.mode === m ? "btn-accent" : ""}" data-quick-mode="${m}">
                    ${m.toUpperCase()}
                  </button>
                `
                  )
                  .join("")}
              </div>
            </div>
          </div>
        </div>

        <!-- Right column: Studio Tabs -->
        <div>
          <div class="tabs">
            <button class="tab-btn ${this._activeTab === "studio" ? "active" : ""}" data-tab="studio">
              ✦ Генератор 2D/3D Эффектов
            </button>
            <button class="tab-btn ${this._activeTab === "gallery" ? "active" : ""}" data-tab="gallery">
              ★ Галерея Пресетов (${this._gallery.length})
            </button>
            <button class="tab-btn ${this._activeTab === "playlist" ? "active" : ""}" data-tab="playlist">
              ☰ Плейлист и Память (${dev.movies?.items?.length || 0})
            </button>
            <button class="tab-btn ${this._activeTab === "groups" ? "active" : ""}" data-tab="groups">
              ⇄ Синхрогруппы и Музыка
            </button>
          </div>

          ${this._renderActiveTab(dev)}
        </div>
      </div>
    `;

    this._bindEvents(dev);
  }

  _renderActiveTab(dev) {
    if (this._activeTab === "studio") {
      return `
        <div class="card">
          <div class="card-title">
            <span>Визуальный конструктор эффекта под реальную геометрию диодов</span>
          </div>
          <div class="form-grid">
            <div class="field">
              <label>Алгоритм 2D/3D паттерна</label>
              <select id="gen-preset">
                ${Object.entries(this._presets)
                  .map(
                    ([k, label]) =>
                      `<option value="${k}" ${this._genPreset === k ? "selected" : ""}>${label}</option>`
                  )
                  .join("")}
              </select>
            </div>
            <div class="field">
              <label>Название эффекта (для записи в память)</label>
              <input type="text" id="gen-name" value="${this._genName}" maxlength="28" />
            </div>
            <div class="field">
              <label>Скорость анимации (${this._genSpeed}x)</label>
              <input type="range" id="gen-speed" min="0.2" max="3.0" step="0.1" value="${this._genSpeed}" />
            </div>
            <div class="field">
              <label>Масштаб волны (${this._genScale}x)</label>
              <input type="range" id="gen-scale" min="0.3" max="3.0" step="0.1" value="${this._genScale}" />
            </div>
            <div class="field">
              <label>Основной цвет</label>
              <input type="color" id="gen-c1" value="${this._genPrimary}" />
            </div>
            <div class="field">
              <label>Вторичный цвет</label>
              <input type="color" id="gen-c2" value="${this._genSecondary}" />
            </div>
            <div class="field">
              <label>Акцентный цвет</label>
              <input type="color" id="gen-c3" value="${this._genTertiary}" />
            </div>
            <div class="field">
              <label>Частота кадров (FPS) и Длительность цикла (с)</label>
              <div style="display:flex; gap:8px;">
                <input type="number" id="gen-fps" min="10" max="40" value="${this._genFps}" style="width:70px;" />
                <input type="number" id="gen-dur" min="2" max="20" value="${this._genDuration}" style="width:70px;" />
              </div>
            </div>
          </div>

          <div class="btn-row">
            <button class="btn btn-accent" id="btn-start-rt">
              ▶ Запустить Live UDP Stream (Порт 7777, без записи во флеш)
            </button>
            <button class="btn btn-primary" id="btn-upload-movie">
              ⬇ Скомпилировать .movie и загрузить в память гирлянды
            </button>
          </div>
        </div>
      `;
    }

    if (this._activeTab === "gallery") {
      return `
        <div class="card">
          <div class="card-title">
            <span>Готовая коллекция эффектов (адаптируется под ваши 2D/3D координаты)</span>
          </div>
          <div class="gallery-grid">
            ${this._gallery
              .map(
                (item) => `
              <div class="gallery-card">
                <div>
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <strong>${item.name}</strong>
                    <span class="badge">${item.category}</span>
                  </div>
                  <p style="font-size:12px; color:#94a3b8; margin:6px 0 10px;">
                    ${item.description}
                  </p>
                  <div class="swatch-row">
                    <span class="swatch" style="background:${item.params.primary_color}"></span>
                    <span class="swatch" style="background:${item.params.secondary_color}"></span>
                    <span class="swatch" style="background:${item.params.tertiary_color}"></span>
                  </div>
                </div>
                <div class="btn-row" style="margin-top:8px;">
                  <button class="btn btn-sm" data-gallery-preview="${item.id}">Предпросмотр</button>
                  <button class="btn btn-sm btn-accent" data-gallery-rt="${item.id}">Live UDP</button>
                  <button class="btn btn-sm btn-primary" data-gallery-upload="${item.id}">В память</button>
                </div>
              </div>
            `
              )
              .join("")}
          </div>
        </div>
      `;
    }

    if (this._activeTab === "playlist") {
      const cap = dev.movies?.max_capacity || 1;
      const avail = dev.movies?.available_frames || 0;
      const usedPct = Math.min(100, Math.max(0, Math.round(((cap - avail) / cap) * 100)));
      const movies = dev.movies?.items || [];

      return `
        <div class="card">
          <div class="card-title">
            <span>Флеш-память гирлянды (${movies.length} / ${dev.movies?.max_movies || 15} слотов)</span>
            <span>Свободно кадров: ${avail} из ${cap} (${100 - usedPct}%)</span>
          </div>
          <div class="mem-bar">
            <div class="mem-fill" style="width:${usedPct}%;"></div>
          </div>

          <div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:14px;">
            ${
              movies.length
                ? movies
                    .map(
                      (m) => `
                <div style="background:#0f172a; border:1px solid #334155; border-radius:10px; padding:8px 12px; display:flex; align-items:center; gap:8px;">
                  <span style="font-size:13px; font-weight:600;">#${m.id}: ${m.name}</span>
                  <span class="badge">${m.frames_number}f @ ${m.fps}fps</span>
                  <button class="btn btn-sm btn-accent" data-play-movie="${m.id}">▶</button>
                  <button class="btn btn-sm" data-add-to-playlist="${m.unique_id}" data-movie-name="${m.name}">+ В очередь</button>
                </div>
              `
                    )
                    .join("")
                : `<span style="color:#94a3b8; font-size:13px;">В памяти гирлянды пока нет загруженных роликов. Загрузите их из вкладки «Генератор» или «Галерея».</span>`
            }
          </div>
        </div>

        <div class="card">
          <div class="card-title">
            <span>Редактор очереди воспроизведения (Плейлист)</span>
            <button class="btn btn-sm btn-primary" id="btn-save-playlist">
              💾 Записать плейлист в гирлянду и запустить
            </button>
          </div>
          ${
            this._playlistDraft.length
              ? `
            <table class="playlist-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Эффект (Movie)</th>
                  <th>Длительность (сек)</th>
                  <th>Порядок / Удаление</th>
                </tr>
              </thead>
              <tbody>
                ${this._playlistDraft
                  .map(
                    (item, idx) => `
                  <tr>
                    <td>${idx + 1}</td>
                    <td><b>${item.name}</b> <span style="color:#64748b; font-size:11px;">(${item.unique_id.slice(0, 8)})</span></td>
                    <td>
                      <input type="number" min="3" max="3600" value="${item.duration}" data-pl-dur="${idx}"
                        style="width:80px; padding:5px 8px; border-radius:6px; background:#0f172a; color:#fff; border:1px solid #475569;" />
                    </td>
                    <td>
                      <button class="btn btn-sm" data-pl-up="${idx}">↑</button>
                      <button class="btn btn-sm" data-pl-down="${idx}">↓</button>
                      <button class="btn btn-sm btn-danger" data-pl-del="${idx}">✕</button>
                    </td>
                  </tr>
                `
                  )
                  .join("")}
              </tbody>
            </table>
          `
              : `<p style="color:#94a3b8; font-size:13px;">Очередь плейлиста пуста. Нажмите «+ В очередь» на любом эффекте выше.</p>`
          }
        </div>
      `;
    }

    // Groups & Music tab
    const drivers = dev.music?.drivers || [];
    return `
      <div class="card">
        <div class="card-title">
          <span>Конструктор синхрогрупп (Master / Slave Sync)</span>
        </div>
        <p style="font-size:13px; color:#94a3b8; margin-top:0;">
          Когда гирлянды объединены в группу, Twinkly Pro автоматически маршрутизирует все команды (яркость, цвет, эффекты, плейлисты) через <b>Master</b>-контроллер, исключая рассинхрон.
        </p>
        <div class="form-grid">
          <div class="field">
            <label>Выберите Master-контроллер (ведущий)</label>
            <select id="grp-master">
              ${this._devices
                .map(
                  (d) =>
                    `<option value="${d.entry_id}" ${
                      this._groupMasterId === d.entry_id ? "selected" : ""
                    }>${d.name} (${d.host}, ${d.number_of_led} LED)</option>`
                )
                .join("")}
            </select>
          </div>
          <div class="field">
            <label>Ведомые гирлянды (Slaves)</label>
            <div style="display:flex; flex-direction:column; gap:6px; background:#0f172a; padding:10px; border-radius:8px; border:1px solid #334155;">
              ${this._devices
                .filter((d) => d.entry_id !== this._groupMasterId)
                .map(
                  (d) => `
                  <label style="display:flex; align-items:center; gap:8px; color:#f8fafc; cursor:pointer;">
                    <input type="checkbox" value="${d.entry_id}" class="chk-slave" ${
                      this._groupSlaveIds.has(d.entry_id) ? "checked" : ""
                    } />
                    ${d.name} (${d.host}) — текущая роль: <b>${d.sync?.mode || "none"}</b>
                  </label>
                `
                )
                .join("") || `<span style="color:#64748b; font-size:12px;">Добавьте вторую гирлянду в интеграцию для создания группы</span>`}
            </div>
          </div>
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" id="btn-create-group">
            🔗 Объединить выбранные гирлянды в синхрогруппу
          </button>
          <button class="btn btn-danger" id="btn-disband-group">
            ✕ Расформировать группу (перевести в Standalone)
          </button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">
          <span>Twinkly Music & Реактивный звук</span>
        </div>
        <div class="btn-row" style="margin-bottom:14px;">
          <button class="btn btn-accent" id="btn-enable-music">
            🎵 Включить режим Twinkly Music
          </button>
          <button class="btn" id="btn-eq-udp">
            📊 Запустить UDP Эквалайзер (Live RT)
          </button>
        </div>
        ${
          drivers.length
            ? `
          <div style="display:flex; flex-wrap:wrap; gap:8px;">
            ${drivers
              .map(
                (dr) => `
              <button class="btn btn-sm ${
                dev.music?.current_driver_id === dr.id ? "btn-primary" : ""
              }" data-music-driver="${dr.id}" data-music-uid="${dr.unique_id}">
                #${dr.id + 1}: ${dr.name}
              </button>
            `
              )
              .join("")}
          </div>
        `
            : `<p style="font-size:12px; color:#94a3b8;">Музыкальные пресеты контроллера будут активированы при переключении в режим MUSIC.</p>`
        }
      </div>
    `;
  }

  _bindEvents(dev) {
    const root = this.shadowRoot;
    if (!root) return;

    // Device switching
    root.querySelectorAll("[data-select-entry]").forEach((el) => {
      el.addEventListener("click", () => {
        this._selectedEntryId = el.getAttribute("data-select-entry");
        this._syncDraftFromDevice(this._currentDevice);
        this._renderContent();
      });
    });

    // Auto-rotate checkbox
    root.querySelector("#chk-autorotate")?.addEventListener("change", (e) => {
      this._autoRotate = e.target.checked;
    });

    // Quick brightness
    root.querySelector("#quick-bri")?.addEventListener("change", (e) => {
      this._callControl("set_brightness", { value: Number(e.target.value) });
    });

    // Quick mode buttons
    root.querySelectorAll("[data-quick-mode]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._callControl("set_mode", { mode: btn.getAttribute("data-quick-mode") });
      });
    });

    // Tab buttons
    root.querySelectorAll("[data-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._activeTab = btn.getAttribute("data-tab");
        this._renderContent();
      });
    });

    // Studio Generator inputs
    root.querySelector("#gen-preset")?.addEventListener("change", (e) => {
      this._genPreset = e.target.value;
    });
    root.querySelector("#gen-name")?.addEventListener("input", (e) => {
      this._genName = e.target.value;
    });
    root.querySelector("#gen-speed")?.addEventListener("input", (e) => {
      this._genSpeed = parseFloat(e.target.value);
      this._renderContent();
    });
    root.querySelector("#gen-scale")?.addEventListener("input", (e) => {
      this._genScale = parseFloat(e.target.value);
      this._renderContent();
    });
    root.querySelector("#gen-c1")?.addEventListener("input", (e) => {
      this._genPrimary = e.target.value;
    });
    root.querySelector("#gen-c2")?.addEventListener("input", (e) => {
      this._genSecondary = e.target.value;
    });
    root.querySelector("#gen-c3")?.addEventListener("input", (e) => {
      this._genTertiary = e.target.value;
    });
    root.querySelector("#gen-fps")?.addEventListener("change", (e) => {
      this._genFps = parseInt(e.target.value, 10) || 24;
    });
    root.querySelector("#gen-dur")?.addEventListener("change", (e) => {
      this._genDuration = parseInt(e.target.value, 10) || 6;
    });

    root.querySelector("#btn-start-rt")?.addEventListener("click", () => {
      this._applyStudioEffect("rt");
    });
    root.querySelector("#btn-upload-movie")?.addEventListener("click", () => {
      this._applyStudioEffect("upload");
    });

    // Gallery buttons
    const loadTemplateToGenerator = (tplId) => {
      const tpl = this._gallery.find((g) => g.id === tplId);
      if (!tpl) return null;
      this._genPreset = tpl.preset;
      this._genName = tpl.name;
      this._genFps = tpl.fps || 24;
      this._genDuration = tpl.duration || 6;
      this._genSpeed = tpl.params?.speed || 1.0;
      this._genScale = tpl.params?.scale || 1.0;
      this._genPrimary = tpl.params?.primary_color || "#ff007f";
      this._genSecondary = tpl.params?.secondary_color || "#00e5ff";
      this._genTertiary = tpl.params?.tertiary_color || "#7c00ff";
      return tpl;
    };

    root.querySelectorAll("[data-gallery-preview]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tpl = loadTemplateToGenerator(btn.getAttribute("data-gallery-preview"));
        if (tpl) {
          this._updateStatus(`Предпросмотр на 3D-маппинге: ${tpl.name}`, "info");
        }
      });
    });
    root.querySelectorAll("[data-gallery-rt]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (loadTemplateToGenerator(btn.getAttribute("data-gallery-rt"))) {
          this._applyStudioEffect("rt");
        }
      });
    });
    root.querySelectorAll("[data-gallery-upload]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (loadTemplateToGenerator(btn.getAttribute("data-gallery-upload"))) {
          this._applyStudioEffect("upload");
        }
      });
    });

    // Stored movies & Playlist actions
    root.querySelectorAll("[data-play-movie]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._callControl("select_movie", {
          movie_id: Number(btn.getAttribute("data-play-movie")),
        });
      });
    });
    root.querySelectorAll("[data-add-to-playlist]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._playlistDraft.push({
          unique_id: btn.getAttribute("data-add-to-playlist"),
          name: btn.getAttribute("data-movie-name") || "Effect",
          duration: 30,
        });
        this._playlistDirty = true;
        this._renderContent();
      });
    });
    root.querySelectorAll("[data-pl-dur]").forEach((inp) => {
      inp.addEventListener("change", (e) => {
        const idx = Number(inp.getAttribute("data-pl-dur"));
        if (this._playlistDraft[idx]) {
          this._playlistDraft[idx].duration = Math.max(3, Number(e.target.value) || 30);
          this._playlistDirty = true;
        }
      });
    });
    root.querySelectorAll("[data-pl-up]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.getAttribute("data-pl-up"));
        if (idx > 0) {
          const tmp = this._playlistDraft[idx - 1];
          this._playlistDraft[idx - 1] = this._playlistDraft[idx];
          this._playlistDraft[idx] = tmp;
          this._playlistDirty = true;
          this._renderContent();
        }
      });
    });
    root.querySelectorAll("[data-pl-down]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.getAttribute("data-pl-down"));
        if (idx < this._playlistDraft.length - 1) {
          const tmp = this._playlistDraft[idx + 1];
          this._playlistDraft[idx + 1] = this._playlistDraft[idx];
          this._playlistDraft[idx] = tmp;
          this._playlistDirty = true;
          this._renderContent();
        }
      });
    });
    root.querySelectorAll("[data-pl-del]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.getAttribute("data-pl-del"));
        this._playlistDraft.splice(idx, 1);
        this._playlistDirty = true;
        this._renderContent();
      });
    });
    root.querySelector("#btn-save-playlist")?.addEventListener("click", () => {
      this._savePlaylist();
    });

    // Groups & Music actions
    root.querySelector("#grp-master")?.addEventListener("change", (e) => {
      this._groupMasterId = e.target.value;
      this._groupSlaveIds.delete(this._groupMasterId);
      this._renderContent();
    });
    root.querySelectorAll(".chk-slave").forEach((chk) => {
      chk.addEventListener("change", (e) => {
        if (e.target.checked) {
          this._groupSlaveIds.add(e.target.value);
        } else {
          this._groupSlaveIds.delete(e.target.value);
        }
      });
    });
    root.querySelector("#btn-create-group")?.addEventListener("click", () => {
      this._configureGroup(false);
    });
    root.querySelector("#btn-disband-group")?.addEventListener("click", () => {
      this._configureGroup(true);
    });
    root.querySelector("#btn-enable-music")?.addEventListener("click", () => {
      this._callControl("set_mode", { mode: "music" });
    });
    root.querySelector("#btn-eq-udp")?.addEventListener("click", () => {
      this._genPreset = "equalizer_bars";
      this._applyStudioEffect("rt");
    });
    root.querySelectorAll("[data-music-driver]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._callControl("select_music_driver", {
          driver_id: Number(btn.getAttribute("data-music-driver")),
          unique_id: btn.getAttribute("data-music-uid") || "",
        });
      });
    });
  }
}

if (!customElements.get("twinkly-pro-panel")) {
  customElements.define("twinkly-pro-panel", TwinklyProPanel);
}
