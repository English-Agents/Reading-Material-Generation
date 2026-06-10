interface Props {
  verdict: "pass" | "warn" | "fail" | null;
  score: number | null;
  reason?: string | null;
}

const CONFIG = {
  pass: { bg: "bg-green-50", border: "border-green-300", text: "text-green-700", label: "Pass" },
  warn: { bg: "bg-yellow-50", border: "border-yellow-300", text: "text-yellow-700", label: "Warn" },
  fail: { bg: "bg-red-50", border: "border-red-300", text: "text-red-700", label: "Fail" },
};

export default function AlignmentBadge({ verdict, score, reason }: Props) {
  if (!verdict) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded border border-slate-200 bg-slate-50 text-slate-400 text-xs">
        Not scored
      </span>
    );
  }

  const c = CONFIG[verdict];
  return (
    <span
      title={reason ?? undefined}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-medium ${c.bg} ${c.border} ${c.text} cursor-default`}
    >
      {c.label}
      {score !== null && (
        <span className="opacity-70">({score.toFixed(2)})</span>
      )}
    </span>
  );
}
