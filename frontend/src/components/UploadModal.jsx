import { useState } from 'react'
import api from '../lib/api'
import CtgSearchModal from './CtgSearchModal'

export default function UploadModal({ open, onClose, trialId, onUploaded }) {
  const [dragging, setDragging] = useState(false)
  const [file, setFile] = useState(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [selectedCtg, setSelectedCtg] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  if (!open) {
    return null
  }

  const onDrop = (event) => {
    event.preventDefault()
    setDragging(false)
    const dropped = event.dataTransfer.files?.[0]
    if (dropped) setFile(dropped)
  }

  const submit = async () => {
    if (!file) return
    setSubmitting(true)
    try {
      const formData = new FormData()
      formData.append('upload', file)
      await api.post(`/trials/${trialId}/documents`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })

      if (selectedCtg?.nctId) {
        await api.post(`/trials/${trialId}/ctg-snapshot`, { nct_id: selectedCtg.nctId })
      }

      onUploaded()
      onClose()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <div className="fixed inset-0 z-20 flex items-center justify-center bg-ink/40 p-4">
        <div className="w-full max-w-xl rounded-2xl bg-white p-5 shadow-2xl">
          <h3 className="font-display text-xl">Upload Trial Document</h3>
          <p className="mt-1 text-sm text-slate-600">Drag-and-drop PDF or DOCX, then optionally confirm CTG match.</p>

          <div
            className={`mt-4 rounded-xl border-2 border-dashed p-8 text-center ${
              dragging ? 'border-moss bg-moss/5' : 'border-slate-300'
            }`}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <input
              type="file"
              accept=".pdf,.docx"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="mx-auto block"
            />
            <p className="mt-3 text-sm text-slate-500">{file ? file.name : 'Drop file here or browse'}</p>
          </div>

          <div className="mt-4 rounded-lg bg-fog p-3 text-sm">
            CTG Match: {selectedCtg ? `${selectedCtg.nctId} — ${selectedCtg.officialTitle}` : 'Not selected'}
          </div>

          <div className="mt-5 flex flex-wrap justify-between gap-2">
            <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm" onClick={onClose}>
              Cancel
            </button>
            <div className="flex gap-2">
              <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm" onClick={() => setSearchOpen(true)}>
                Search CTG
              </button>
              <button
                className="rounded-lg bg-ink px-4 py-2 text-sm text-white disabled:opacity-50"
                onClick={submit}
                disabled={!file || submitting}
              >
                {submitting ? 'Uploading...' : 'Submit'}
              </button>
            </div>
          </div>
        </div>
      </div>

      <CtgSearchModal
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        onSelect={(match) => {
          setSelectedCtg(match)
          setSearchOpen(false)
        }}
      />
    </>
  )
}
