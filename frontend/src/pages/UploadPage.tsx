import { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { generateFromFile, generateFromUrl } from "../api/client";

export default function UploadPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<"file" | "url">("file");
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    setError(null);
    setLoading(true);
    try {
      const { data } = await generateFromFile(file);
      navigate(`/review/${data.deck_id}`);
    } catch (e: any) {
      setError(e.response?.data?.detail ?? "Generation failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleUrl = async () => {
    if (!url.trim()) return;
    setError(null);
    setLoading(true);
    try {
      const { data } = await generateFromUrl(url.trim());
      navigate(`/review/${data.deck_id}`);
    } catch (e: any) {
      setError(e.response?.data?.detail ?? "Generation failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-xl mx-auto mt-12">
      <h1 className="text-3xl font-bold text-slate-800 mb-2">
        Generate Reading Material
      </h1>
      <p className="text-slate-500 mb-8">
        Upload a PowerPoint file or paste a Google Slides URL.
        One reading material document will be generated for the whole presentation.
      </p>

      {/* Tab switcher */}
      <div className="flex border border-slate-200 rounded-lg overflow-hidden mb-6">
        {(["file", "url"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-2 text-sm font-medium transition-colors ${
              tab === t
                ? "bg-indigo-600 text-white"
                : "bg-white text-slate-600 hover:bg-slate-50"
            }`}
          >
            {t === "file" ? "Upload PPTX" : "Google Slides URL"}
          </button>
        ))}
      </div>

      {tab === "file" ? (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const f = e.dataTransfer.files[0];
            if (f) handleFile(f);
          }}
          onClick={() => fileRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors ${
            dragOver
              ? "border-indigo-400 bg-indigo-50"
              : "border-slate-300 hover:border-indigo-400 hover:bg-slate-50"
          }`}
        >
          <div className="text-4xl mb-3">📄</div>
          <p className="text-slate-600 font-medium">
            Drop your .pptx file here or click to browse
          </p>
          <p className="text-slate-400 text-sm mt-1">Max 50 MB</p>
          <input
            ref={fileRef}
            type="file"
            accept=".pptx"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleFile(f);
            }}
          />
        </div>
      ) : (
        <div className="space-y-3">
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleUrl()}
            placeholder="https://docs.google.com/presentation/d/..."
            className="w-full border border-slate-300 rounded-lg px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
          <button
            onClick={handleUrl}
            disabled={loading || !url.trim()}
            className="w-full bg-indigo-600 text-white py-3 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            Generate
          </button>
        </div>
      )}

      {loading && (
        <div className="mt-6 flex items-center gap-3 text-indigo-600">
          <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
          </svg>
          <span className="text-sm">Generating reading material — this takes 20–40 seconds…</span>
        </div>
      )}

      {error && (
        <div className="mt-4 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
          {error}
        </div>
      )}
    </div>
  );
}
