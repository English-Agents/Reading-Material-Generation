import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listSourcePassages, deleteSourcePassage } from "../api/client";
import AlignmentBadge from "../components/AlignmentBadge";
import PassageForm from "../components/PassageForm";

export default function SourceContentPage() {
  const { deckId } = useParams<{ deckId: string }>();
  const qc = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["source-passages", deckId],
    queryFn: () => listSourcePassages(deckId!).then((r) => r.data),
    enabled: !!deckId,
  });

  const deleteMutation = useMutation({
    mutationFn: (passageId: string) => deleteSourcePassage(deckId!, passageId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["source-passages", deckId] }),
  });

  const budgetPct = data
    ? Math.round((data.total_chars / data.budget_chars) * 100)
    : 0;

  const budgetColor =
    budgetPct >= 90 ? "bg-red-500" : budgetPct >= 70 ? "bg-yellow-500" : "bg-green-500";

  return (
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Reference Passages</h1>
          <p className="text-slate-500 text-sm mt-1">
            Deck{" "}
            <code className="bg-slate-100 px-1.5 py-0.5 rounded text-xs">
              {deckId?.slice(0, 8)}…
            </code>
          </p>
        </div>
        <Link
          to={`/review/${deckId}`}
          className="text-sm text-indigo-600 hover:underline font-medium"
        >
          ← Back to review
        </Link>
      </div>

      {/* Budget bar */}
      {data && (
        <div className="mb-6 bg-white border border-slate-200 rounded-xl p-4">
          <div className="flex items-center justify-between text-sm mb-2">
            <span className="font-medium text-slate-700">Source budget</span>
            <span className="text-slate-500">
              {data.total_chars.toLocaleString()} / {data.budget_chars.toLocaleString()} chars
              &nbsp;·&nbsp;
              <span className={budgetPct >= 90 ? "text-red-600 font-semibold" : "text-slate-500"}>
                {data.budget_remaining.toLocaleString()} remaining
              </span>
            </span>
          </div>
          <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${budgetColor}`}
              style={{ width: `${Math.min(budgetPct, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Passage list */}
      {isLoading && (
        <p className="text-slate-400 text-sm text-center py-8">Loading passages…</p>
      )}

      {isError && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm mb-4">
          Failed to load passages.
        </div>
      )}

      {data && data.passages.length === 0 && !isLoading && (
        <p className="text-slate-400 text-sm text-center py-6 mb-4">
          No passages added yet. Add one below.
        </p>
      )}

      <div className="space-y-3 mb-6">
        {data?.passages.map((p) => (
          <div
            key={p.id}
            className="bg-white border border-slate-200 rounded-xl p-4 space-y-2"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-slate-800 text-sm">{p.topic_label}</span>
                  <AlignmentBadge
                    verdict={p.alignment_verdict as any}
                    score={p.alignment_score}
                    reason={p.alignment_reason}
                  />
                </div>
                {(p.source_title || p.author || p.page_ref) && (
                  <p className="text-slate-400 text-xs mt-0.5">
                    {[p.source_title, p.author && `by ${p.author}`, p.page_ref && `p.${p.page_ref}`]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                )}
              </div>
              <button
                onClick={() => deleteMutation.mutate(p.id)}
                disabled={deleteMutation.isPending}
                title="Remove passage"
                className="text-slate-300 hover:text-red-500 transition-colors text-lg leading-none disabled:opacity-40"
              >
                ×
              </button>
            </div>

            <p className="text-slate-600 text-sm leading-relaxed line-clamp-3">
              {p.passage_text}
            </p>

            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>{p.char_count.toLocaleString()} chars</span>
              {p.alignment_reason && (
                <span className="italic truncate max-w-xs" title={p.alignment_reason}>
                  {p.alignment_reason}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Add passage form */}
      {deckId && <PassageForm deckId={deckId} />}
    </div>
  );
}
