import { useState } from 'react'
import api from '../lib/api'

export default function CtgSearchModal({ open, onClose, onSelect }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)

  if (!open) {
    return null
  }

  const search = async () => {
    if (!query.trim()) return
    setLoading(true)
    try {
      const res = await api.get('/ctg/search', { params: { q: query } })
      setResults(res.data)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-20 flex items-center justify-center bg-ink/40 p-4">
      <div className="w-full max-w-2xl rounded-2xl bg-white p-5 shadow-2xl">
        <h3 className="font-display text-xl">CTG Search</h3>
        <div className="mt-4 flex gap-2">
          <input
            className="w-full rounded-lg border border-slate-300 px-3 py-2"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search trial title or disease"
          />
          <button className="rounded-lg bg-ink px-4 py-2 text-white" onClick={search}>
            {loading ? 'Searching...' : 'Search'}
          </button>
        </div>
        <div className="mt-4 space-y-2">
          {results.map((r) => (
            <button
              key={r.nctId}
              className="w-full rounded-lg border border-slate-200 p-3 text-left hover:bg-slate-50"
              onClick={() => onSelect(r)}
            >
              <div className="font-semibold">{r.officialTitle || 'Untitled Trial'}</div>
              <div className="text-sm text-slate-600">
                {r.nctId} | {r.phase || 'N/A'} | {r.overallStatus || 'N/A'}
              </div>
            </button>
          ))}
        </div>
        <div className="mt-4 flex justify-between">
          <button className="text-sm text-slate-500 hover:text-slate-700" onClick={onClose}>
            Close
          </button>
          <button
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
            onClick={() => onSelect(null)}
          >
            Skip CTG Match
          </button>
        </div>
      </div>
    </div>
  )
}
