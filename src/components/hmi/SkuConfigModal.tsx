import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { apiFetch } from "@/lib/usePolledJson";

export type Sku = {
  skuCode: string;
  skuName: string;
  productColor: string | null;
  soapsPerBar: number | null;
  soapWeightG: number | null;
  longBarWeightG: number | null;
  barKg: number | null;
  soapKg: number | null;
  fringeKg: number | null;
};

export type SkuConfig = {
  activeSku: string | null;
  skus: Sku[];
};

type FormState = {
  skuCode: string;
  skuName: string;
  productColor: string;
  soapsPerBar: string;
  soapWeightG: string;
  longBarWeightG: string;
};

const EMPTY_FORM: FormState = {
  skuCode: "",
  skuName: "",
  productColor: "",
  soapsPerBar: "",
  soapWeightG: "",
  longBarWeightG: "",
};

const NUMBER_FIELDS: { key: keyof FormState; label: string; unit: string; integer?: boolean }[] = [
  { key: "soapsPerBar", label: "Soaps per Bar", unit: "nos", integer: true },
  { key: "soapWeightG", label: "Soap Weight", unit: "g" },
  { key: "longBarWeightG", label: "Long Bar Weight", unit: "g" },
];

function skuToForm(sku: Sku): FormState {
  return {
    skuCode: sku.skuCode,
    skuName: sku.skuName,
    productColor: sku.productColor ?? "",
    soapsPerBar: sku.soapsPerBar?.toString() ?? "",
    soapWeightG: sku.soapWeightG?.toString() ?? "",
    longBarWeightG: sku.longBarWeightG?.toString() ?? "",
  };
}

