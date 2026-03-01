import { useEffect, useMemo, useState } from 'react'
import Nav from '../components/Nav'
import { useAuth } from '../context/AuthContext'
import api from '../lib/api'

const INDICATIONS = [
  { value: 'aml', label: 'AML' },
  { value: 'all', label: 'ALL' },
  { value: 'lymphoma', label: 'Lymphoma' },
  { value: 'mm', label: 'MM' },
  { value: 'transplant', label: 'Transplant' },
  { value: 'gvhd', label: 'GVHD' },
]

const STATUS_LABELS = {
  met: 'ELIGIBLE',
  not_met: 'INELIGIBLE',
  incomplete: 'INCOMPLETE',
  manual_review: 'MANUAL REVIEW',
}

const STATUS_CLASS = {
  met: 'bg-emerald-100 text-emerald-800',
  not_met: 'bg-rose-100 text-rose-800',
  incomplete: 'bg-amber-100 text-amber-800',
  manual_review: 'bg-slate-200 text-slate-700',
}

const UNIT_OPTIONS = {
  anc: ['cells/uL', 'x10^9/L'],
  hgb: ['g/dL', 'g/L'],
  cr: ['mg/dL', 'umol/L'],
  bili: ['mg/dL', 'umol/L'],
  age: ['years'],
  lvef: ['%'],
  egfr: ['mL/min/1.73m2'],
}

