import { useEffect, useState } from 'react'
import api from '../lib/api'

function toNullable(value) {
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

export default function AwarenessCardModal({ open, onClose, trialId, trial }) {
  const [form, setForm] = useState({
    disease_setting: '',
    intervention_class: '',
    why_it_matters: '',
    when_to_think: '',
    referral_contact: '',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [card, setCard] = useState(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!open) return
    setForm({
      disease_setting: trial?.indication || '',
      intervention_class: '',
      why_it_matters: '',
      when_to_think: '',
      referral_contact: '',
    })
    setBusy(false)
    setError('')
    setCard(null)
    setCopied(false)
  }, [open, trial?.indication])

  if (!open) return null

  const setField = (name, value) => {
    setForm((prev) => ({ ...prev, [name]: value }))
  }

  const generateCard = async () => {
    setBusy(true)
    setError('')
    setCopied(false)
    try {
      const payload = {
        disease_setting: toNullable(form.disease_setting),
        intervention_class: toNullable(form.intervention_class),
        why_it_matters: toNullable(form.why_it_matters),
        when_to_think: toNullable(form.when_to_think),
        referral_contact: toNullable(form.referral_contact),
      }
      const res = await api.post(`/trials/${trialId}/awareness/generate`, payload)
      setCard(res.data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not generate awareness card.')
    } finally {
      setBusy(false)
    }
  }

  const copyText = async () => {
    if (!card?.text_card) return
    await navigator.clipboard.writeText(card.text_card)
    setCopied(true)
  }

  const downloadJson = () => {
    if (!card) return
    const blob = new Blob([JSON.stringify(card, null, 2)], { type: 'application/json' })
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
            Intervention class
            <input
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={form.intervention_class}
              onChange={(e) => setField('intervention_class', e.target.value)}
            />
          </label>
          <label className="text-sm text-slate-700 md:col-span-2">
            Why it matters
            <textarea
              className="mt-1 h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={form.why_it_matters}
              onChange={(e) => setField('why_it_matters', e.target.value)}
            />
          </label>
          <label className="text-sm text-slate-700 md:col-span-2">
            When to think
            <textarea
              className="mt-1 h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={form.when_to_think}
              onChange={(e) => setField('when_to_think', e.target.value)}
            />
          </label>
          <label className="text-sm text-slate-700 md:col-span-2">
            Referral contact
            <input
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={form.referral_contact}
              onChange={(e) => setField('referral_contact', e.target.value)}
            />
          </label>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            className="rounded-lg bg-ink px-4 py-2 text-sm text-white disabled:opacity-50"
            onClick={generateCard}
            disabled={busy}
          >
            {busy ? 'Generating...' : 'Generate'}
          </button>
          <button
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:opacity-50"
            onClick={copyText}
            disabled={!card?.text_card}
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
          <p className="text-xs uppercase tracking-wide text-slate-500">Text card preview</p>
          <pre className="mt-2 whitespace-pre-wrap text-sm text-slate-800">{card?.text_card || 'No card generated yet.'}</pre>
        </div>
      </div>
    </div>
  )
}
