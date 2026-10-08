"use client";

import type { Area } from "@/lib/types";
import type { CustomerForm } from "@/lib/adminview";

/** The customer details form, used for both "new customer" and "edit". */
export function CustomerFormFields({ form, onChange, areas, editing }: {
  form: CustomerForm;
  onChange: (next: CustomerForm) => void;
  areas: Area[];
  editing?: boolean;
}) {
  const set = (key: keyof CustomerForm) => (e: { target: { value: string } }) => onChange({ ...form, [key]: e.target.value });
  const field = (label: string, key: keyof CustomerForm, opts: { placeholder?: string; urdu?: boolean; mode?: string } = {}) => (
    <div>
      <label className="small muted" htmlFor={`cf-${key}`}>{label}</label><br />
      <input id={`cf-${key}`} type="text" value={form[key]} placeholder={opts.placeholder} inputMode={opts.mode as never}
        className={opts.urdu ? "urdu" : undefined} onChange={set(key)} style={{ width: "100%" }} />
    </div>
  );
  return (
    <div className="grid">
      {field("Name *", "full_name")}
      {field("Name in Urdu", "full_name_ur", { urdu: true })}
      {field("Father's name", "father_name")}
      {field("Mobile", "mobile", { placeholder: "0300 1234567", mode: "tel" })}
      {field("WhatsApp", "whatsapp", { placeholder: "if different", mode: "tel" })}
      {field("Other contact", "alt_contact")}
      {field(editing ? "CNIC (leave empty to keep the saved one)" : "CNIC", "cnic", { placeholder: "35202-1234567-1" })}
      <div>
        <label className="small muted" htmlFor="cf-area">Area</label><br />
        <select id="cf-area" value={form.area_id} onChange={set("area_id")} style={{ width: "100%" }}>
          <option value="">No area</option>
          {areas.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
      </div>
      {field("House no", "house_no")}
      {field("Address", "address")}
      {field("Address in Urdu", "address_ur", { urdu: true })}
      {field("Notes", "notes")}
    </div>
  );
}
