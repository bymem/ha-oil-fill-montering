/**
 * Oil Tank sidebar panel - placeholder.
 *
 * Plain web component, no build step. Home Assistant sets `hass`, `narrow`
 * and `panel` on the element. Uses theme CSS variables so it follows
 * light/dark themes.
 */
class OilTankPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  set narrow(narrow) {
    this._narrow = narrow;
    this._render();
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    // Build the DOM once; later calls only pass fresh props to the menu button.
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
            min-height: 100vh;
            background: var(--primary-background-color);
            color: var(--primary-text-color);
          }
          .toolbar {
            display: flex;
            align-items: center;
            height: var(--header-height, 56px);
            padding: 0 12px;
            background: var(--app-header-background-color, var(--primary-color));
            color: var(--app-header-text-color, var(--text-primary-color));
            font-size: 20px;
          }
          .content {
            padding: 16px;
          }
          .card {
            max-width: 600px;
            padding: 16px;
            border-radius: var(--ha-card-border-radius, 12px);
            background: var(--card-background-color);
          }
        </style>
        <div class="toolbar">
          <ha-menu-button></ha-menu-button>
          <span>Oil tank</span>
        </div>
        <div class="content">
          <div class="card">Oil tank panel - coming soon.</div>
        </div>
      `;
    }

    // The menu button opens the sidebar on narrow (phone) layouts.
    const menuButton = this.shadowRoot.querySelector("ha-menu-button");
    menuButton.hass = this._hass;
    menuButton.narrow = this._narrow;
  }
}

customElements.define("oil-tank-panel", OilTankPanel);
