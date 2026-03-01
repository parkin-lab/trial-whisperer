import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import Nav from '../components/Nav'
import UploadModal from '../components/UploadModal'
import api from '../lib/api'

const tabs = ['Overview', 'Documents', 'Criteria', 'Amendments', 'Audit']

export default function TrialDetail({ user, onLogout }) {
  const { id } = useParams()
  const [activeTab, setActiveTab] = useState('Overview')
  const [trial, setTrial] = useState(null)
  const [documents, setDocuments] = useState([])
  const [amendments, setAmendments] = useState([])
  const [snapshots, setSnapshots] = useState([])
  const [uploadOpen, setUploadOpen] = useState(false)

  const canUpload = ['owner', 'pi', 'coordinator'].includes(user.role)

  const load = async () => {
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

  useEffect(() => {
    load()
  }, [id])

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
      return <Placeholder text="Phase 3" />
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

    return <Placeholder text="Phase 5" />
  }, [activeTab, trial, snapshots, documents, amendments, canUpload])

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