function normalizeOption(value) {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function buildPatientData(fields, formState) {
  const patientData = {}

  fields.forEach((field) => {
    const value = formState[field.name]

    if (field.type === 'number') {
      if (value === '' || value === null || value === undefined) return
      const numeric = Number(value)
      if (Number.isNaN(numeric)) return
      patientData[field.name] = numeric

      const unitValue = formState[`${field.name}_unit`]
      if (unitValue) {
        patientData[`${field.name}_unit`] = unitValue
      }
      return
    }

    if (field.type === 'boolean') {
      if (value === '' || value === undefined || value === null) return
      patientData[field.name] = value === 'true'
      return
    }

    if (field.type === 'multi_select') {
      if (Array.isArray(value) && value.length > 0) {
        patientData[field.name] = value
      }
      return
    }

    if (value !== '' && value !== undefined && value !== null) {
      patientData[field.name] = value
    }
  })

  return patientData
}

function formatNearMiss(nearMiss) {
  if (!nearMiss) return '-'
  if (nearMiss.delta === null || nearMiss.delta === undefined) {
    return `${nearMiss.actual_value} vs ${nearMiss.required_value}`
  }
  return `${nearMiss.actual_value} vs ${nearMiss.required_value} (delta ${nearMiss.delta.toFixed(2)})`
}

export default function Screener({ onLogout }) {
  const { user } = useAuth()
  const [indication, setIndication] = useState('aml')
  const [fieldsByIndication, setFieldsByIndication] = useState({})
  const [formState, setFormState] = useState({})
  const [results, setResults] = useState([])
  const [engineVersion, setEngineVersion] = useState('1.0.0')
  const [screenedAt, setScreenedAt] = useState(null)
  const [expanded, setExpanded] = useState({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  if (!user) {
    return null
  }

  useEffect(() => {
    api
      .get('/screen/tier1-fields')
      .then((res) => {
        setFieldsByIndication(res.data)
      })
      .catch(() => {
        setError('Could not load Tier 1 field definitions.')
      })
  }, [])

  const fields = useMemo(() => fieldsByIndication[indication] || [], [fieldsByIndication, indication])

  useEffect(() => {
    setFormState((previous) => {
      const next = {}
      fields.forEach((field) => {
        if (previous[field.name] !== undefined) {
          next[field.name] = previous[field.name]
        } else if (field.type === 'multi_select') {
          next[field.name] = []
        } else {
          next[field.name] = ''
        }

        const unitOptions = UNIT_OPTIONS[field.name]
        if (unitOptions) {
          next[`${field.name}_unit`] = previous[`${field.name}_unit`] || unitOptions[0]
        }
      })
      return next
    })
  }, [fields])

  const updateValue = (name, value) => {
    setFormState((previous) => ({ ...previous, [name]: value }))
  }

  const toggleMultiSelect = (name, option) => {
    setFormState((previous) => {
      const current = Array.isArray(previous[name]) ? previous[name] : []
      const hasValue = current.includes(option)
      return {
        ...previous,
        [name]: hasValue ? current.filter((item) => item !== option) : [...current, option],
      }
    })
  }

  const runScreen = async () => {
    setLoading(true)
    setError('')
    try {
      const patient_data = buildPatientData(fields, formState)
      const res = await api.post('/screen', {
        indication,
        patient_data,
        trial_ids: null,
      })
      setResults(res.data.results || [])
      setEngineVersion(res.data.engine_version)
      setScreenedAt(res.data.screened_at)
      setExpanded({})
    } catch (err) {
      setError(err.response?.data?.detail || 'Screening failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <Nav onLogout={onLogout} />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-display text-2xl">Eligibility Screener</h2>
          <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm" onClick={() => window.print()}>
            Export PDF
          </button>
        </div>

        <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-sm text-slate-600">Select indication</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {INDICATIONS.map((item) => (
              <button
                key={item.value}
                className={`rounded-full px-4 py-2 text-sm ${
                  indication === item.value ? 'bg-ink text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                }`}
                onClick={() => setIndication(item.value)}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {fields.map((field) => {
              if (field.type === 'number') {
                const unitOptions = UNIT_OPTIONS[field.name]
                return (
                  <div key={field.name}>
                    <label className="mb-1 block text-sm font-medium text-slate-700">{field.label}</label>
                    <div className="flex gap-2">
                      <input
                        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                        type="number"
                        value={formState[field.name] ?? ''}
                        onChange={(e) => updateValue(field.name, e.target.value)}
                      />
                      {unitOptions ? (
                        <select
                          className="rounded-lg border border-slate-300 px-2 py-2 text-sm"
                          value={formState[`${field.name}_unit`] || unitOptions[0]}
                          onChange={(e) => updateValue(`${field.name}_unit`, e.target.value)}
                        >
                          {unitOptions.map((unit) => (
                            <option key={unit} value={unit}>
                              {unit}
                            </option>
                          ))}
                        </select>
                      ) : field.unit ? (
                        <span className="inline-flex items-center rounded-lg bg-slate-100 px-3 text-xs text-slate-600">{field.unit}</span>
                      ) : null}
                    </div>
                  </div>
                )
              }

              if (field.type === 'boolean') {
                return (
                  <div key={field.name}>
                    <label className="mb-1 block text-sm font-medium text-slate-700">{field.label}</label>
                    <select
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                      value={formState[field.name] ?? ''}
                      onChange={(e) => updateValue(field.name, e.target.value)}
                    >
                      <option value="">Select</option>
                      <option value="true">Yes</option>
                      <option value="false">No</option>
                    </select>
                  </div>
                )
              }

              if (field.type === 'enum') {
                return (
                  <div key={field.name}>
                    <label className="mb-1 block text-sm font-medium text-slate-700">{field.label}</label>
                    <select
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                      value={formState[field.name] ?? ''}
                      onChange={(e) => updateValue(field.name, e.target.value)}
                    >
                      <option value="">Select</option>
                      {(field.options || []).map((option) => (
                        <option key={option} value={option}>
                          {normalizeOption(option)}
                        </option>
                      ))}
                    </select>
                  </div>
                )
              }

              if (field.type === 'date') {
                return (
                  <div key={field.name}>
                    <label className="mb-1 block text-sm font-medium text-slate-700">{field.label}</label>
                    <input
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                      type="date"
                      value={formState[field.name] ?? ''}
                      onChange={(e) => updateValue(field.name, e.target.value)}
                    />
                  </div>
                )
              }

              return (
                <div key={field.name}>
                  <label className="mb-1 block text-sm font-medium text-slate-700">{field.label}</label>
                  <div className="rounded-lg border border-slate-300 p-2">
                    <div className="flex flex-wrap gap-2">
                      {(field.options || []).map((option) => {
                        const selected = (formState[field.name] || []).includes(option)
                        return (
                          <button
                            key={option}
                            type="button"
                            className={`rounded-full px-3 py-1 text-xs ${
                              selected ? 'bg-ink text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                            }`}
                            onClick={() => toggleMultiSelect(field.name, option)}
                          >
                            {normalizeOption(option)}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>

          <div className="mt-4">
            <button
              className="rounded-lg bg-ink px-4 py-2 text-sm text-white disabled:opacity-50"
              onClick={runScreen}
              disabled={loading}
            >
              {loading ? 'Screening...' : 'Screen'}
            </button>
          </div>
        </section>

        {error && (
          <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        )}

        <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between">
            <h3 className="font-display text-xl">Results</h3>
            {screenedAt && (
              <div className="text-xs text-slate-500">
                Screened {new Date(screenedAt).toLocaleString()} | Engine {engineVersion}
              </div>
            )}
          </div>

          {results.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">No results yet.</p>
          ) : (
            <div className="mt-3 space-y-3">
              {results.map((trial) => {
                const isOpen = !!expanded[trial.trial_id]
                return (
                  <div key={trial.trial_id} className="rounded-xl border border-slate-200">
                    <button
                      className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
                      onClick={() => setExpanded((previous) => ({ ...previous, [trial.trial_id]: !isOpen }))}
                    >
                      <div>
                        <div className="font-semibold text-ink">{trial.trial_name || trial.trial_id}</div>
                        <div className="text-xs text-slate-500">Criteria set {trial.version_hash.slice(0, 12)}...</div>
                      </div>
                      <span className={`badge ${STATUS_CLASS[trial.overall] || 'bg-slate-100 text-slate-700'}`}>
                        {STATUS_LABELS[trial.overall] || trial.overall}
                      </span>
                    </button>

                    {isOpen && (
                      <div className="border-t border-slate-200 p-4">
                        <div className="overflow-x-auto">
                          <table className="min-w-full text-sm">
                            <thead className="bg-slate-50 text-left text-slate-600">
                              <tr>
                                <th className="px-3 py-2">Criterion</th>
                                <th className="px-3 py-2">Result</th>
                                <th className="px-3 py-2">Near-miss</th>
                              </tr>
                            </thead>
                            <tbody>
                              {trial.criteria_results.map((row) => (
                                <tr key={row.criterion_id} className="border-t border-slate-100">
                                  <td className="px-3 py-2">{row.raw_text}</td>
                                  <td className="px-3 py-2">
                                    <span className={`badge ${STATUS_CLASS[row.result] || 'bg-slate-100 text-slate-700'}`}>
                                      {STATUS_LABELS[row.result] || row.result}
                                    </span>
                                  </td>
                                  <td className="px-3 py-2 text-slate-600">{formatNearMiss(row.near_miss)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </section>

        <footer className="mt-4 rounded-lg bg-fog px-4 py-3 text-xs text-slate-600">
          Pre-screening aid only. Clinical judgment and direct protocol review required before enrollment decisions.
        </footer>
      </main>
    </div>
  )
}
