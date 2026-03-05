import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import AwarenessCardModal from '../components/AwarenessCardModal'
import Nav from '../components/Nav'
import ProtocolQA from '../components/ProtocolQA'
import UploadModal from '../components/UploadModal'
import { useAuth } from '../context/AuthContext'
import api from '../lib/api'

const confidenceClass = {
  high: 'bg-emerald-100 text-emerald-800',
  needs_review: 'bg-amber-100 text-amber-800',
}

const parseStatusClass = {
  parsed: 'bg-sky-100 text-sky-800',
  needs_review: 'bg-amber-100 text-amber-800',
  approved: 'bg-emerald-100 text-emerald-800',
  manual_only: 'bg-violet-100 text-violet-800',
}

const extractionStatusClass = {
  processing: 'bg-amber-100 text-amber-800',
  ready: 'bg-emerald-100 text-emerald-800',
  needs_review: 'bg-sky-100 text-sky-800',
  failed: 'bg-rose-100 text-rose-800',
}

const extractionStatusLabel = {
  processing: 'processing',
  ready: 'ready',
  needs_review: 'needs_review',
  failed: 'failed',
}

const reasonLabelMap = {
  disease_match: 'Disease',
  intervention_match: 'Intervention',
  phase_match: 'Phase',
  population_match: 'Population',
  sponsor_match: 'Sponsor',
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
  const [criteriaView, setCriteriaView] = useState('all')
  const [reviewStatus, setReviewStatus] = useState(null)
  const [criteriaError, setCriteriaError] = useState('')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [editTarget, setEditTarget] = useState(null)
  const [editText, setEditText] = useState('')
  const [editExpression, setEditExpression] = useState('')
  const [editExpressionError, setEditExpressionError] = useState('')
  const [editConfidence, setEditConfidence] = useState('needs_review')
  const [editParseStatus, setEditParseStatus] = useState('needs_review')
  const [editManualReview, setEditManualReview] = useState(false)
  const [criteriaBusy, setCriteriaBusy] = useState(false)
  const [criteriaToast, setCriteriaToast] = useState('')
  const [auditEntries, setAuditEntries] = useState([])
  const [auditError, setAuditError] = useState('')
  const [auditBusy, setAuditBusy] = useState(false)
  const [expandedAudit, setExpandedAudit] = useState({})
  const [qaStatus, setQaStatus] = useState(null)
  const [expandedAmendments, setExpandedAmendments] = useState({})
  const [trialBusy, setTrialBusy] = useState(false)
  const [trialError, setTrialError] = useState('')
  const [candidateBusy, setCandidateBusy] = useState(false)
  const [ctgMatchBusy, setCtgMatchBusy] = useState(false)
  const [candidateError, setCandidateError] = useState('')
  const [ctgCandidates, setCtgCandidates] = useState([])
  const [metadataForm, setMetadataForm] = useState({
    nickname: '',
    trial_title: '',

    nct_id: '',
    ctg_url: '',
    indication: '',
    phase: '',
    sponsor: '',
  })
  const [metadataBusy, setMetadataBusy] = useState(false)
  const [metadataError, setMetadataError] = useState('')
  const [metadataSaved, setMetadataSaved] = useState('')
  const [isEditingMetadata, setIsEditingMetadata] = useState(true)
  const [awarenessOpen, setAwarenessOpen] = useState(false)

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

  const loadCtgCandidates = async ({ showProgress = false } = {}) => {
    if (showProgress) {
      setCtgMatchBusy(true)
      setCandidateError('')
    }
    try {
      const res = await api.get(`/trials/${id}/ctg/candidates`)
      setCtgCandidates(Array.isArray(res.data) ? res.data.slice(0, 5) : [])
      return true
    } catch {
      setCtgCandidates([])
      if (showProgress) {
        setCandidateError('Could not match CTG candidates.')
      }
      return false
    } finally {
      if (showProgress) {
        setCtgMatchBusy(false)
      }
    }
  }

  const loadCriteria = async (view = criteriaView) => {
    try {
      const [criteriaRes, statusRes] = await Promise.all([
        api.get(`/trials/${id}/criteria`, { params: { type: view } }),
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
    await Promise.all([loadTrialData(), loadQaStatus(), loadCtgCandidates()])
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
      nct_id: trial.nct_id || '',
      ctg_url: trial.ctg_url || '',
      indication: trial.indication || '',
      phase: trial.phase || '',
      sponsor: trial.sponsor || '',
    })
    setIsEditingMetadata(!(trial.metadata_locked ?? false))
  }, [trial])

  useEffect(() => {
    loadCriteria(criteriaView)
  }, [criteriaView, id])

  useEffect(() => {
    if (!criteriaToast) return undefined
    const timeoutId = window.setTimeout(() => setCriteriaToast(''), 2800)
    return () => window.clearTimeout(timeoutId)
  }, [criteriaToast])

  const approveCriterion = async (criterionId) => {
    setCriteriaBusy(true)
    setCriteriaError('')
    try {
      await api.post(`/trials/${id}/criteria/${criterionId}/approve`)
      await loadCriteria(criteriaView)
    } catch (err) {
      setCriteriaError(err.response?.data?.detail || 'Approve failed.')
    } finally {
      setCriteriaBusy(false)
    }
  }

  const approveReviewed = async () => {
    setCriteriaBusy(true)
    setCriteriaError('')
    try {
      await api.post(`/trials/${id}/criteria/approve-reviewed`)
      await loadCriteria(criteriaView)
    } catch (err) {
      setCriteriaError(err.response?.data?.detail || 'Bulk approve failed.')
    } finally {
      setCriteriaBusy(false)
    }
  }

  const approveAllVisible = async () => {
    if (!canReview || criteriaBusy) return
    const visibleRows = criteria.filter((row) => !row.approved_at && (row.text || '').trim())
    if (visibleRows.length === 0) {
      setCriteriaToast('No visible criteria to approve.')
      return
    }

    setCriteriaBusy(true)
    setCriteriaError('')
    try {
      for (const row of visibleRows) {
        await api.post(`/trials/${id}/criteria/${row.id}/approve`)
      }
      await loadCriteria(criteriaView)
      setCriteriaToast(`Approved ${visibleRows.length} visible criteria.`)
    } catch (err) {
      setCriteriaError(err.response?.data?.detail || 'Approve visible failed.')
    } finally {
      setCriteriaBusy(false)
    }
  }

  const deleteCriterion = async (criterionId) => {
    if (!canReview || criteriaBusy) return
    const confirmed = window.confirm('Delete this criterion?')
    if (!confirmed) return

    setCriteriaBusy(true)
    setCriteriaError('')
    try {
      await api.delete(`/trials/${id}/criteria/${criterionId}`)
      await loadCriteria(criteriaView)
    } catch (err) {
      setCriteriaError(err.response?.data?.detail || 'Delete failed.')
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
        nct_id: metadataForm.nct_id.trim() || null,
        ctg_url: metadataForm.ctg_url.trim() || null,
        indication: metadataForm.indication || null,
        phase: metadataForm.phase.trim() || null,
        sponsor: metadataForm.sponsor.trim() || null,
      }
      const res = await api.patch(`/trials/${id}`, payload)
      setTrial(res.data)
      setIsEditingMetadata(false)
      setMetadataSaved('Metadata updated.')
    } catch (err) {
      setMetadataError(err.response?.data?.detail || 'Could not update trial metadata.')
    } finally {
      setMetadataBusy(false)
    }
  }

  const cancelMetadataEdit = () => {
    if (!trial) return
    setMetadataForm({
      nickname: trial.nickname || '',
      trial_title: trial.trial_title || '',
      nct_id: trial.nct_id || '',
      ctg_url: trial.ctg_url || '',
      indication: trial.indication || '',
      phase: trial.phase || '',
      sponsor: trial.sponsor || '',
    })
    setMetadataError('')
    setMetadataSaved('')
    setIsEditingMetadata(false)
  }

  const acceptCtgCandidate = async (candidate = null) => {
    if (!canEditMetadata) return
    setCandidateBusy(true)
    setCandidateError('')
    try {
      const payload = candidate?.nct_id
        ? {
            nct_id: candidate.nct_id,
            title: candidate.title || null,
            url: candidate.url || null,
            source: candidate.source || null,
            final_score: typeof candidate.final_score === 'number' ? candidate.final_score : null,
            confidence:
              typeof candidate.final_score === 'number'
                ? candidate.final_score
                : typeof candidate.confidence === 'number'
                  ? candidate.confidence
                  : null,
          }
        : {}
      await api.post(`/trials/${id}/ctg/accept-candidate`, payload)
      await Promise.all([loadTrialData(), loadCtgCandidates()])
    } catch (err) {
      setCandidateError(err.response?.data?.detail || 'Could not accept CTG candidate.')
    } finally {
      setCandidateBusy(false)
    }
  }

  const matchCtgCandidates = async () => {
    if (!canEditMetadata || ctgMatchBusy || candidateBusy) return
    await loadCtgCandidates({ showProgress: true })
  }

  const openEdit = (criterion) => {
    setEditTarget(criterion)
    setEditText(criterion.text || '')
    setEditExpression(criterion.expression ? JSON.stringify(criterion.expression, null, 2) : '')
    setEditExpressionError('')
    setEditConfidence(criterion.confidence || 'needs_review')
    setEditParseStatus(criterion.parse_status || 'needs_review')
    setEditManualReview(criterion.manual_review_required)
    setEditModalOpen(true)
  }

  const saveEdit = async () => {
    if (!editTarget) return
    const trimmedText = editText.trim()
    if (!trimmedText) {
      setEditExpressionError('Text is required.')
      return
    }

    let parsedExpression
    if (!editExpression.trim()) {
      parsedExpression = null
    } else {
      try {
        parsedExpression = JSON.parse(editExpression)
      } catch {
        setEditExpressionError('Expression must be valid JSON.')
        return
      }
    }

    setCriteriaBusy(true)
    setCriteriaError('')
    setEditExpressionError('')
    try {
      await api.patch(`/trials/${id}/criteria/${editTarget.id}`, {
        text: trimmedText,
        expression: parsedExpression,
        confidence: editConfidence,
        manual_review_required: editManualReview,
        parse_status: editParseStatus,
      })
      setEditModalOpen(false)
      setEditTarget(null)
      await loadCriteria(criteriaView)
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

  const suggestedManualCtgQuery = useMemo(() => {
    if (!trial) return 'site:clinicaltrials.gov <disease> <intervention> <phase>'
    const parts = [trial.trial_title, trial.indication, trial.phase, trial.sponsor]
      .map((value) => (value ? String(value).trim() : ''))
      .filter(Boolean)
    const query = parts.join(' ')
    if (query) {
      return `site:clinicaltrials.gov ${query}`
    }
    return 'site:clinicaltrials.gov <disease> <intervention> <phase>'
  }, [trial])

  const content = useMemo(() => {
    if (!trial) return <div className="text-sm">Loading...</div>

    if (activeTab === 'Overview') {
      return (
        <div className="space-y-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <h4 className="font-display text-lg">Awareness Card</h4>
            <p className="mt-1 text-sm text-slate-600">Create a concise, shareable trial-level card.</p>
            <button
              className="mt-3 rounded-lg bg-ink px-4 py-2 text-sm text-white"
              onClick={() => setAwarenessOpen(true)}
            >
              Generate Awareness Card
            </button>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="font-display text-lg">Trial Metadata</h4>
              <div className="flex items-center gap-2">
                {canEditMetadata && !isEditingMetadata && (
                  <button
                    className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
                    onClick={() => setIsEditingMetadata(true)}
                  >
                    Edit Metadata
                  </button>
                )}
                <span className={`badge ${extractionStatusClass[trial.extraction_status] || 'bg-slate-100 text-slate-700'}`}>
                  {trial.extraction_status === 'processing' && <SpinnerIcon className="mr-1 inline-block h-3 w-3 align-[-1px]" />}
                  extraction: {extractionStatusLabel[trial.extraction_status] || trial.extraction_status}
                </span>
              </div>
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
                  disabled={!canEditMetadata || metadataBusy || !isEditingMetadata}
                />
              </div>
              <div className="md:col-span-2">
                <p className="text-xs uppercase tracking-wide text-slate-500">Trial Title</p>
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={metadataForm.trial_title}
                  onChange={(e) => setMetadataForm((previous) => ({ ...previous, trial_title: e.target.value }))}
                  disabled={!canEditMetadata || metadataBusy || !isEditingMetadata}
                />
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">NCT ID</p>
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={metadataForm.nct_id}
                  onChange={(e) => setMetadataForm((previous) => ({ ...previous, nct_id: e.target.value }))}
                  disabled={!canEditMetadata || metadataBusy || !isEditingMetadata}
                />
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">CTG URL</p>
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={metadataForm.ctg_url}
                  onChange={(e) => setMetadataForm((previous) => ({ ...previous, ctg_url: e.target.value }))}
                  disabled={!canEditMetadata || metadataBusy || !isEditingMetadata}
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
                  disabled={!canEditMetadata || metadataBusy || !isEditingMetadata}
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
                  disabled={!canEditMetadata || metadataBusy || !isEditingMetadata}
                />
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">Sponsor</p>
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={metadataForm.sponsor}
                  onChange={(e) => setMetadataForm((previous) => ({ ...previous, sponsor: e.target.value }))}
                  disabled={!canEditMetadata || metadataBusy || !isEditingMetadata}
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
              {canEditMetadata && (
                <div className="mt-3">
                  <button
                    className="rounded-lg border border-slate-300 px-3 py-2 text-xs disabled:opacity-50"
                    onClick={matchCtgCandidates}
                    disabled={ctgMatchBusy || candidateBusy}
                  >
                    {ctgMatchBusy ? 'Matching...' : 'Match CTG Candidates'}
                  </button>
                </div>
              )}
            </div>
            {ctgMatchBusy && (
              <div className="mt-3 flex items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800">
                <SpinnerIcon />
                <span>Matching CTG candidates...</span>
              </div>
            )}
            {!ctgMatchBusy && candidateError && (
              <p className="mt-3 text-sm text-rose-700">{candidateError}</p>
            )}
            {!trial.nct_id && ctgCandidates.length > 0 && (
              <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                <p className="font-semibold">Top CTG candidates</p>
                <div className="mt-3 grid gap-3 md:grid-cols-1">
                  {ctgCandidates.map((candidate) => (
                    <div key={`${candidate.nct_id}-${candidate.source || 'source'}`} className="rounded-lg border border-amber-300 bg-white p-3">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-xs uppercase tracking-wide text-slate-500">{candidate.source || 'resolver'}</p>
                          <p className="font-medium text-slate-900">{candidate.title || 'Untitled CTG Candidate'}</p>
                          {candidate.url ? (
                            <a className="mt-1 inline-flex text-xs text-sky-700 hover:underline" href={candidate.url} target="_blank" rel="noreferrer">
                              {candidate.nct_id}
                            </a>
                          ) : (
                            <p className="mt-1 text-xs text-slate-700">{candidate.nct_id}</p>
                          )}
                        </div>
                        <div className="rounded-lg bg-slate-100 px-3 py-2 text-right">
                          <p className="text-xs uppercase tracking-wide text-slate-500">Final Score</p>
                          <p className="text-xl font-semibold text-slate-900">
                            {typeof candidate.final_score === 'number'
                              ? candidate.final_score.toFixed(2)
                              : typeof candidate.confidence === 'number'
                                ? candidate.confidence.toFixed(2)
                                : 'N/A'}
                          </p>
                          <p className="text-[11px] text-slate-500">
                            lex {typeof candidate.lexical_score === 'number' ? candidate.lexical_score.toFixed(2) : 'N/A'} | sem{' '}
                            {typeof candidate.semantic_score === 'number' ? candidate.semantic_score.toFixed(2) : 'N/A'}
                          </p>
                        </div>
                      </div>

                      {Array.isArray(candidate.reason_codes) && candidate.reason_codes.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-2">
                          {candidate.reason_codes.map((code) => (
                            <span key={`${candidate.nct_id}-${code}`} className="rounded-full bg-sky-100 px-2 py-1 text-[11px] font-medium text-sky-800">
                              {reasonLabelMap[code] || code}
                            </span>
                          ))}
                        </div>
                      )}

                      {candidate.notes && <p className="mt-2 text-xs text-slate-700">{candidate.notes}</p>}

                      {canEditMetadata && (
                        <div className="mt-3">
                          <button
                            className="rounded-lg bg-ink px-3 py-2 text-sm text-white disabled:opacity-50"
                            onClick={() => acceptCtgCandidate(candidate)}
                            disabled={candidateBusy}
                          >
                            {candidateBusy ? 'Accepting...' : 'Accept'}
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {!trial.nct_id && ctgCandidates.length === 0 && (
              <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                <p className="font-semibold">No CTG candidates found</p>
                <p className="mt-1 text-amber-900/90">
                  Try a manual search query in CTG or web search, then paste the selected NCT ID into metadata.
                </p>
                <p className="mt-2 text-xs">
                  Suggested query: <span className="font-mono">{suggestedManualCtgQuery}</span>
                </p>
              </div>
            )}
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <Card label="Status" value={trial.status} />
              <Card
                label="Indexing"
                value={qaStatus?.embeddings_exist ? `Indexed (${qaStatus.chunk_count} chunks)` : 'Pending'}
              />
            </div>
            {canEditMetadata && isEditingMetadata && (
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <button
                  className="rounded-lg bg-ink px-4 py-2 text-sm text-white disabled:opacity-50"
                  onClick={saveTrialMetadata}
                  disabled={metadataBusy}
                >
                  {metadataBusy ? 'Saving...' : 'Save Metadata'}
                </button>
                {trial.metadata_locked && (
                  <button
                    className="rounded-lg border border-slate-300 px-4 py-2 text-sm"
                    onClick={cancelMetadataEdit}
                    disabled={metadataBusy}
                  >
                    Cancel
                  </button>
                )}
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
                <p className="text-xs text-slate-500">
                  Criteria are automatically extracted after protocol ingestion.
                </p>
              )}
            </div>

            {reviewStatus && (
              <div className="mt-3 rounded-lg bg-fog px-3 py-2 text-sm text-slate-700">
                {reviewStatus.approved} of {reviewStatus.total} criteria approved - {reviewStatus.blocking_count} blocking activation
              </div>
            )}

            {canReview && (
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  className="rounded-lg bg-ink px-3 py-2 text-sm text-white disabled:opacity-50"
                  onClick={approveReviewed}
                  disabled={criteriaBusy}
                >
                  Approve Reviewed
                </button>
                <button
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:opacity-50"
                  onClick={approveAllVisible}
                  disabled={criteriaBusy}
                >
                  Approve All Visible
                </button>
              </div>
            )}

            <div className="mt-3 inline-flex rounded-lg border border-slate-300 p-1">
              {[
                { value: 'inclusion', label: 'Inclusion' },
                { value: 'exclusion', label: 'Exclusion' },
                { value: 'all', label: 'All' },
              ].map((tab) => (
                <button
                  key={tab.value}
                  type="button"
                  onClick={() => setCriteriaView(tab.value)}
                  className={`rounded-md px-3 py-1 text-xs ${criteriaView === tab.value ? 'bg-ink text-white' : 'text-slate-700'}`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {criteriaError && (
              <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                {criteriaError}
              </div>
            )}

            <div className="mt-3 overflow-x-auto rounded-xl border border-slate-200">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50 text-left text-slate-600">
                  <tr>
                    <th className="px-4 py-3">#</th>
                    <th className="px-4 py-3">Criterion text</th>
                    <th className="px-4 py-3">
                      <span title="Extraction confidence (high vs needs review).">Confidence</span>
                    </th>
                    <th className="px-4 py-3">
                      <span title="Workflow state for reviewer action.">Status</span>
                    </th>
                    <th className="px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {criteria.map((row, idx) => {
                    const sourceOrder = row.source_order || idx + 1
                    const parseStatus = row.parse_status || 'needs_review'
                    return (
                      <tr key={row.id} className="border-t border-slate-100 align-top">
                        <td className="px-4 py-3">
                          <span className="badge bg-slate-100 text-slate-700">{sourceOrder}</span>
                        </td>
                        <td className="px-4 py-3">{row.text}</td>
                        <td className="px-4 py-3">
                          <span className={`badge ${confidenceClass[row.confidence] || 'bg-slate-100 text-slate-700'}`}>
                            {row.confidence}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`badge ${parseStatusClass[parseStatus] || 'bg-slate-100 text-slate-700'}`}>
                            {parseStatus}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          {canReview ? (
                            <div className="flex flex-wrap gap-2">
                              <button
                                className="rounded-lg border border-slate-300 px-2 py-1 text-xs"
                                onClick={() => openEdit(row)}
                                disabled={criteriaBusy}
                               title="Edit">✏️</button>
                              <button
                                className="rounded-lg border border-rose-300 px-2 py-1 text-xs text-rose-700"
                                onClick={() => deleteCriterion(row.id)}
                                disabled={criteriaBusy}
                               title="Delete">🗑️</button>
                              {!row.approved_at && (
                                <button
                                  className="rounded-lg bg-ink px-2 py-1 text-xs text-white"
                                  onClick={() => approveCriterion(row.id)}
                                  disabled={criteriaBusy}
                                  title="Approve"
                                >
                                  ✅
                                </button>
                              )}
                            </div>
                          ) : (
                            <span className="text-xs text-slate-500">No actions available</span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {criteria.length === 0 && <div className="p-4 text-sm text-slate-500">No criteria in this view.</div>}
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
    criteriaView,
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
    ctgCandidates,
    candidateBusy,
    ctgMatchBusy,
    candidateError,
    documentsByVersion,
    canEditMetadata,
    metadataForm,
    metadataBusy,
    metadataError,
    metadataSaved,
    suggestedManualCtgQuery,
  ])

  return (
    <div>
      <Nav onLogout={onLogout} />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="font-display text-2xl">{trial?.nickname || 'Trial Detail'}</h2>
          {trial?.extraction_status && (
            <span className={`badge ${extractionStatusClass[trial.extraction_status] || 'bg-slate-100 text-slate-700'}`}>
              {trial.extraction_status === 'processing' && <SpinnerIcon className="mr-1 inline-block h-3 w-3 align-[-1px]" />}
              {extractionStatusLabel[trial.extraction_status] || trial.extraction_status}
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

      {criteriaToast && (
        <div className="fixed right-4 top-4 z-40 rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white shadow-lg">
          {criteriaToast}
        </div>
      )}

      <UploadModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        trialId={id}
        onUploaded={load}
      />

      {editModalOpen && editTarget && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-ink/50 p-4">
          <div className="w-full max-w-2xl rounded-2xl bg-white p-5 shadow-2xl">
            <h3 className="font-display text-xl">Edit Criterion</h3>

            <label className="mt-4 block text-xs uppercase tracking-wide text-slate-500">Criterion text</label>
            <textarea
              className="mt-1 h-28 w-full rounded-lg border border-slate-300 p-3 text-sm"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
            />

            <label className="mt-3 block text-xs uppercase tracking-wide text-slate-500">Expression JSON (optional)</label>
            <textarea
              className="mt-1 h-48 w-full rounded-lg border border-slate-300 p-3 font-mono text-xs"
              value={editExpression}
              onChange={(e) => setEditExpression(e.target.value)}
            />

            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <div>
                <label className="block text-xs uppercase tracking-wide text-slate-500">Confidence</label>
                <select
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={editConfidence}
                  onChange={(e) => setEditConfidence(e.target.value)}
                >
                  <option value="high">high</option>
                  <option value="needs_review">needs_review</option>
                </select>
              </div>
              <div>
                <label className="block text-xs uppercase tracking-wide text-slate-500">Status</label>
                <select
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={editParseStatus}
                  onChange={(e) => setEditParseStatus(e.target.value)}
                >
                  <option value="parsed">parsed</option>
                  <option value="needs_review">needs_review</option>
                  <option value="approved">approved</option>
                  <option value="manual_only">manual_only</option>
                </select>
              </div>
            </div>

            <label className="mt-3 flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={editManualReview}
                onChange={(e) => setEditManualReview(e.target.checked)}
              />
              Manual review required
            </label>
            {editExpressionError && <p className="mt-2 text-sm text-rose-700">{editExpressionError}</p>}

            <div className="mt-4 flex justify-between">
              <button
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                onClick={() => {
                  setEditModalOpen(false)
                  setEditTarget(null)
                  setEditExpressionError('')
                }}
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

      <AwarenessCardModal
        open={awarenessOpen}
        onClose={() => setAwarenessOpen(false)}
        trialId={id}
        trial={trial}
      />
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

function SpinnerIcon({ className = 'h-4 w-4' }) {
  return (
    <svg className={`${className} animate-spin`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-90" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  )
}
