import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import Nav from '../components/Nav'
import ProtocolQA from '../components/ProtocolQA'
import UploadModal from '../components/UploadModal'
import { useAuth } from '../context/AuthContext'
import api from '../lib/api'

const confidenceClass = {
  high: 'bg-emerald-100 text-emerald-800',
  needs_review: 'bg-amber-100 text-amber-800',
}

const approvalClass = {
  approved: 'bg-emerald-100 text-emerald-800',
  pending: 'bg-slate-200 text-slate-700',
  manual: 'bg-amber-100 text-amber-800',
}

const extractionStatusClass = {
  processing: 'bg-sky-100 text-sky-800',
  ready: 'bg-emerald-100 text-emerald-800',
  needs_review: 'bg-amber-100 text-amber-800',
}

function truncateSummary(value, maxLength = 180) {
  if (!value) return ''
  if (value.length <= maxLength) return value
  return `${value.slice(0, maxLength)}...`
}

export default function TrialDetail({ onLogout }) {
  const { user } = useAuth()
  const { id } = useParams()
  const navigate = useNavigate()

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
  const [expandedAmendments, setExpandedAmendments] = useState({})
  const [trialBusy, setTrialBusy] = useState(false)
  const [trialError, setTrialError] = useState('')
  const [metadataForm, setMetadataForm] = useState({
    nickname: '',
    trial_title: '',
    document_title: '',
    nct_id: '',
    ctg_url: '',
    indication: '',
    phase: '',
    sponsor: '',
  })
  const [metadataBusy, setMetadataBusy] = useState(false)
  const [metadataError, setMetadataError] = useState('')
  const [metadataSaved, setMetadataSaved] = useState('')

  if (!user) {
    return null
  }

  const canUpload = ['owner', 'pi', 'coordinator'].includes(user.role)
  const canReview = ['owner', 'pi', 'coordinator'].includes(user.role)
  const canAudit = ['owner', 'coordinator'].includes(user.role)
  const canArchive = ['owner', 'pi'].includes(user.role)
  const canDelete = user.role === 'owner'
  const canEditMetadata = ['owner', 'pi', 'coordinator'].includes(user.role)

  const tabs = useMemo(() => {
    const available = ['Overview', 'Documents', 'Criteria', 'Amendments', 'Q&A']
    if (canAudit) {
      available.push('Audit')
    }
    return available
  }, [canAudit])

  const documentsByVersion = useMemo(
    () => Object.fromEntries(documents.map((doc) => [doc.version, doc])),
    [documents],
  )

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

  const loadQaStatus = async () => {
    try {
      const res = await api.get(`/trials/${id}/qa/status`)
      setQaStatus(res.data)
    } catch {
      setQaStatus(null)
    }
  }

  const load = async () => {
    await Promise.all([loadTrialData(), loadCriteria(), loadQaStatus()])
  }

  useEffect(() => {
    load()
  }, [id])

  useEffect(() => {
    if (!tabs.includes(activeTab)) {
      setActiveTab('Overview')
    }
  }, [activeTab, tabs])

  useEffect(() => {
    if (!trial) return
    setMetadataForm({
      nickname: trial.nickname || '',
      trial_title: trial.trial_title || '',
      document_title: trial.document_title || '',
      nct_id: trial.nct_id || '',
      ctg_url: trial.ctg_url || '',
      indication: trial.indication || '',
      phase: trial.phase || '',
      sponsor: trial.sponsor || '',
    })
  }, [trial])

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

  const archiveTrial = async () => {
    if (!canArchive) return
    setTrialBusy(true)
    setTrialError('')
    try {
      const res = await api.post(`/trials/${id}/archive`)
      setTrial(res.data)
    } catch (err) {
      setTrialError(err.response?.data?.detail || 'Could not archive trial.')
    } finally {
      setTrialBusy(false)
    }
  }

  const deleteTrial = async () => {
    if (!canDelete) return
    const confirmed = window.confirm('Delete this trial permanently? This action cannot be undone.')
    if (!confirmed) return

    setTrialBusy(true)
    setTrialError('')
    try {
      await api.delete(`/trials/${id}`)
      navigate('/trials')
    } catch (err) {
      setTrialError(err.response?.data?.detail || 'Could not delete trial.')
      setTrialBusy(false)
    }
  }

  const saveTrialMetadata = async () => {
    if (!canEditMetadata) return
    const nickname = metadataForm.nickname.trim()
    if (!nickname) {
      setMetadataError('Nickname is required.')
      return
    }

    setMetadataBusy(true)
    setMetadataError('')
    setMetadataSaved('')
    try {
      const payload = {
        nickname,
        trial_title: metadataForm.trial_title.trim() || null,
        document_title: metadataForm.document_title.trim() || null,
        nct_id: metadataForm.nct_id.trim() || null,
        ctg_url: metadataForm.ctg_url.trim() || null,
        indication: metadataForm.indication || null,
        phase: metadataForm.phase.trim() || null,
        sponsor: metadataForm.sponsor.trim() || null,
      }
      const res = await api.patch(`/trials/${id}`, payload)
      setTrial(res.data)
      setMetadataSaved('Metadata updated.')
    } catch (err) {
      setMetadataError(err.response?.data?.detail || 'Could not update trial metadata.')
    } finally {
      setMetadataBusy(false)
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

  const downloadDocument = async (documentId, filename) => {
    try {
      const res = await api.get(`/trials/${id}/documents/${documentId}/download`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', filename)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      setTrialError(err.response?.data?.detail || 'Could not download document.')
    }
  }

  const toggleAuditDetails = (auditId) => {
    setExpandedAudit((prev) => ({ ...prev, [auditId]: !prev[auditId] }))
  }

  const toggleAmendment = (amendmentId) => {
    setExpandedAmendments((prev) => ({ ...prev, [amendmentId]: !prev[amendmentId] }))
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
          {(canArchive || canDelete) && (
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <h4 className="font-display text-lg">Trial Actions</h4>
              <div className="mt-3 flex flex-wrap gap-2">
                {canArchive && (
                  <button
                    className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    onClick={archiveTrial}
                    disabled={trialBusy || trial.status === 'archived'}
                  >
                    Archive Trial
                  </button>
                )}
                {canDelete && (
                  <button
                    className="rounded-lg border border-rose-300 px-3 py-2 text-sm text-rose-700"
                    onClick={deleteTrial}
                    disabled={trialBusy}
                  >
                    Delete Trial
                  </button>
                )}
              </div>
              {trialError && (
                <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                  {trialError}
                </div>
              )}
            </div>
          )}

          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="font-display text-lg">Trial Metadata</h4>
              <span className={`badge ${extractionStatusClass[trial.extraction_status] || 'bg-slate-100 text-slate-700'}`}>
                extraction: {trial.extraction_status}
              </span>
            </div>
            {trial.extraction_status === 'processing' && (
              <div className="mt-3 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800">
                Metadata extraction is running from the latest protocol upload.
              </div>
            )}
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">Nickname</p>
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={metadataForm.nickname}
                  onChange={(e) => setMetadataForm((previous) => ({ ...previous, nickname: e.target.value }))}
                  disabled={!canEditMetadata || metadataBusy}
                />
              </div>
              <div className="md:col-span-2">
                <p className="text-xs uppercase tracking-wide text-slate-500">Trial Title</p>
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={metadataForm.trial_title}
                  onChange={(e) => setMetadataForm((previous) => ({ ...previous, trial_title: e.target.value }))}
                  disabled={!canEditMetadata || metadataBusy}
                />
              </div>
              <div className="md:col-span-2">
                <p className="text-xs uppercase tracking-wide text-slate-500">Document Title</p>
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={metadataForm.document_title}
                  onChange={(e) => setMetadataForm((previous) => ({ ...previous, document_title: e.target.value }))}
                  disabled={!canEditMetadata || metadataBusy}
                />
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">NCT ID</p>
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={metadataForm.nct_id}
                  onChange={(e) => setMetadataForm((previous) => ({ ...previous, nct_id: e.target.value }))}
                  disabled={!canEditMetadata || metadataBusy}
                />
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">CTG URL</p>
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={metadataForm.ctg_url}
                  onChange={(e) => setMetadataForm((previous) => ({ ...previous, ctg_url: e.target.value }))}
                  disabled={!canEditMetadata || metadataBusy}
                />
                {trial.ctg_url && (
                  <a
                    className="mt-2 inline-flex text-xs text-sky-700 hover:underline"
                    href={trial.ctg_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open ClinicalTrials.gov record
                  </a>
                )}
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">Indication</p>
                <select
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={metadataForm.indication}
                  onChange={(e) => setMetadataForm((previous) => ({ ...previous, indication: e.target.value }))}
                  disabled={!canEditMetadata || metadataBusy}
                >
                  <option value="">Unknown</option>
                  <option value="aml">AML</option>
                  <option value="all">ALL</option>
                  <option value="lymphoma">Lymphoma</option>
                  <option value="mm">MM</option>
                  <option value="transplant">Transplant</option>
                  <option value="gvhd">GVHD</option>
                </select>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">Phase</p>
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={metadataForm.phase}
                  onChange={(e) => setMetadataForm((previous) => ({ ...previous, phase: e.target.value }))}
                  disabled={!canEditMetadata || metadataBusy}
                />
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">Sponsor</p>
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={metadataForm.sponsor}
                  onChange={(e) => setMetadataForm((previous) => ({ ...previous, sponsor: e.target.value }))}
                  disabled={!canEditMetadata || metadataBusy}
                />
              </div>
            </div>
            <div className="mt-4 rounded-lg border border-slate-200 bg-fog p-3 text-sm text-slate-700">
              <div>
                <span className="font-medium">CTG match confidence:</span>{' '}
                {typeof trial.ctg_match_confidence === 'number' ? trial.ctg_match_confidence.toFixed(2) : 'N/A'}
              </div>
              <div className="mt-1">
                <span className="font-medium">CTG match note:</span> {trial.ctg_match_note || 'N/A'}
              </div>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <Card label="Status" value={trial.status} />
              <Card
                label="Indexing"
                value={qaStatus?.embeddings_exist ? `Indexed (${qaStatus.chunk_count} chunks)` : 'Pending'}
              />
            </div>
            {canEditMetadata && (
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <button
                  className="rounded-lg bg-ink px-4 py-2 text-sm text-white disabled:opacity-50"
                  onClick={saveTrialMetadata}
                  disabled={metadataBusy}
                >
                  {metadataBusy ? 'Saving...' : 'Save Metadata'}
                </button>
                {metadataSaved && <span className="text-sm text-emerald-700">{metadataSaved}</span>}
                {metadataError && <span className="text-sm text-rose-700">{metadataError}</span>}
              </div>
            )}
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
                  <li className="flex items-center justify-between gap-4 p-3 text-sm" key={doc.id}>
                    <div>
                      <div className="font-medium">v{doc.version} - {doc.filename}</div>
                      <div className="text-xs text-slate-500">
                        {new Date(doc.uploaded_at).toLocaleString()} by {doc.uploaded_by_email || doc.uploaded_by}
                      </div>
                    </div>
                    <button
                      className="rounded-lg border border-slate-300 px-3 py-1 text-xs"
                      onClick={() => downloadDocument(doc.id, doc.filename)}
                    >
                      View Document
                    </button>
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
                    Approve All
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
              {amendments.map((amendment) => {
                const isExpanded = Boolean(expandedAmendments[amendment.id])
                const linkedDoc = documentsByVersion[amendment.to_version]
                return (
                  <li className="p-4" key={amendment.id}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold">Version {amendment.to_version}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          Uploaded {new Date(amendment.uploaded_at).toLocaleString()} by {amendment.uploaded_by_email || amendment.uploaded_by}
                        </div>
                        <div className="mt-2 text-sm text-slate-700">{truncateSummary(amendment.summary)}</div>
                      </div>

                      <div className="flex flex-wrap gap-2">
                        <button
                          className="rounded-lg border border-slate-300 px-3 py-1 text-xs"
                          onClick={() => toggleAmendment(amendment.id)}
                        >
                          {isExpanded ? 'Hide Details' : 'Show Details'}
                        </button>
                        {linkedDoc ? (
                          <button
                            className="rounded-lg border border-slate-300 px-3 py-1 text-xs"
                            onClick={() => downloadDocument(linkedDoc.id, linkedDoc.filename)}
                          >
                            View Document
                          </button>
                        ) : (
                          <span className="rounded-lg border border-slate-200 px-3 py-1 text-xs text-slate-400">No document</span>
                        )}
                      </div>
                    </div>

                    {isExpanded && (
                      <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-fog p-3 text-xs text-slate-700">
                        {amendment.summary}
                      </pre>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )
    }

    if (activeTab === 'Q&A') {
      return <ProtocolQA trialId={id} />
    }

    if (activeTab === 'Audit') {
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
                  const entryCriteria = Array.isArray(trialResult?.criteria) ? trialResult.criteria : []
                  const isExpanded = Boolean(expandedAudit[entry.id])
                  return (
                    <tr className="border-t border-slate-100 align-top" key={entry.id}>
                      <td className="px-4 py-3">{new Date(entry.timestamp).toLocaleString()}</td>
                      <td className="px-4 py-3">{entry.user_email || '-'}</td>
                      <td className="px-4 py-3 uppercase">{entry.indication}</td>
                      <td className="px-4 py-3">{trialResult?.overall || '-'}</td>
                      <td className="px-4 py-3">
                        {entryCriteria.length === 0 ? (
                          '-'
                        ) : (
                          <div>
                            <button
                              className="rounded-lg border border-slate-300 px-2 py-1 text-xs"
                              onClick={() => toggleAuditDetails(entry.id)}
                            >
                              {isExpanded ? 'Hide' : 'Show'} ({entryCriteria.length})
                            </button>
                            {isExpanded && (
                              <div className="mt-2 space-y-1 rounded-lg bg-fog p-2 text-xs">
                                {entryCriteria.map((criterion) => (
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

    return null
  }, [
    activeTab,
    trial,
    snapshots,
    documents,
    amendments,
    canUpload,
    canReview,
    canAudit,
    canArchive,
    canDelete,
    criteria,
    reviewStatus,
    criteriaError,
    criteriaBusy,
    auditEntries,
    auditError,
    auditBusy,
    expandedAudit,
    expandedAmendments,
    qaStatus,
    user.role,
    id,
    trialBusy,
    trialError,
    documentsByVersion,
    canEditMetadata,
    metadataForm,
    metadataBusy,
    metadataError,
    metadataSaved,
  ])

  return (
    <div>
      <Nav onLogout={onLogout} />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="font-display text-2xl">{trial?.nickname || 'Trial Detail'}</h2>
          {trial?.extraction_status && (
            <span className={`badge ${extractionStatusClass[trial.extraction_status] || 'bg-slate-100 text-slate-700'}`}>
              {trial.extraction_status}
            </span>
          )}
        </div>

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
