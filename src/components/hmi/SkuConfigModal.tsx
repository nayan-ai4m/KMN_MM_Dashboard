import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { apiFetch } from "@/lib/usePolledJson";

export type Sku = {
  skuCode: string;
  skuName: string;
  productColor: string | null;
  orificeTopBottomWidth: number | null;
  orificeHeight: number | null;
  orificeMiddleWidth: number | null;
  soapsPerBar: number | null;
  soapWeight: number | null;
  barWeight: number | null;
  updatedAt?: string | null;
};

type FormState = {
  skuCode: string;
  skuName: string;
  productColor: string;
  orificeTopBottomWidth: string;
  orificeHeight: string;
  orificeMiddleWidth: string;
  soapsPerBar: string;
  soapWeight: string;
  barWeight: string;
};

const EMPTY_FORM: FormState = {
  skuCode: "",
  skuName: "",
  productColor: "",
  orificeTopBottomWidth: "",
  orificeHeight: "",
  orificeMiddleWidth: "",
  soapsPerBar: "",
  soapWeight: "",
  barWeight: "",
};

const NUMBER_FIELDS: { key: keyof FormState; label: string; unit: string; integer?: boolean }[] = [
  { key: "orificeTopBottomWidth", label: "Orifice Top/Bottom Width", unit: "mm" },
  { key: "orificeHeight", label: "Orifice Height", unit: "mm" },
  { key: "orificeMiddleWidth", label: "Orifice Middle Width", unit: "mm" },
  { key: "soapsPerBar", label: "Soaps per Bar", unit: "nos", integer: true },
  { key: "soapWeight", label: "Soap Weight", unit: "g" },
  { key: "barWeight", label: "Bar Weight", unit: "g" },
];

function skuToForm(sku: Sku): FormState {
  return {
    skuCode: sku.skuCode,
    skuName: sku.skuName,
    productColor: sku.productColor ?? "",
    orificeTopBottomWidth: sku.orificeTopBottomWidth?.toString() ?? "",
    orificeHeight: sku.orificeHeight?.toString() ?? "",
    orificeMiddleWidth: sku.orificeMiddleWidth?.toString() ?? "",
    soapsPerBar: sku.soapsPerBar?.toString() ?? "",
    soapWeight: sku.soapWeight?.toString() ?? "",
    barWeight: sku.barWeight?.toString() ?? "",
  };
}

function numOrNull(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

export function SkuConfigModal({ onClose }: { onClose: () => void }) {
  const [skus, setSkus] = useState<Sku[]>([]);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  async function loadSkus() {
    try {
      const res = await apiFetch("/api/sku");
      if (res.ok) setSkus((await res.json()) as Sku[]);
    } catch {
      // backend unreachable; list stays empty
    }
  }

  useEffect(() => {
    loadSkus();
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

  async function save() {
    if (!form.skuCode.trim() || !form.skuName.trim()) {
      setNotice({ kind: "err", text: "SKU code and SKU name are required." });
      return;
    }
    setSaving(true);
    setNotice(null);
    try {
      const res = await apiFetch("/api/sku", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          skuCode: form.skuCode.trim(),
          skuName: form.skuName.trim(),
          productColor: form.productColor.trim() || null,
          orificeTopBottomWidth: numOrNull(form.orificeTopBottomWidth),
          orificeHeight: numOrNull(form.orificeHeight),
          orificeMiddleWidth: numOrNull(form.orificeMiddleWidth),
          soapsPerBar: numOrNull(form.soapsPerBar),
          soapWeight: numOrNull(form.soapWeight),
          barWeight: numOrNull(form.barWeight),
        }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { error?: string } | null;
        setNotice({ kind: "err", text: body?.error ?? `Save failed (HTTP ${res.status}).` });
        return;
      }
      setNotice({ kind: "ok", text: `SKU "${form.skuCode.trim()}" saved.` });
      await loadSkus();
    } catch {
      setNotice({ kind: "err", text: "Could not reach the server. Try again." });
    } finally {
      setSaving(false);
    }
  }

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
            <div className="hmi-panel-sub">Product · Orifice · Weights</div>
          </div>
          <button type="button" className="hmi-modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        {skus.length > 0 ? (
          <label className="hmi-field hmi-field-wide">
            <span className="hmi-field-label">Load existing SKU</span>
            <select
              className="hmi-input"
              value=""
              onChange={(e) => {
                const sku = skus.find((s) => s.skuCode === e.target.value);
                if (sku) {
                  setForm(skuToForm(sku));
                  setNotice(null);
                }
              }}
            >
              <option value="">— New SKU —</option>
              {skus.map((s) => (
                <option key={s.skuCode} value={s.skuCode}>
                  {s.skuCode} · {s.skuName}
                </option>
              ))}
            </select>
          </label>
        ) : null}

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
