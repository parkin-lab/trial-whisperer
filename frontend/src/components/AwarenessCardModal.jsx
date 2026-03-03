import { useEffect, useState } from 'react'
import api from '../lib/api'

function toNullable(value) {
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function inferMechanismFromTitle(trial) {
  const source = `${trial?.trial_title || ''} ${trial?.document_title || ''}`.toLowerCase()
  const sourcePadded = ` ${source} `
  if (!source.trim()) return ''
  if (source.includes('car-t') || source.includes('cart') || source.includes('chimeric antigen receptor')) {
    return 'CAR-T cell therapy'
  }
  if (source.includes('bispecific') || source.includes('bi-specific') || source.includes('bsab')) {
    return 'Bispecific antibody'
  }
  if (source.includes('antibody-drug conjugate') || source.includes('antibody drug conjugate') || sourcePadded.includes(' adc ')) {
    return 'Antibody-drug conjugate'
  }
  if (source.includes('t-cell engager') || source.includes('t cell engager')) {
    return 'T-cell engager'
  }
  if (source.includes('checkpoint inhibitor') || source.includes('pd-1') || source.includes('pd-l1') || source.includes('ctla-4')) {
    return 'Checkpoint inhibitor'
  }
  if (source.includes('cell therapy')) {
    return 'Cell therapy'
  }
  return ''
}

export default function AwarenessCardModal({ open, onClose, trialId, trial }) {
  const [form, setForm] = useState({
    disease_setting: '',
    mechanism: '',
    trial_purpose: '',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [card, setCard] = useState(null)
  const [previewText, setPreviewText] = useState('')
  const [copied, setCopied] = useState(false)
  const [hasGeneratedInSession, setHasGeneratedInSession] = useState(false)
  const [autoGenerateForm, setAutoGenerateForm] = useState(null)

  const buildPayload = (formValues) => ({
    disease_setting: toNullable(formValues.disease_setting),
    mechanism: toNullable(formValues.mechanism),
    trial_purpose: toNullable(formValues.trial_purpose),
  })

  const generateCard = async (formValues = form) => {
    setBusy(true)
    setError('')
    setCopied(false)
    try {
      const res = await api.post(`/trials/${trialId}/awareness/generate`, buildPayload(formValues))
      setCard(res.data)
      setPreviewText(res.data?.text_card || '')
      setHasGeneratedInSession(true)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not generate awareness card.')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (!open) return
    const initialForm = {
      disease_setting: trial?.indication || '',
      mechanism: inferMechanismFromTitle(trial),
      trial_purpose: '',
    }
    setHasGeneratedInSession(false)
    setAutoGenerateForm(initialForm)
    setForm({ ...initialForm })
    setBusy(false)
    setError('')
    setCard(null)
    setPreviewText('')
    setCopied(false)
  }, [open, trialId])

  useEffect(() => {
    if (!open || hasGeneratedInSession || !autoGenerateForm) return
    generateCard(autoGenerateForm)
    setAutoGenerateForm(null)
  }, [open, hasGeneratedInSession, autoGenerateForm])

  if (!open) return null

  const setField = (name, value) => {
    setForm((prev) => ({ ...prev, [name]: value }))
  }

  const copyText = async () => {
    if (!previewText) return
    await navigator.clipboard.writeText(previewText)
    setCopied(true)
  }

  const downloadJson = () => {
    if (!card) return
    const payload = {
      ...card,
      text_card: previewText,
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `awareness-card-${trialId}.json`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  }

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-ink/50 p-4">
      <div className="w-full max-w-2xl rounded-2xl bg-white p-5 shadow-2xl">
        <div className="flex items-center justify-between">
          <h3 className="font-display text-xl">Trial Awareness Card</h3>
          <button className="rounded-lg border border-slate-300 px-3 py-1 text-sm" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <label className="text-sm text-slate-700">
            Disease setting
            <input
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={form.disease_setting}
              onChange={(e) => setField('disease_setting', e.target.value)}
            />
          </label>
          <label className="text-sm text-slate-700">
            Mechanism / intervention
            <input
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={form.mechanism}
              onChange={(e) => setField('mechanism', e.target.value)}
            />
          </label>
          <label className="text-sm text-slate-700 md:col-span-2">
            Trial purpose override (optional)
            <textarea
              className="mt-1 h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={form.trial_purpose}
              onChange={(e) => setField('trial_purpose', e.target.value)}
            />
          </label>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            className="rounded-lg bg-ink px-4 py-2 text-sm text-white disabled:opacity-50"
            onClick={() => generateCard(form)}
            disabled={busy}
          >
            {busy ? 'Generating...' : 'Generate'}
          </button>
          <button
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:opacity-50"
            onClick={copyText}
            disabled={!previewText}
          >
            Copy Text
          </button>
          <button
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:opacity-50"
            onClick={downloadJson}
            disabled={!card}
          >
            Download JSON
          </button>
          {copied && <span className="text-sm text-emerald-700">Copied.</span>}
        </div>

        {error && <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}

        <div className="mt-4 rounded-xl border border-slate-200 bg-fog p-3">
          <p className="text-xs uppercase tracking-wide text-slate-500">Text card preview (editable)</p>
          <textarea
            className="mt-2 h-44 w-full rounded-lg border border-slate-300 p-3 text-sm text-slate-800"
            value={previewText}
            onChange={(e) => setPreviewText(e.target.value)}
            placeholder="No card generated yet."
          />
        </div>
      </div>
    </div>
  )
}
