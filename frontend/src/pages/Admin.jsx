import { useEffect, useMemo, useState } from 'react'
import { Navigate } from 'react-router-dom'
import Nav from '../components/Nav'
import { useAuth } from '../context/AuthContext'
import api from '../lib/api'

const tabs = ['Users', 'Domain Allowlist', 'Audit Log', 'Stats']
const roles = ['owner', 'pi', 'coordinator', 'collaborator']
const PAGE_SIZE = 50

function toLocalDateTime(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

function summarizeOverall(screenResults) {
  if (!screenResults || typeof screenResults !== 'object') return '-'
  const counts = {}
  Object.values(screenResults).forEach((item) => {
    if (item?.overall) {
      counts[item.overall] = (counts[item.overall] || 0) + 1
    }
  })
  const summary = Object.entries(counts).map(([status, count]) => `${status}:${count}`)
  return summary.length > 0 ? summary.join(', ') : '-'
}

export default function Admin({ onLogout }) {
  const { user } = useAuth()
  const [activeTab, setActiveTab] = useState('Users')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const [users, setUsers] = useState([])
  const [userDrafts, setUserDrafts] = useState({})

  const [domains, setDomains] = useState([])
  const [newDomain, setNewDomain] = useState('')

  const [auditRows, setAuditRows] = useState([])
  const [auditTotal, setAuditTotal] = useState(0)
  const [auditOffset, setAuditOffset] = useState(0)
  const [auditFilters, setAuditFilters] = useState({
    from_date: '',
    to_date: '',
    indication: '',
    user_id: '',
  })
  const [purgeText, setPurgeText] = useState('')

  const [stats, setStats] = useState(null)

  const userChoices = useMemo(
    () => users.map((u) => ({ id: u.id, label: `${u.email} (${u.name})` })),
    [users],
  )

  const loadUsers = async () => {
    const res = await api.get('/admin/users')
    setUsers(res.data)
    setUserDrafts(
      Object.fromEntries(
        res.data.map((row) => [
          row.id,
          {
            role: row.role,
            active: row.active,
          },
        ]),
      ),
    )
  }

  const loadDomains = async () => {
    const res = await api.get('/admin/domain-allowlist')
    setDomains(res.data)
  }

  const loadAudit = async (offset = 0) => {
    const params = {
      limit: PAGE_SIZE,
      offset,
    }
    if (auditFilters.from_date) params.from_date = auditFilters.from_date
    if (auditFilters.to_date) params.to_date = auditFilters.to_date
    if (auditFilters.indication) params.indication = auditFilters.indication
    if (auditFilters.user_id) params.user_id = auditFilters.user_id

    const res = await api.get('/audit', { params })
    setAuditRows(res.data.items || [])
    setAuditTotal(res.data.total || 0)
    setAuditOffset(offset)
  }

  const loadStats = async () => {
    const res = await api.get('/admin/stats')
    setStats(res.data)
  }

  useEffect(() => {
    if (!user || user.role !== 'owner') {
      return
    }

    const loadInitial = async () => {
      setBusy(true)
      setError('')
      try {
        await Promise.all([loadUsers(), loadDomains(), loadAudit(0), loadStats()])
      } catch (err) {
        setError(err.response?.data?.detail || 'Could not load admin data.')
      } finally {
        setBusy(false)
      }
    }
    loadInitial()
  }, [user])

  const setUserDraft = (userId, field, value) => {
    setUserDrafts((prev) => ({
      ...prev,
      [userId]: {
        ...(prev[userId] || {}),
        [field]: value,
      },
    }))
  }

  const saveUser = async (userId) => {
    const draft = userDrafts[userId]
    if (!draft) return

    setBusy(true)
    setError('')
    try {
      await api.patch(`/admin/users/${userId}`, draft)
      await loadUsers()
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to save user changes.')
    } finally {
      setBusy(false)
    }
  }

  const deactivateUser = async (userId) => {
    setUserDraft(userId, 'active', false)
    setBusy(true)
    setError('')
    try {
      await api.patch(`/admin/users/${userId}`, { active: false })
      await loadUsers()
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to deactivate user.')
    } finally {
      setBusy(false)
    }
  }

  const addDomain = async () => {
    const domain = newDomain.trim().toLowerCase()
    if (!domain) return

    setBusy(true)
    setError('')
    try {
      await api.post('/admin/domain-allowlist', { domain })
      setNewDomain('')
      await loadDomains()
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to add domain.')
    } finally {
      setBusy(false)
    }
  }

  const removeDomain = async (allowlistId) => {
    setBusy(true)
    setError('')
    try {
      await api.delete(`/admin/domain-allowlist/${allowlistId}`)
      await loadDomains()
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to remove domain.')
    } finally {
      setBusy(false)
    }
  }

  const runAuditSearch = async () => {
    setBusy(true)
    setError('')
    try {
      await loadAudit(0)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load audit log.')
    } finally {
      setBusy(false)
    }
  }

  const exportAudit = async () => {
    setBusy(true)
    setError('')
    try {
      const payload = {}
      if (auditFilters.from_date) payload.from_date = auditFilters.from_date
      if (auditFilters.to_date) payload.to_date = auditFilters.to_date
      if (auditFilters.indication) payload.indication = auditFilters.indication
      if (auditFilters.user_id) payload.user_id = auditFilters.user_id

      const res = await api.post('/audit/export', payload, { responseType: 'blob' })
      const disposition = res.headers['content-disposition'] || ''
      const match = disposition.match(/filename=\"?([^"]+)\"?/)
      const filename = match?.[1] || 'audit_export.csv'

      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'text/csv' }))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', filename)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)

      await loadAudit(auditOffset)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to export audit log.')
    } finally {
      setBusy(false)
    }
  }

  const purgeAudit = async () => {
    if (purgeText !== 'PURGE') return

    setBusy(true)
    setError('')
    try {
      const params = { confirm: true }
      if (auditFilters.from_date) params.from_date = auditFilters.from_date
      if (auditFilters.to_date) params.to_date = auditFilters.to_date
      if (auditFilters.indication) params.indication = auditFilters.indication
      if (auditFilters.user_id) params.user_id = auditFilters.user_id

      await api.delete('/audit', { params })
      setPurgeText('')
      await loadAudit(0)
      await loadStats()
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to purge audit log.')
    } finally {
      setBusy(false)
    }
  }

  if (!user) {
    return null
  }
  if (user.role !== 'owner') {
    return <Navigate to="/trials" replace />
  }

  return (
    <div>
      <Nav onLogout={onLogout} />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <h2 className="font-display text-2xl">Admin</h2>

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

        {error && <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
        {busy && <div className="mt-4 text-sm text-slate-500">Working...</div>}

        {activeTab === 'Users' && (
          <section className="mt-4 overflow-x-auto rounded-xl border border-slate-200 bg-white">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-slate-600">
                <tr>
                  <th className="px-4 py-3">Email</th>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Role</th>
                  <th className="px-4 py-3">Active</th>
                  <th className="px-4 py-3">Created</th>
                  <th className="px-4 py-3">Domain</th>
                  <th className="px-4 py-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((row) => {
                  const draft = userDrafts[row.id] || { role: row.role, active: row.active }
                  return (
                    <tr className="border-t border-slate-100" key={row.id}>
                      <td className="px-4 py-3">{row.email}</td>
                      <td className="px-4 py-3">{row.name}</td>
                      <td className="px-4 py-3">
                        <select
                          className="rounded-lg border border-slate-300 px-2 py-1"
                          value={draft.role}
                          onChange={(e) => setUserDraft(row.id, 'role', e.target.value)}
                        >
                          {roles.map((role) => (
                            <option key={role} value={role}>
                              {role}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          checked={Boolean(draft.active)}
                          onChange={(e) => setUserDraft(row.id, 'active', e.target.checked)}
                        />
                      </td>
                      <td className="px-4 py-3">{toLocalDateTime(row.created_at)}</td>
                      <td className="px-4 py-3">{row.domain}</td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-2">
                          <button className="rounded-lg border border-slate-300 px-3 py-1" onClick={() => saveUser(row.id)}>
                            Save
                          </button>
                          <button
                            className="rounded-lg border border-rose-300 px-3 py-1 text-rose-700"
                            onClick={() => deactivateUser(row.id)}
                          >
                            Deactivate
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {users.length === 0 && <div className="p-4 text-sm text-slate-500">No users found.</div>}
          </section>
        )}

        {activeTab === 'Domain Allowlist' && (
          <section className="mt-4 space-y-4 rounded-xl border border-slate-200 bg-white p-4">
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              Removing a domain will not deactivate existing users.
            </p>
            <div className="flex flex-wrap gap-2">
              <input
                className="w-80 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                placeholder="example.org"
                value={newDomain}
                onChange={(e) => setNewDomain(e.target.value)}
              />
              <button className="rounded-lg bg-ink px-4 py-2 text-sm text-white" onClick={addDomain}>
                Add Domain
              </button>
            </div>
            <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
              {domains.map((row) => (
                <li className="flex items-center justify-between p-3 text-sm" key={row.id}>
                  <div>
                    <div className="font-medium">{row.domain}</div>
                    <div className="text-xs text-slate-500">Added {toLocalDateTime(row.added_at)}</div>
                  </div>
                  <button
                    className="rounded-lg border border-rose-300 px-3 py-1 text-rose-700"
                    onClick={() => removeDomain(row.id)}
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
            {domains.length === 0 && <div className="text-sm text-slate-500">No domains configured.</div>}
          </section>
        )}

        {activeTab === 'Audit Log' && (
          <section className="mt-4 space-y-4">
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="grid gap-2 md:grid-cols-5">
                <input
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  type="date"
                  value={auditFilters.from_date}
                  onChange={(e) => setAuditFilters((prev) => ({ ...prev, from_date: e.target.value }))}
                />
                <input
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  type="date"
                  value={auditFilters.to_date}
                  onChange={(e) => setAuditFilters((prev) => ({ ...prev, to_date: e.target.value }))}
                />
                <input
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  placeholder="Indication"
                  value={auditFilters.indication}
                  onChange={(e) => setAuditFilters((prev) => ({ ...prev, indication: e.target.value }))}
                />
                <select
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={auditFilters.user_id}
                  onChange={(e) => setAuditFilters((prev) => ({ ...prev, user_id: e.target.value }))}
                >
                  <option value="">All users</option>
                  {userChoices.map((choice) => (
                    <option key={choice.id} value={choice.id}>
                      {choice.label}
                    </option>
                  ))}
                </select>
                <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm" onClick={runAuditSearch}>
                  Apply Filters
                </button>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                <button className="rounded-lg bg-ink px-3 py-2 text-sm text-white" onClick={exportAudit}>
                  Export CSV
                </button>
                <input
                  className="rounded-lg border border-rose-300 px-3 py-2 text-sm"
                  placeholder='Type "PURGE" to confirm'
                  value={purgeText}
                  onChange={(e) => setPurgeText(e.target.value)}
                />
                <button
                  className="rounded-lg border border-rose-300 px-3 py-2 text-sm text-rose-700 disabled:opacity-50"
                  disabled={purgeText !== 'PURGE'}
                  onClick={purgeAudit}
                >
                  Purge
                </button>
              </div>
            </div>

            <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50 text-left text-slate-600">
                  <tr>
                    <th className="px-4 py-3">Timestamp</th>
                    <th className="px-4 py-3">User</th>
                    <th className="px-4 py-3">Indication</th>
                    <th className="px-4 py-3">Overall Results</th>
                    <th className="px-4 py-3">Engine Version</th>
                  </tr>
                </thead>
                <tbody>
                  {auditRows.map((row) => (
                    <tr className="border-t border-slate-100" key={row.id}>
                      <td className="px-4 py-3">{toLocalDateTime(row.timestamp)}</td>
                      <td className="px-4 py-3">{row.user_email || '-'}</td>
                      <td className="px-4 py-3 uppercase">{row.indication}</td>
                      <td className="px-4 py-3">{summarizeOverall(row.screen_results)}</td>
                      <td className="px-4 py-3">{row.engine_version}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {auditRows.length === 0 && <div className="p-4 text-sm text-slate-500">No audit rows found.</div>}
            </div>

            <div className="flex items-center justify-between text-sm text-slate-600">
              <div>
                Showing {auditRows.length} of {auditTotal}
              </div>
              <div className="flex gap-2">
                <button
                  className="rounded-lg border border-slate-300 px-3 py-1 disabled:opacity-50"
                  disabled={auditOffset === 0}
                  onClick={() => loadAudit(Math.max(0, auditOffset - PAGE_SIZE))}
                >
                  Prev
                </button>
                <button
                  className="rounded-lg border border-slate-300 px-3 py-1 disabled:opacity-50"
                  disabled={auditOffset + PAGE_SIZE >= auditTotal}
                  onClick={() => loadAudit(auditOffset + PAGE_SIZE)}
                >
                  Next
                </button>
              </div>
            </div>
          </section>
        )}

        {activeTab === 'Stats' && (
          <section className="mt-4 space-y-4">
            <div className="grid gap-3 md:grid-cols-4">
              <StatCard label="Total Users" value={stats?.total_users ?? 0} />
              <StatCard label="Active Trials" value={stats?.active_trials ?? 0} />
              <StatCard label="Total Screens" value={stats?.total_screens ?? 0} />
              <StatCard label="Screens This Month" value={stats?.screens_this_month ?? 0} />
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <h3 className="font-display text-lg">Users by Role</h3>
                <table className="mt-3 min-w-full text-sm">
                  <tbody>
                    {Object.entries(stats?.users_by_role || {}).map(([role, count]) => (
                      <tr key={role} className="border-t border-slate-100">
                        <td className="px-2 py-2">{role}</td>
                        <td className="px-2 py-2 text-right font-semibold">{count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <h3 className="font-display text-lg">Trials by Status</h3>
                <table className="mt-3 min-w-full text-sm">
                  <tbody>
                    {Object.entries(stats?.trials_by_status || {}).map(([status, count]) => (
                      <tr key={status} className="border-t border-slate-100">
                        <td className="px-2 py-2">{status}</td>
                        <td className="px-2 py-2 text-right font-semibold">{count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        )}
      </main>
    </div>
  )
}

function StatCard({ label, value }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-ink">{value}</div>
    </div>
  )
}
