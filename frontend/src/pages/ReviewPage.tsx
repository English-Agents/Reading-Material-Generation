import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listGenerations, exportDeck } from "../api/client";
import GenerationCard from "../components/GenerationCard";
import { useState } from "react";

export default function ReviewPage() {
  const { deckId } = useParams<{ deckId: string }>();
  const queryClient = useQueryClient();
  const [exporting, setExporting] = useState(false);

  // Fetch only the deck-level compiled reading material
  const { data: generations = [], isLoading } = useQuery({
    queryKey: ["deck-reading", deckId],
    queryFn: () =>
      listGenerations({
        deck_id: deckId,
        skill_type: "deck_reading",
        limit: 1,
      }).then((r) => r.data),
    enabled: !!deckId,
    refetchInterval: (query) => {
      const gens = query.state.data ?? [];
      const pending = gens.some((g) => g.status === "pending");
      return pending ? 3000 : false;
    },
  });

  const gen = generations[0] ?? null;

  const handleExport = async (format: string) => {
    if (!deckId) return;
    setExporting(true);
    try {
      const { data } = await exportDeck(deckId, format);
      const ext = format === "markdown" ? "md" : format;
      const url = URL.createObjectURL(new Blob([data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = `reading-material-${deckId.slice(0, 8)}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Reading Material Review</h1>
          <p className="text-slate-500 text-sm mt-1">
            Deck <code className="bg-slate-100 px-1.5 py-0.5 rounded text-xs">{deckId?.slice(0, 8)}…</code>
          </p>
        </div>

        <div className="flex items-center gap-2">
          {["markdown", "docx", "pdf"].map((fmt) => (
            <button
              key={fmt}
              onClick={() => handleExport(fmt)}
              disabled={exporting || gen?.status !== "approved"}
              className="px-3 py-1.5 text-sm border border-slate-300 rounded-lg text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            >
              ↓ {fmt.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="text-center py-24 text-slate-400">
          <div className="text-4xl mb-3">⏳</div>
          <p>Compiling reading material…</p>
        </div>
      ) : !gen ? (
        <div className="text-center py-24 text-slate-400">
          <div className="text-4xl mb-3">📭</div>
          <p>No reading material found for this deck.</p>
        </div>
      ) : (
        <GenerationCard
          gen={gen}
          onUpdate={() =>
            queryClient.invalidateQueries({ queryKey: ["deck-reading", deckId] })
          }
        />
      )}
    </div>
  );
}
