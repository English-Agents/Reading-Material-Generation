import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import type { Generation, FeedbackSignal } from "../api/client";
import { approveGeneration, rejectGeneration } from "../api/client";
import FeedbackModal from "./FeedbackModal";

const PREVIEW_URL = "https://react-markdown-preview-web-alpha.earlywave.in/markdown-preview";

interface Props {
  gen: Generation;
  onUpdate: () => void;
}

const STATUS_COLOR: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  approved: "bg-green-100 text-green-700",
  rejected: "bg-red-100 text-red-700",
  needs_repair: "bg-orange-100 text-orange-700",
};

export default function GenerationCard({ gen, onUpdate }: Props) {
  const [showFeedback, setShowFeedback] = useState(false);
  const [score, setScore] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (!gen.output_text) return;
    await navigator.clipboard.writeText(gen.output_text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleApprove = async () => {
    setLoading(true);
    try {
      await approveGeneration(
        gen.generation_id,
        "reviewer",
        score ? parseFloat(score) : undefined
      );
      onUpdate();
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async (signals: FeedbackSignal[]) => {
    setLoading(true);
    try {
      await rejectGeneration(gen.generation_id, "reviewer", signals);
      setShowFeedback(false);
      onUpdate();
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 px-5 py-3 border-b border-slate-100 bg-slate-50">
          <span className={`text-xs font-medium px-2.5 py-1 rounded-full ${STATUS_COLOR[gen.status] ?? "bg-slate-100 text-slate-600"}`}>
            {gen.status}
          </span>
          {gen.eval_score !== null && gen.eval_score !== undefined && (
            <span className="text-xs text-slate-500">
              G-Eval score: <strong>{gen.eval_score.toFixed(2)}</strong>
            </span>
          )}
          {gen.token_cost_usd !== null && gen.token_cost_usd !== undefined && (
            <span className="text-xs text-slate-400">${gen.token_cost_usd.toFixed(4)}</span>
          )}

          {/* Toolbar — right side */}
          <div className="ml-auto flex items-center gap-2">
            {gen.output_text && (
              <button
                onClick={handleCopy}
                title="Copy markdown to clipboard"
                className="px-3 py-1 text-xs border border-slate-300 rounded-lg text-slate-600 hover:bg-slate-100 transition-colors"
              >
                {copied ? "✓ Copied" : "Copy MD"}
              </button>
            )}
            <a
              href={PREVIEW_URL}
              target="_blank"
              rel="noopener noreferrer"
              title="Open markdown preview tool"
              className="px-3 py-1 text-xs border border-indigo-300 text-indigo-600 rounded-lg hover:bg-indigo-50 transition-colors"
            >
              Open preview ↗
            </a>
          </div>
        </div>

        {/* Reading material */}
        <div className="p-6 prose prose-slate max-w-none text-sm overflow-y-auto max-h-[70vh]
                        prose-headings:font-semibold prose-h2:text-lg prose-h3:text-base
                        prose-details:border prose-details:border-slate-200
                        prose-details:rounded-lg prose-details:p-3 prose-details:mb-2
                        prose-summary:cursor-pointer prose-summary:font-medium
                        prose-blockquote:border-l-4 prose-blockquote:border-indigo-300
                        prose-blockquote:bg-indigo-50 prose-blockquote:not-italic
                        prose-blockquote:px-4 prose-blockquote:py-1 prose-blockquote:rounded-r-lg">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeRaw]}
          >
            {gen.output_text ?? "_No output yet_"}
          </ReactMarkdown>
        </div>

        {/* Actions */}
        {gen.status === "pending" && (
          <div className="flex items-center gap-3 px-5 py-3 border-t border-slate-100 bg-slate-50">
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={score}
              onChange={(e) => setScore(e.target.value)}
              placeholder="Override score 0–1 (optional)"
              className="w-52 border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
            />
            <button
              onClick={handleApprove}
              disabled={loading}
              className="px-5 py-1.5 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50"
            >
              ✓ Approve
            </button>
            <button
              onClick={() => setShowFeedback(true)}
              disabled={loading}
              className="px-5 py-1.5 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50"
            >
              ✗ Reject
            </button>
          </div>
        )}
      </div>

      {showFeedback && (
        <FeedbackModal
          onSubmit={handleReject}
          onCancel={() => setShowFeedback(false)}
        />
      )}
    </>
  );
}