function numOrNull(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

export function SkuConfigModal({ onClose }: { onClose: () => void }) {
  const [config, setConfig] = useState<SkuConfig>({ activeSku: null, skus: [] });
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  async function loadConfig() {
    try {
      const res = await apiFetch("/api/sku-config");
      if (res.ok) setConfig((await res.json()) as SkuConfig);
    } catch {
      // backend unreachable; list stays empty
    }
  }

  useEffect(() => {
    loadConfig();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function set(key: keyof FormState, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
    setNotice(null);
  }

  async function setActive(skuCode: string) {
    setSwitching(true);
    setNotice(null);
    try {
      const res = await apiFetch("/api/sku-config/active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skuCode }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { error?: string } | null;
        setNotice({ kind: "err", text: body?.error ?? `Switch failed (HTTP ${res.status}).` });
        return;
      }
      setNotice({ kind: "ok", text: `Active SKU set to "${skuCode}".` });
      await loadConfig();
    } catch {
      setNotice({ kind: "err", text: "Could not reach the server. Try again." });
    } finally {
      setSwitching(false);
    }
  }

  async function save() {
    if (!form.skuCode.trim() || !form.skuName.trim()) {
      setNotice({ kind: "err", text: "SKU code and SKU name are required." });
      return;
    }
    const soapsPerBar = numOrNull(form.soapsPerBar);
    const soapWeightG = numOrNull(form.soapWeightG);
    const longBarWeightG = numOrNull(form.longBarWeightG);
    if (soapsPerBar === null || soapWeightG === null || longBarWeightG === null) {
      setNotice({ kind: "err", text: "Soaps per bar, soap weight, and long bar weight are required." });
      return;
    }
    setSaving(true);
    setNotice(null);
    try {
      const res = await apiFetch("/api/sku-config/sku", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          skuCode: form.skuCode.trim(),
          skuName: form.skuName.trim(),
          productColor: form.productColor.trim() || null,
          soapsPerBar,
          soapWeightG,
          longBarWeightG,
        }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { error?: string } | null;
        setNotice({ kind: "err", text: body?.error ?? `Save failed (HTTP ${res.status}).` });
        return;
      }
      setNotice({ kind: "ok", text: `SKU "${form.skuCode.trim()}" saved.` });
      await loadConfig();
    } catch {
      setNotice({ kind: "err", text: "Could not reach the server. Try again." });
    } finally {
      setSaving(false);
    }
  }

  const activeSku = config.skus.find((s) => s.skuCode === config.activeSku) ?? null;

  return createPortal(
    <div className="hmi-modal-overlay" onClick={onClose}>
      <div
        className="hmi-modal"
        role="dialog"
        aria-modal="true"
        aria-label="SKU configurator"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="hmi-modal-head">
          <div>
            <h2 className="hmi-panel-title">SKU Configurator</h2>
            <div className="hmi-panel-sub">Product · Weights</div>
          </div>
          <button type="button" className="hmi-modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="hmi-form-grid">
          <label className="hmi-field hmi-field-wide">
            <span className="hmi-field-label">Active SKU</span>
            <select
              className="hmi-input"
              value={config.activeSku ?? ""}
              disabled={switching}
              onChange={(e) => {
                if (e.target.value) setActive(e.target.value);
              }}
            >
              {!config.activeSku ? <option value="">— none —</option> : null}
              {config.skus.map((s) => (
                <option key={s.skuCode} value={s.skuCode}>
                  {s.skuCode} · {s.skuName}
                  {s.productColor ? ` · ${s.productColor}` : ""}
                </option>
              ))}
            </select>
          </label>
          {activeSku ? (
            <div className="hmi-field hmi-field-wide hmi-field-readout">
              Currently running: <strong>{activeSku.skuCode}</strong> — {activeSku.skuName}
              {activeSku.productColor ? ` (${activeSku.productColor})` : ""}
            </div>
          ) : null}
        </div>

        <label className="hmi-field hmi-field-wide">
          <span className="hmi-field-label">Load / edit existing SKU</span>
          <select
            className="hmi-input"
            value=""
            onChange={(e) => {
              const sku = config.skus.find((s) => s.skuCode === e.target.value);
              if (sku) {
                setForm(skuToForm(sku));
                setNotice(null);
              }
            }}
          >
            <option value="">— New SKU —</option>
            {config.skus.map((s) => (
              <option key={s.skuCode} value={s.skuCode}>
                {s.skuCode} · {s.skuName}
              </option>
            ))}
          </select>
        </label>

        <div className="hmi-form-grid">
          <label className="hmi-field">
            <span className="hmi-field-label">SKU Code *</span>
            <input
              className="hmi-input"
              value={form.skuCode}
              onChange={(e) => set("skuCode", e.target.value)}
            />
          </label>
          <label className="hmi-field">
            <span className="hmi-field-label">SKU Name *</span>
            <input
              className="hmi-input"
              value={form.skuName}
              onChange={(e) => set("skuName", e.target.value)}
            />
          </label>
          <label className="hmi-field">
            <span className="hmi-field-label">Product Color</span>
            <input
              className="hmi-input"
              value={form.productColor}
              onChange={(e) => set("productColor", e.target.value)}
            />
          </label>
          {NUMBER_FIELDS.map((f) => (
            <label key={f.key} className="hmi-field">
              <span className="hmi-field-label">
                {f.label} <em className="hmi-field-unit">({f.unit})</em>
              </span>
              <input
                className="hmi-input"
                type="number"
                min="0"
                step={f.integer ? "1" : "any"}
                value={form[f.key]}
                onChange={(e) => set(f.key, e.target.value)}
              />
            </label>
          ))}
        </div>

        <footer className="hmi-modal-foot">
          {notice ? <div className={`hmi-modal-notice is-${notice.kind}`}>{notice.text}</div> : <span />}
          <div className="hmi-modal-actions">
            <button
              type="button"
              className="hmi-btn"
              onClick={() => {
                setForm(EMPTY_FORM);
                setNotice(null);
              }}
            >
              Clear
            </button>
            <button type="button" className="hmi-btn is-primary" onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save SKU"}
            </button>
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
