import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import Nav from '../components/Nav'
import { useAuth } from '../context/AuthContext'
import api from '../lib/api'

const trialStatusBadgeClass = {
  draft: 'bg-amber-100 text-amber-800',
  active: 'bg-emerald-100 text-emerald-800',
  archived: 'bg-slate-200 text-slate-700',
}

const extractionStatusBadgeClass = {
  processing: 'bg-sky-100 text-sky-800',
  ready: 'bg-emerald-100 text-emerald-800',
  needs_review: 'bg-amber-100 text-amber-800',
}

const canCreate = (role) => ['owner', 'pi', 'coordinator'].includes(role)

const truncateText = (value, maxLength = 72) => {
  if (!value) return ''
  if (value.length <= maxLength) return value
  return `${value.slice(0, maxLength)}...`
}

export default function Trials({ onLogout }) {
  const { user } = useAuth()
  const [trials, setTrials] = useState([])
  const [status, setStatus] = useState('')
  const [indication, setIndication] = useState('')
  const [showNew, setShowNew] = useState(false)
  const [newTrial, setNewTrial] = useState({ nickname: '', protocol: null })
  const [createBusy, setCreateBusy] = useState(false)
  const [createError, setCreateError] = useState('')
  const [createInfo, setCreateInfo] = useState('')

  if (!user) {
    return null
  }

  const load = async () => {
    const params = {}
    if (status) params.status = status
    if (indication) params.indication = indication
    const res = await api.get('/trials', { params })
    setTrials(res.data)
  }

  useEffect(() => {
    load()
  }, [status, indication])

  const rows = useMemo(() => trials, [trials])
  const hasProcessingRows = rows.some((trial) => trial.extraction_status === 'processing')

  useEffect(() => {
    if (!hasProcessingRows) return undefined
    const timer = window.setInterval(() => {
      load()
    }, 4000)
    return () => window.clearInterval(timer)
  }, [hasProcessingRows, status, indication])

  const closeNewModal = () => {
    setShowNew(false)
    setNewTrial({ nickname: '', protocol: null })
    setCreateError('')
  }

  const createTrial = async () => {
    const nickname = newTrial.nickname.trim()
    if (!nickname || !newTrial.protocol) {
      setCreateError('Nickname and protocol upload are required.')
      return
    }

    setCreateBusy(true)
    setCreateError('')
    try {
      const formData = new FormData()
      formData.append('nickname', nickname)
      formData.append('protocol', newTrial.protocol)

      await api.post('/trials/create-with-upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setCreateInfo('Trial created. Metadata extraction is processing.')
      closeNewModal()
      await load()
    } catch (err) {
      setCreateError(err.response?.data?.detail || 'Could not create trial.')
    } finally {
      setCreateBusy(false)
    }
  }

  return (
    <div>
      <Nav onLogout={onLogout} />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-display text-2xl">Trial Registry</h2>
          {canCreate(user.role) && (
            <button className="rounded-lg bg-ink px-4 py-2 text-sm text-white" onClick={() => setShowNew(true)}>
              New Trial
            </button>
          )}
        </div>

        {createInfo && (
          <div className="mb-4 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800">{createInfo}</div>
        )}

        <div className="mb-4 grid gap-2 md:grid-cols-3">
          <select className="rounded-lg border border-slate-300 px-3 py-2" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            <option value="draft">Draft</option>
            <option value="active">Active</option>
            <option value="archived">Archived</option>
          </select>
          <select
            className="rounded-lg border border-slate-300 px-3 py-2"
            value={indication}
            onChange={(e) => setIndication(e.target.value)}
          >
            <option value="">All indications</option>
            <option value="aml">AML</option>
            <option value="all">ALL</option>
            <option value="lymphoma">Lymphoma</option>
            <option value="mm">MM</option>
            <option value="transplant">Transplant</option>
            <option value="gvhd">GVHD</option>
          </select>
        </div>

        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-slate-600">
              <tr>
                <th className="px-4 py-3">Nickname</th>
                <th className="px-4 py-3">Trial Title</th>
                <th className="px-4 py-3">NCT ID</th>
                <th className="px-4 py-3">Indication</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Extraction</th>
                <th className="px-4 py-3">CTG Match</th>
                <th className="px-4 py-3">PI</th>
                <th className="px-4 py-3">Coordinator</th>
                <th className="px-4 py-3">Created</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((trial) => (
                <tr className="border-t border-slate-100" key={trial.id}>
                  <td className="px-4 py-3 font-medium">
                    <Link className="text-ink hover:underline" to={`/trials/${trial.id}`}>
                      {trial.nickname}
                    </Link>
                  </td>
                  <td className="max-w-md px-4 py-3 text-slate-700" title={trial.trial_title || ''}>
                    {trial.trial_title ? (
                      <div>
                        <div>{truncateText(trial.trial_title)}</div>
                        {trial.document_title && trial.document_title !== trial.trial_title && (
                          <div className="text-xs text-slate-500" title={trial.document_title}>
                            Doc: {truncateText(trial.document_title, 88)}
                          </div>
                        )}
                      </div>
                    ) : (
                      '-'
                    )}
                  </td>
                  <td className="px-4 py-3">{trial.nct_id || '-'}</td>
                  <td className="px-4 py-3">{trial.indication ? trial.indication.toUpperCase() : '-'}</td>
                  <td className="px-4 py-3">
                    <span className={`badge ${trialStatusBadgeClass[trial.status] || 'bg-slate-100'}`}>{trial.status}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`badge ${extractionStatusBadgeClass[trial.extraction_status] || 'bg-slate-100'}`}>
                      {trial.extraction_status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {typeof trial.ctg_match_confidence === 'number' ? (
                      <span className="badge bg-sky-100 text-sky-800">{trial.ctg_match_confidence.toFixed(2)}</span>
                    ) : (
                      '-'
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600">{trial.pi_id || '-'}</td>
                  <td className="px-4 py-3 text-xs text-slate-600">{trial.coordinator_id || '-'}</td>
                  <td className="px-4 py-3 text-slate-600">{new Date(trial.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <div className="p-6 text-sm text-slate-500">No trials found.</div>}
        </div>
      </main>

      {showNew && (
        <div className="fixed inset-0 z-20 flex items-center justify-center bg-ink/40 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-5 shadow-2xl">
            <h3 className="font-display text-xl">New Trial</h3>
            <div className="mt-4 grid gap-2">
              <input
                className="rounded-lg border border-slate-300 px-3 py-2"
                placeholder="Nickname"
                value={newTrial.nickname}
                onChange={(e) => setNewTrial((previous) => ({ ...previous, nickname: e.target.value }))}
              />
              <input
                className="rounded-lg border border-slate-300 px-3 py-2"
                type="file"
                accept=".pdf,.docx"
                onChange={(e) => setNewTrial((previous) => ({ ...previous, protocol: e.target.files?.[0] || null }))}
              />
              {newTrial.protocol && <p className="text-xs text-slate-500">{newTrial.protocol.name}</p>}
            </div>

            {createError && (
              <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                {createError}
              </div>
            )}

            <div className="mt-5 flex justify-between">
              <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm" onClick={closeNewModal} disabled={createBusy}>
                Cancel
              </button>
              <button
                className="rounded-lg bg-ink px-4 py-2 text-sm text-white disabled:opacity-50"
                onClick={createTrial}
                disabled={createBusy}
              >
                {createBusy ? 'Creating...' : 'Create Trial'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
