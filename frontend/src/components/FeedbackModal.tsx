import { useState } from "react";
import type { FeedbackSignal } from "../api/client";

const SIGNALS = [
  { value: "too_long", label: "Too long" },
  { value: "too_short", label: "Too short" },
  { value: "wrong_tone", label: "Wrong tone" },
  { value: "missing_example", label: "Missing example" },
  { value: "factual_error", label: "Factual error" },
  { value: "format_violation", label: "Format violation" },
  { value: "unclear_explanation", label: "Unclear explanation" },
  { value: "unnecessary_diagram", label: "Unnecessary diagram" },
  { value: "needs_diagram", label: "Needs diagram" },
];

interface Props {
  onSubmit: (signals: FeedbackSignal[], note: string) => void;
  onCancel: () => void;
}

export default function FeedbackModal({ onSubmit, onCancel }: Props) {
  const [selected, setSelected] = useState<Record<string, number>>({});
  const [note, setNote] = useState("");

  const toggle = (value: string) => {
    setSelected((prev) => {
      if (prev[value]) {
        const next = { ...prev };
        delete next[value];
        return next;
      }
      return { ...prev, [value]: 2 };
    });
  };

  const handleSubmit = () => {
    const signals: FeedbackSignal[] = Object.entries(selected).map(
      ([signal_type, severity]) => ({ signal_type, severity, reviewer_note: note })
    );
    onSubmit(signals, note);
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
        <h3 className="text-lg font-semibold text-slate-800 mb-4">
          Reject — select feedback signals
        </h3>

        <div className="grid grid-cols-2 gap-2 mb-4">
          {SIGNALS.map((s) => (
            <button
              key={s.value}
              onClick={() => toggle(s.value)}
              className={`text-left px-3 py-2 rounded-lg text-sm border transition-colors ${
                selected[s.value]
                  ? "bg-red-50 border-red-400 text-red-700 font-medium"
                  : "border-slate-200 text-slate-600 hover:bg-slate-50"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>

        {/* Severity adjusters for selected signals */}
        {Object.keys(selected).length > 0 && (
          <div className="mb-4 space-y-1">
            {Object.entries(selected).map(([sig, sev]) => (
              <div key={sig} className="flex items-center gap-2 text-sm">
                <span className="text-slate-600 flex-1">{sig}</span>
                {[1, 2, 3].map((v) => (
                  <button
                    key={v}
                    onClick={() => setSelected((p) => ({ ...p, [sig]: v }))}
                    className={`w-7 h-7 rounded-full text-xs font-bold border transition-colors ${
                      sev === v
                        ? "bg-red-500 text-white border-red-500"
                        : "border-slate-300 text-slate-400 hover:border-red-300"
                    }`}
                  >
                    {v}
                  </button>
                ))}
              </div>
            ))}
          </div>
        )}

        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Optional: reviewer note (used to generate a regression test case)"
          rows={3}
          className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-300 mb-4 resize-none"
        />

        <div className="flex gap-3 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 rounded-lg"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={Object.keys(selected).length === 0}
            className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 font-medium"
          >
            Reject
          </button>
        </div>
      </div>
    </div>
  );
}
