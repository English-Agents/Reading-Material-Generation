import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { addSourcePassage } from "../api/client";

interface Props {
  deckId: string;
}

const EMPTY = {
  topic_label: "",
  passage_text: "",
  source_title: "",
  page_ref: "",
  author: "",
};

export default function PassageForm({ deckId }: Props) {
  const qc = useQueryClient();
  const [form, setForm] = useState(EMPTY);
  const [open, setOpen] = useState(false);

  const mutation = useMutation({
    mutationFn: () =>
      addSourcePassage(deckId, {
        topic_label: form.topic_label,
        passage_text: form.passage_text,
        source_title: form.source_title || undefined,
        page_ref: form.page_ref || undefined,
        author: form.author || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["source-passages", deckId] });
      setForm(EMPTY);
      setOpen(false);
    },
  });

  const charsLeft = 2000 - form.passage_text.length;
  const canSubmit =
    form.topic_label.trim().length > 0 &&
    form.passage_text.trim().length >= 50 &&
    !mutation.isPending;

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="w-full border-2 border-dashed border-slate-300 hover:border-indigo-400 rounded-xl py-4 text-slate-500 hover:text-indigo-600 text-sm font-medium transition-colors"
      >
        + Add reference passage
      </button>
    );
  }

  return (
    <div className="border border-slate-200 rounded-xl p-5 bg-slate-50 space-y-3">
      <h3 className="font-semibold text-slate-700 text-sm">New reference passage</h3>

      <input
        type="text"
        placeholder="Topic label (e.g. Subject–Verb Agreement)"
        value={form.topic_label}
        onChange={(e) => setForm((f) => ({ ...f, topic_label: e.target.value }))}
        className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
      />

      <div className="grid grid-cols-3 gap-2">
        <input
          type="text"
          placeholder="Book / source title"
          value={form.source_title}
          onChange={(e) => setForm((f) => ({ ...f, source_title: e.target.value }))}
          className="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
        <input
          type="text"
          placeholder="Page ref"
          value={form.page_ref}
          onChange={(e) => setForm((f) => ({ ...f, page_ref: e.target.value }))}
          className="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
        <input
          type="text"
          placeholder="Author"
          value={form.author}
          onChange={(e) => setForm((f) => ({ ...f, author: e.target.value }))}
          className="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
      </div>

      <div>
        <textarea
          rows={5}
          placeholder="Paste the passage text here (50–2000 characters)…"
          value={form.passage_text}
          onChange={(e) => setForm((f) => ({ ...f, passage_text: e.target.value }))}
          maxLength={2000}
          className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-none"
        />
        <p className={`text-xs mt-0.5 text-right ${charsLeft < 100 ? "text-red-500" : "text-slate-400"}`}>
          {charsLeft} chars remaining
        </p>
      </div>

      {mutation.isError && (
        <p className="text-red-600 text-xs">
          {(mutation.error as any)?.response?.data?.detail ?? "Failed to add passage."}
        </p>
      )}

      <div className="flex gap-2 justify-end">
        <button
          onClick={() => { setOpen(false); setForm(EMPTY); }}
          className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-200 rounded-lg"
        >
          Cancel
        </button>
        <button
          onClick={() => mutation.mutate()}
          disabled={!canSubmit}
          className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 font-medium"
        >
          {mutation.isPending ? "Saving…" : "Add passage"}
        </button>
      </div>
    </div>
  );
}
