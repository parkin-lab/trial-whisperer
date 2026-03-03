import { useEffect, useState } from 'react'
import api from '../lib/api'

function parseBulletLines(answer) {
  if (!answer) return []
  return answer
    .split('\n')
    .map((line) => line.replace(/^\s*(?:[-*•]\s+|\d+[.)]\s+)/, '').trim())
    .filter(Boolean)
    .slice(0, 6)
}

export default function ProtocolQA({ trialId }) {
  const [statusData, setStatusData] = useState(null)
  const [statusError, setStatusError] = useState('')
  const [statusLoading, setStatusLoading] = useState(false)
  const [question, setQuestion] = useState('')
  const [mode, setMode] = useState('brief')
  const [history, setHistory] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const loadStatus = async () => {
    setStatusLoading(true)
    try {
      const res = await api.get(`/trials/${trialId}/qa/status`)
      setStatusData(res.data)
      setStatusError('')
    } catch (err) {
      setStatusData(null)
      setStatusError(err.response?.data?.detail || 'Could not load protocol indexing status.')
    } finally {
      setStatusLoading(false)
    }
  }

  useEffect(() => {
    setHistory([])
    setQuestion('')
    setError('')
    setMode('brief')
    loadStatus()
  }, [trialId])

  const ask = async () => {
    const prompt = question.trim()
    if (!prompt || busy) return

    setBusy(true)
    setError('')
    try {
      const res = await api.post(`/trials/${trialId}/qa`, {
        question: prompt,
        document_version: null,
        mode,
      })
      const data = res.data
      setHistory((prev) => [
        ...prev,
        {
          id: `${Date.now()}-${prev.length}`,
          question: prompt,
          answer: data.answer,
          sources: data.sources || [],
          embeddings_pending: Boolean(data.embeddings_pending),
          model: data.model || '',
          mode,
        },
      ])
      setQuestion('')

      if (data.embeddings_pending) {
        setError('Protocol is being indexed for search. This may take a few minutes.')
      }
      await loadStatus()
    } catch (err) {
      setError(err.response?.data?.detail || 'Protocol Q&A request failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        {statusLoading ? (
          <p className="text-sm text-slate-500">Checking protocol indexing status...</p>
        ) : statusError ? (
          <p className="text-sm text-rose-700">{statusError}</p>
        ) : statusData?.embeddings_pending ? (
          <p className="text-sm text-amber-800">Protocol is being indexed for search. This may take a few minutes.</p>
        ) : statusData?.embeddings_exist ? (
          <p className="text-sm text-emerald-800">Protocol indexed - {statusData.chunk_count} chunks ready</p>
        ) : (
          <p className="text-sm text-slate-600">No protocol embeddings available yet.</p>
        )}
      </div>

      <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
        {history.length === 0 ? (
          <div className="text-sm text-slate-500">Ask a protocol question to begin.</div>
        ) : (
          <div className="space-y-3">
            {history.map((item) => (
              <div className="space-y-2 rounded-lg border border-slate-200 p-3" key={item.id}>
                <div className="rounded-lg bg-fog p-2 text-sm text-slate-800">
                  <span className="font-semibold">Question:</span> {item.question}
                </div>
                <div className="text-sm text-slate-800">
                  <span className="font-semibold">Answer:</span>
                  {item.mode === 'brief' ? (
                    parseBulletLines(item.answer).length > 0 ? (
                      <ul className="mt-2 list-disc space-y-1 pl-5">
                        {parseBulletLines(item.answer).map((line, idx) => (
                          <li key={`${item.id}-${idx}`}>{line}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-1 whitespace-pre-wrap">
                        {item.answer || (item.embeddings_pending ? 'Protocol indexing is still in progress.' : 'No answer returned.')}
                      </p>
                    )
                  ) : (
                    <p className="mt-1 whitespace-pre-wrap">
                      {item.answer || (item.embeddings_pending ? 'Protocol indexing is still in progress.' : 'No answer returned.')}
                    </p>
                  )}
                </div>
                {item.sources.length > 0 && (
                  <details className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-sm">
                    <summary className="cursor-pointer font-medium text-slate-700">
                      Sources ({item.sources.length})
                    </summary>
                    <div className="mt-2 space-y-2">
                      {item.sources.map((source, index) => (
                        <div className="rounded bg-white p-2" key={`${item.id}-${source.chunk_index}-${index}`}>
                          <div className="text-xs text-slate-500">
                            Chunk {source.chunk_index} | similarity {(source.similarity * 100).toFixed(1)}%
                          </div>
                          <div className="mt-1 whitespace-pre-wrap text-xs text-slate-700">{source.chunk_text}</div>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>
      )}

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="mb-3 inline-flex rounded-lg border border-slate-300 p-1">
          {['brief', 'detailed'].map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setMode(value)}
              className={`rounded-md px-3 py-1 text-xs ${mode === value ? 'bg-ink text-white' : 'text-slate-700'}`}
            >
              {value === 'brief' ? 'Brief' : 'Detailed'}
            </button>
          ))}
        </div>
        <label className="text-sm font-medium text-slate-700" htmlFor="protocol-question">
          Ask about the current protocol
        </label>
        <textarea
          id="protocol-question"
          className="mt-2 h-28 w-full rounded-lg border border-slate-300 p-3 text-sm"
          disabled={busy}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="What is the washout period for prior immunotherapy?"
          value={question}
        />
        <div className="mt-3 flex justify-end">
          <button
            className="rounded-lg bg-ink px-4 py-2 text-sm text-white disabled:opacity-50"
            disabled={busy || !question.trim()}
            onClick={ask}
            type="button"
          >
            {busy ? 'Asking...' : 'Ask'}
          </button>
        </div>
      </div>

      <p className="text-xs text-slate-500">
        For informational use only. Eligibility decisions use the structured criteria engine only.
      </p>
    </div>
  )
}
