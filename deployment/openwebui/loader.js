(() => {
  const TARGET_MODEL_NAME = "PPT Master Service";
  const STORAGE_KEY = "owui_ppt_panel_config_v1";
  const STYLE_ID = "ppt-panel-root";

  const DEFAULTS = {
    enabled: true,
    collapsed: false,
    autoInject: true,
    confirmation_mode: "lite",
    target_audience: "管理层",
    use_case: "季度经营复盘",
    page_count: "10",
    style_objective: "general_consulting",
    language: "zh-CN",
    image_strategy: "ai_generation",
    color_hint: "深蓝+青色",
    canvas_format: "ppt169",
  };

  let state = loadState();
  let panel;
  let launcher;

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return { ...DEFAULTS };
      const parsed = JSON.parse(raw);
      return { ...DEFAULTS, ...parsed };
    } catch {
      return { ...DEFAULTS };
    }
  }

  function saveState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  function isVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function isPptContext() {
    const nodes = document.querySelectorAll("button, span, div, h1, h2, h3");
    for (const node of nodes) {
      const text = (node.textContent || "").trim();
      if (text === TARGET_MODEL_NAME && isVisible(node)) return true;
    }
    return false;
  }

  function getComposerTextarea() {
    const areas = Array.from(document.querySelectorAll("textarea")).filter(
      (el) => isVisible(el) && !el.disabled
    );
    if (!areas.length) return null;
    return areas[areas.length - 1];
  }

  function buildConfigBlock() {
    return [
      `确认模式: ${state.confirmation_mode}`,
      `受众: ${state.target_audience}`,
      `场景: ${state.use_case}`,
      `页数: ${state.page_count}`,
      `风格: ${state.style_objective}`,
      `语言: ${state.language}`,
      `图片策略: ${state.image_strategy}`,
      `配色: ${state.color_hint}`,
      `画幅: ${state.canvas_format}`,
    ].join("\n");
  }

  function hasConfigBlock(text) {
    return /确认模式\s*[:：]\s*(auto|lite|full)/i.test(text);
  }

  function injectConfigToComposer() {
    if (!state.enabled || !isPptContext()) return;
    const textarea = getComposerTextarea();
    if (!textarea) return;
    const current = textarea.value || "";
    if (hasConfigBlock(current)) return;
    const injected = `${buildConfigBlock()}\n\n${current}`.trim();
    textarea.value = injected;
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function syncFormToState() {
    if (!panel) return;
    panel.querySelectorAll("[data-field]").forEach((el) => {
      const key = el.getAttribute("data-field");
      if (!(key in state)) return;
      if (el.type === "checkbox") {
        state[key] = !!el.checked;
      } else {
        state[key] = (el.value || "").trim();
      }
    });
    saveState();
  }

  function fillFormFromState() {
    if (!panel) return;
    panel.querySelectorAll("[data-field]").forEach((el) => {
      const key = el.getAttribute("data-field");
      if (!(key in state)) return;
      if (el.type === "checkbox") {
        el.checked = !!state[key];
      } else {
        el.value = state[key] ?? "";
      }
    });
  }

  function createField(label, name, html) {
    return `<label class="ppt-panel-label">${label}<div class="ppt-panel-input">${html}</div></label>`;
  }

  function renderPanel() {
    if (document.getElementById(STYLE_ID)) return;

    panel = document.createElement("aside");
    panel.id = STYLE_ID;
    panel.innerHTML = `
      <div class="ppt-panel-card">
        <div class="ppt-panel-head">
          <div class="ppt-panel-head-main">
            <strong>PPT 配置面板</strong>
            <div class="ppt-panel-head-actions">
              <button type="button" id="ppt-panel-collapse" class="ppt-panel-mini-btn">折叠</button>
              <button type="button" id="ppt-panel-hide" class="ppt-panel-mini-btn">隐藏</button>
            </div>
          </div>
          <span class="ppt-panel-sub">仅对 ${TARGET_MODEL_NAME} 生效</span>
        </div>
        <div class="ppt-panel-body" id="ppt-panel-body">
          <div class="ppt-panel-grid">
          ${createField(
            "启用面板",
            "enabled",
            `<input data-field="enabled" type="checkbox" />`
          )}
          ${createField(
            "发送时自动附加",
            "autoInject",
            `<input data-field="autoInject" type="checkbox" />`
          )}
          ${createField(
            "确认模式",
            "confirmation_mode",
            `<select data-field="confirmation_mode">
              <option value="auto">auto（直接生成）</option>
              <option value="lite">lite（轻确认）</option>
              <option value="full">full（完整八项确认）</option>
            </select>`
          )}
          ${createField(
            "目标受众",
            "target_audience",
            `<input data-field="target_audience" placeholder="如：管理层" />`
          )}
          ${createField(
            "使用场景",
            "use_case",
            `<input data-field="use_case" placeholder="如：季度经营复盘" />`
          )}
          ${createField(
            "页数",
            "page_count",
            `<input data-field="page_count" type="number" min="1" max="30" />`
          )}
          ${createField(
            "风格",
            "style_objective",
            `<select data-field="style_objective">
              <option value="general_versatile">general_versatile（通用风）</option>
              <option value="general_consulting">general_consulting（通用咨询风）</option>
              <option value="top_consulting">top_consulting（顶级咨询风）</option>
            </select>`
          )}
          ${createField(
            "语言",
            "language",
            `<select data-field="language">
              <option value="zh-CN">zh-CN（中文）</option>
              <option value="en-US">en-US（英文）</option>
            </select>`
          )}
          ${createField(
            "图片策略",
            "image_strategy",
            `<select data-field="image_strategy">
              <option value="ai_generation">ai_generation（启用AI生图）</option>
              <option value="placeholder">placeholder（不用AI生图）</option>
            </select>`
          )}
          ${createField(
            "配色偏好",
            "color_hint",
            `<input data-field="color_hint" placeholder="如：深蓝+青色" />`
          )}
          ${createField(
            "画幅",
            "canvas_format",
            `<select data-field="canvas_format">
              <option value="ppt169">ppt169（16:9）</option>
              <option value="ppt43">ppt43（4:3）</option>
            </select>`
          )}
          </div>
          <div class="ppt-panel-actions">
            <button type="button" id="ppt-panel-apply">应用到输入框</button>
          </div>
          <details class="ppt-panel-help">
            <summary>附录：选项中文解释</summary>
            <ul>
              <li>确认模式：auto 直接生成；lite 缺关键项先追问；full 八项确认后需“确认生成”。</li>
              <li>目标受众：决定表达深度与措辞（管理层/一线/投资人等）。</li>
              <li>使用场景：决定结构侧重（复盘/汇报/培训/路演等）。</li>
              <li>页数：建议 6-16 页，过少信息不完整，过多容易冗长。</li>
              <li>风格：通用风更灵活，咨询风更结构化，顶级咨询风更克制。</li>
              <li>语言：控制整套文案的主语言。</li>
              <li>图片策略：ai_generation 会调用生图接口；placeholder 不调用生图。</li>
              <li>配色偏好：用于主题色倾向（如深蓝、青绿、黑金）。</li>
              <li>画幅：ppt169 为宽屏，ppt43 为传统投影比例。</li>
            </ul>
          </details>
        </div>
      </div>
    `;
    document.body.appendChild(panel);
    fillFormFromState();
    renderLauncher();
    applyCollapsedState();

    panel.addEventListener("change", () => syncFormToState());
    panel.addEventListener("input", () => syncFormToState());
    panel.querySelector("#ppt-panel-apply")?.addEventListener("click", () => {
      syncFormToState();
      injectConfigToComposer();
    });
    panel.querySelector("#ppt-panel-hide")?.addEventListener("click", () => {
      state.enabled = false;
      saveState();
      fillFormFromState();
      refreshVisibility();
    });
    panel.querySelector("#ppt-panel-collapse")?.addEventListener("click", () => {
      state.collapsed = !state.collapsed;
      saveState();
      applyCollapsedState();
    });

    document.addEventListener(
      "keydown",
      (e) => {
        if (!state.enabled || !state.autoInject || !isPptContext()) return;
        const target = e.target;
        if (!(target instanceof HTMLTextAreaElement)) return;
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
          injectConfigToComposer();
        }
      },
      true
    );

    document.addEventListener(
      "click",
      (e) => {
        if (!state.enabled || !state.autoInject || !isPptContext()) return;
        const btn = e.target && e.target.closest ? e.target.closest("button") : null;
        if (!btn) return;
        const submitLike =
          btn.getAttribute("type") === "submit" ||
          /send|发送/i.test((btn.textContent || "") + " " + (btn.getAttribute("aria-label") || ""));
        if (submitLike) injectConfigToComposer();
      },
      true
    );
  }

  function renderLauncher() {
    if (launcher) return;
    launcher = document.createElement("button");
    launcher.id = "ppt-panel-launcher";
    launcher.type = "button";
    launcher.textContent = "PPT 面板";
    launcher.addEventListener("click", () => {
      state.enabled = true;
      state.collapsed = false;
      saveState();
      fillFormFromState();
      applyCollapsedState();
      refreshVisibility();
    });
    document.body.appendChild(launcher);
  }

  function applyCollapsedState() {
    if (!panel) return;
    const body = panel.querySelector("#ppt-panel-body");
    const collapseBtn = panel.querySelector("#ppt-panel-collapse");
    if (!body || !collapseBtn) return;
    body.style.display = state.collapsed ? "none" : "block";
    collapseBtn.textContent = state.collapsed ? "展开" : "折叠";
  }

  function refreshVisibility() {
    if (!panel) return;
    const showInContext = isPptContext();
    if (launcher) {
      launcher.style.display = showInContext && !state.enabled ? "block" : "none";
    }
    if (!state.enabled) {
      panel.style.display = "none";
      return;
    }
    panel.style.display = showInContext ? "block" : "none";
  }

  function boot() {
    renderPanel();
    refreshVisibility();
    const mo = new MutationObserver(() => refreshVisibility());
    mo.observe(document.documentElement, { childList: true, subtree: true });
    setInterval(refreshVisibility, 1500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
