"use client";

import { useState } from "react";
import { sourceCaption } from "@/lib/result-presentation";

/** Short readable caption; the editable source and URL remain verbatim. */
export default function SourceField({ label, value, onChange, placeholder, required = false }: {
  label: string; value: string; onChange: (value: string) => void; placeholder: string; required?: boolean;
}) {
  const [open, setOpen] = useState(!value.trim());
  return <details className="provenance-details source-editor" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{label}<span className="source-caption">{sourceCaption(value)}</span></summary>
    <label className="field-label"><span>Исходное описание и ссылка · {label.toLocaleLowerCase("ru-RU")}</span>
      <input type="text" required={required} value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} />
    </label>
  </details>;
}
