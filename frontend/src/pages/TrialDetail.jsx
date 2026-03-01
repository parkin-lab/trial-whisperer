import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import Nav from '../components/Nav'
import ProtocolQA from '../components/ProtocolQA'
import UploadModal from '../components/UploadModal'
import api from '../lib/api'

const tabs = ['Overview', 'Documents', 'Criteria', 'Amendments', 'Q&A', 'Audit']

const confidenceClass = {
  high: 'bg-emerald-100 text-emerald-800',
  needs_review: 'bg-amber-100 text-amber-800',
}

const approvalClass = {
  approved: 'bg-emerald-100 text-emerald-800',
  pending: 'bg-slate-200 text-slate-700',
  manual: 'bg-amber-100 text-amber-800',
}

export default function TrialDetail({ user, onLogout }) {
  const { id } = useParams()
  const [activeTab, setActiveTab] = useState('Overview')
  const [trial, setTrial] = useState(null)
  const [documents, setDocuments] = useState([])
  const [amendments, setAmendments] = useState([])
  const [snapshots, setSnapshots] = useState([])
  const [criteria, setCriteria] = useState([])
  const [reviewStatus, setReviewStatus] = useState(null)
  const [criteriaError, setCriteriaError] = useState('')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [editTarget, setEditTarget] = useState(null)
  const [editExpression, setEditExpression] = useState('')
  const [editManualReview, setEditManualReview] = useState(false)
  const [criteriaBusy, setCriteriaBusy] = useState(false)
  const [auditEntries, setAuditEntries] = useState([])
  const [auditError, setAuditError] = useState('')
  const [auditBusy, setAuditBusy] = useState(false)
  const [expandedAudit, setExpandedAudit] = useState({})
  const [qaStatus, setQaStatus] = useState(null)

  const canUpload = ['owner', 'pi', 'coordinator'].includes(user.role)
  const canReview = ['owner', 'pi', 'coordinator'].includes(user.role)
  const canAudit = ['owner', 'coordinator'].includes(user.role)

  const loadTrialData = async () => {
    const [trialRes, docsRes, amendRes, snapshotRes] = await Promise.all([
      api.get(`/trials/${id}`),
      api.get(`/trials/${id}/documents`),
      api.get(`/trials/${id}/amendments`),
      api.get(`/trials/${id}/ctg-snapshot`),
    ])

    setTrial(trialRes.data)
    setDocuments(docsRes.data)
    setAmendments(amendRes.data)
    setSnapshots(snapshotRes.data ? [snapshotRes.data] : [])
  }

  const loadCriteria = async () => {
    try {
      const [criteriaRes, statusRes] = await Promise.all([
        api.get(`/trials/${id}/criteria`),
        api.get(`/trials/${id}/criteria/review-status`),
      ])
      setCriteria(criteriaRes.data)
      setReviewStatus(statusRes.data)
      setCriteriaError('')
    } catch (err) {
      setCriteria([])
      setReviewStatus(null)
      setCriteriaError(err.response?.data?.detail || 'Could not load criteria data.')
    }
  }

  const load = async () => {
    await Promise.all([loadTrialData(), loadCriteria(), loadQaStatus()])
  }

  const loadQaStatus = async () => {
    try {
      const res = await api.get(`/trials/${id}/qa/status`)
      setQaStatus(res.data)
    } catch {
      setQaStatus(null)
    }
  }

  useEffect(() => {
    load()
  }, [id])

  const parseCriteria = async () => {
    setCriteriaBusy(true)
    setCriteriaError('')
    try {
      await api.post(`/trials/${id}/criteria/parse`)
      await loadCriteria()
    } catch (err) {
      setCriteriaError(err.response?.data?.detail || 'Criteria parsing failed.')
    } finally {
      setCriteriaBusy(false)
    }
  }

  const approveCriterion = async (criterionId) => {
    setCriteriaBusy(true)
    setCriteriaError('')
    try {
      await api.post(`/trials/${id}/criteria/${criterionId}/approve`)
      await loadCriteria()
    } catch (err) {
      setCriteriaError(err.response?.data?.detail || 'Approve failed.')
    } finally {
      setCriteriaBusy(false)
    }
  }

  const approveAll = async () => {
    setCriteriaBusy(true)
    setCriteriaError('')
    try {
      await api.post(`/trials/${id}/criteria/approve-all`)
      await loadCriteria()
    } catch (err) {
      setCriteriaError(err.response?.data?.detail || 'Bulk approve failed.')
    } finally {
      setCriteriaBusy(false)
    }
  }

  const openEdit = (criterion) => {
    setEditTarget(criterion)
    setEditExpression(JSON.stringify(criterion.expression, null, 2))
    setEditManualReview(criterion.manual_review_required)
    setEditModalOpen(true)
  }

  const saveEdit = async () => {
    if (!editTarget) return

    let parsedExpression
    try {
      parsedExpression = JSON.parse(editExpression)
    } catch {
      setCriteriaError('Expression must be valid JSON.')
      return
    }

    setCriteriaBusy(true)
    setCriteriaError('')
    try {
      await api.patch(`/trials/${id}/criteria/${editTarget.id}`, {
        expression: parsedExpression,
        manual_review_required: editManualReview,
      })
      setEditModalOpen(false)
      setEditTarget(null)
      await loadCriteria()
    } catch (err) {
      setCriteriaError(err.response?.data?.detail || 'Could not save criterion changes.')
    } finally {
      setCriteriaBusy(false)
    }
  }

  const loadAudit = async () => {
    if (!canAudit) return

    setAuditBusy(true)
    setAuditError('')
    try {
      const res = await api.get('/audit', { params: { trial_id: id, limit: 200, offset: 0 } })
      setAuditEntries(res.data.items || [])
    } catch (err) {
      setAuditEntries([])
      setAuditError(err.response?.data?.detail || 'Could not load trial audit.')
    } finally {
      setAuditBusy(false)
    }
  }

  const toggleAuditDetails = (auditId) => {
    setExpandedAudit((prev) => ({ ...prev, [auditId]: !prev[auditId] }))
  }

  const exportTrialAudit = async () => {
    setAuditBusy(true)
    setAuditError('')
    try {
      const res = await api.post('/audit/export', { trial_id: id }, { responseType: 'blob' })
      const disposition = res.headers['content-disposition'] || ''
      const match = disposition.match(/filename=\"?([^"]+)\"?/)
      const filename = match?.[1] || `trial_${id}_audit.csv`
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'text/csv' }))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', filename)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
      await loadAudit()
    } catch (err) {
      setAuditError(err.response?.data?.detail || 'Could not export trial audit.')
    } finally {
      setAuditBusy(false)
    }
  }

  useEffect(() => {
    if (activeTab === 'Audit') {
      loadAudit()
    }
  }, [activeTab, id, canAudit])

  const content = useMemo(() => {
    if (!trial) return <div className="text-sm">Loading...</div>

    if (activeTab === 'Overview') {
      return (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            <Card label="Nickname" value={trial.nickname} />
            <Card label="NCT ID" value={trial.nct_id || '-'} />
            <Card label="Indication" value={trial.indication} />
            <Card label="Phase" value={trial.phase || '-'} />
            <Card label="Sponsor" value={trial.sponsor || '-'} />
            <Card label="Status" value={trial.status} />
            <Card
              label="Indexing"
              value={
                qaStatus?.embeddings_exist
                  ? `✅ Indexed (${qaStatus.chunk_count} chunks)`
                  : '🟡 Pending'
              }
            />
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <h4 className="font-display text-lg">CTG Snapshot</h4>
            {snapshots.length === 0 ? (
              <p className="mt-2 text-sm text-slate-600">No snapshot available yet.</p>
            ) : (
              <div className="mt-2 space-y-2 text-sm">
                {snapshots.map((item, idx) => (
                  <div key={`${item.nct_id || 'snapshot'}-${idx}`} className="rounded-lg bg-fog p-2">
                    <div className="font-medium">Clinical Trial Record</div>
                    <div className="text-slate-600">
                      {item.nct_id} | pulled {new Date(item.pulled_at).toLocaleString()}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )
    }

    if (activeTab === 'Documents') {
      return (
        <div>
          {canUpload && (
            <button className="mb-3 rounded-lg bg-ink px-4 py-2 text-sm text-white" onClick={() => setUploadOpen(true)}>
              Upload Document
            </button>
          )}
          <div className="rounded-xl border border-slate-200 bg-white">
            {documents.length === 0 ? (
              <div className="p-4 text-sm text-slate-500">No documents uploaded.</div>
            ) : (
              <ul className="divide-y divide-slate-100">
                {documents.map((doc) => (
                  <li className="flex items-center justify-between p-3 text-sm" key={doc.id}>
                    <div>
                      <div className="font-medium">v{doc.version} - {doc.filename}</div>
                      <div className="text-xs text-slate-500">{new Date(doc.uploaded_at).toLocaleString()}</div>
                    </div>
                    <span className="text-xs text-slate-500">{doc.file_path}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )
    }

    if (activeTab === 'Criteria') {
      return (
        <div className="space-y-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="font-display text-lg">Criteria Review</h4>
              {canReview && (
                <div className="flex flex-wrap gap-2">
                  <button
                    className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    onClick={parseCriteria}
                    disabled={criteriaBusy}
                  >
                    Parse Criteria
                  </button>
                  <button
                    className="rounded-lg bg-ink px-3 py-2 text-sm text-white disabled:opacity-50"
                    onClick={approveAll}
                    disabled={criteriaBusy}
                  >
                    Approve All High Confidence
                  </button>
                </div>
              )}
            </div>

            {reviewStatus && (
              <div className="mt-3 rounded-lg bg-fog px-3 py-2 text-sm text-slate-700">
                {reviewStatus.approved} of {reviewStatus.total} criteria approved - {reviewStatus.blocking_count} blocking activation
              </div>
            )}

            {criteriaError && (
              <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                {criteriaError}
              </div>
            )}

            <div className="mt-3 overflow-x-auto rounded-xl border border-slate-200">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50 text-left text-slate-600">
                  <tr>
                    <th className="px-4 py-3">Raw text</th>
                    <th className="px-4 py-3">Expression</th>
                    <th className="px-4 py-3">Confidence</th>
                    <th className="px-4 py-3">Approval</th>
                    {canReview && <th className="px-4 py-3">Actions</th>}
                  </tr>
                </thead>
                <tbody>
                  {criteria.map((row) => {
                    const approvalStatus = row.approved_at ? 'approved' : row.manual_review_required ? 'manual' : 'pending'
                    return (
                      <tr key={row.id} className="border-t border-slate-100 align-top">
                        <td className="px-4 py-3">{row.text}</td>
                        <td className="px-4 py-3">
                          <pre className="max-w-md overflow-auto whitespace-pre-wrap rounded bg-fog p-2 text-xs text-slate-700">
                            {JSON.stringify(row.expression, null, 2)}
                          </pre>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`badge ${confidenceClass[row.confidence] || 'bg-slate-100 text-slate-700'}`}>
                            {row.confidence}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`badge ${approvalClass[approvalStatus] || 'bg-slate-100 text-slate-700'}`}>
                            {approvalStatus === 'approved'
                              ? 'Approved'
                              : approvalStatus === 'manual'
                                ? 'Manual Review Flagged'
                                : 'Pending'}
                          </span>
                        </td>
                        {canReview && (
                          <td className="px-4 py-3">
                            <div className="flex flex-wrap gap-2">
                              <button
                                className="rounded-lg border border-slate-300 px-2 py-1 text-xs"
                                onClick={() => openEdit(row)}
                              >
                                Edit Expression
                              </button>
                              {!row.approved_at && (
                                <button
                                  className="rounded-lg bg-ink px-2 py-1 text-xs text-white"
                                  onClick={() => approveCriterion(row.id)}
                                  disabled={criteriaBusy}
                                >
                                  Approve
                                </button>
                              )}
                            </div>
                          </td>
                        )}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {criteria.length === 0 && <div className="p-4 text-sm text-slate-500">No criteria parsed yet.</div>}
            </div>
          </div>
        </div>
      )
    }

    if (activeTab === 'Amendments') {
      return (
        <div className="rounded-xl border border-slate-200 bg-white">
          {amendments.length === 0 ? (
            <div className="p-4 text-sm text-slate-500">No amendments recorded.</div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {amendments.map((a) => (
                <li className="p-4" key={a.id}>
                  <div className="text-sm font-semibold">
                    v{a.from_version} to v{a.to_version}
                  </div>
                  <pre className="mt-2 whitespace-pre-wrap rounded-lg bg-fog p-3 text-xs text-slate-700">{a.summary}</pre>
                </li>
              ))}
            </ul>
          )}
        </div>
      )
    }

    if (activeTab === 'Q&A') {
      return <ProtocolQA trialId={id} />
    }

    if (activeTab === 'Audit') {
      if (!canAudit) {
        return <div className="text-sm text-slate-600">Audit log is only available to owner and coordinator roles.</div>
      }

      return (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="font-display text-lg">Trial Audit Log</h4>
            {user.role === 'owner' && (
              <button
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                onClick={exportTrialAudit}
                disabled={auditBusy}
              >
                Export
              </button>
            )}
          </div>

          {auditError && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{auditError}</div>
          )}
          {auditBusy && <div className="text-sm text-slate-500">Loading audit data...</div>}

          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-slate-600">
                <tr>
                  <th className="px-4 py-3">Timestamp</th>
                  <th className="px-4 py-3">User</th>
                  <th className="px-4 py-3">Indication</th>
                  <th className="px-4 py-3">Overall Result</th>
                  <th className="px-4 py-3">Criteria Breakdown</th>
                </tr>
              </thead>
              <tbody>
                {auditEntries.map((entry) => {
                  const trialResult = entry.screen_results?.[id]
                  const criteria = Array.isArray(trialResult?.criteria) ? trialResult.criteria : []
                  const isExpanded = Boolean(expandedAudit[entry.id])
                  return (
                    <tr className="border-t border-slate-100 align-top" key={entry.id}>
                      <td className="px-4 py-3">{new Date(entry.timestamp).toLocaleString()}</td>
                      <td className="px-4 py-3">{entry.user_email || '-'}</td>
                      <td className="px-4 py-3 uppercase">{entry.indication}</td>
                      <td className="px-4 py-3">{trialResult?.overall || '-'}</td>
                      <td className="px-4 py-3">
                        {criteria.length === 0 ? (
                          '-'
                        ) : (
                          <div>
                            <button
                              className="rounded-lg border border-slate-300 px-2 py-1 text-xs"
                              onClick={() => toggleAuditDetails(entry.id)}
                            >
                              {isExpanded ? 'Hide' : 'Show'} ({criteria.length})
                            </button>
                            {isExpanded && (
                              <div className="mt-2 space-y-1 rounded-lg bg-fog p-2 text-xs">
                                {criteria.map((criterion) => (
                                  <div key={`${entry.id}-${criterion.criterion_id}`}>
                                    {criterion.criterion_id}: {criterion.result}
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {auditEntries.length === 0 && <div className="p-4 text-sm text-slate-500">No audit entries found for this trial.</div>}
          </div>
        </div>
      )
    }

    return <Placeholder text="Phase 5" />
  }, [
    activeTab,
    trial,
    snapshots,
    documents,
    amendments,
    canUpload,
    canReview,
    criteria,
    reviewStatus,
    criteriaError,
    criteriaBusy,
    canAudit,
    auditEntries,
    auditError,
    auditBusy,
    expandedAudit,
    qaStatus,
    id,
    user.role,
  ])

  return (
    <div>
      <Nav user={user} onLogout={onLogout} />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <h2 className="font-display text-2xl">{trial?.nickname || 'Trial Detail'}</h2>

        <div className="mt-4 flex flex-wrap gap-2">
          {tabs.map((tab) => (
            <button
              key={tab}
              className={`rounded-full px-4 py-2 text-sm ${
                activeTab === tab ? 'bg-ink text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
              }`}
              onClick={() => setActiveTab(tab)}
            >
              {tab}
            </button>
          ))}
        </div>

        <section className="mt-4">{content}</section>
      </main>

      <UploadModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        trialId={id}
        onUploaded={load}
      />

      {editModalOpen && editTarget && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-ink/50 p-4">
          <div className="w-full max-w-2xl rounded-2xl bg-white p-5 shadow-2xl">
            <h3 className="font-display text-xl">Edit Criterion Expression</h3>
            <p className="mt-1 text-xs text-slate-500">{editTarget.text}</p>

            <textarea
              className="mt-4 h-64 w-full rounded-lg border border-slate-300 p-3 font-mono text-xs"
              value={editExpression}
              onChange={(e) => setEditExpression(e.target.value)}
            />

            <label className="mt-3 flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={editManualReview}
                onChange={(e) => setEditManualReview(e.target.checked)}
              />
              Manual review required
            </label>

            <div className="mt-4 flex justify-between">
              <button
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                onClick={() => setEditModalOpen(false)}
              >
                Cancel
              </button>
              <button
                className="rounded-lg bg-ink px-4 py-2 text-sm text-white"
                onClick={saveEdit}
                disabled={criteriaBusy}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Card({ label, value }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-sm font-semibold text-ink">{value}</p>
    </div>
  )
}

function Placeholder({ text }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
      {text}
    </div>
  )
}
