import { useState } from 'react'
import api from '../lib/api'

export default function Login({ onLogin }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setInfo('')
    setLoading(true)

    try {
      if (mode === 'register') {
        await api.post('/auth/register', { email, password, name })
        setInfo('Account created. An owner must approve your account before you can log in.')
        setMode('login')
      } else {
        await onLogin(email, password)
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-7 shadow-xl shadow-slate-200/80">
        <h1 className="font-display text-3xl">Trial Whisperer</h1>
        <p className="mt-2 text-sm text-slate-600">Clinical trial eligibility screening portal</p>

        <div className="mt-5 flex gap-2 rounded-lg bg-slate-100 p-1">
          <button
            className={`w-1/2 rounded-md py-2 text-sm ${mode === 'login' ? 'bg-white font-semibold shadow' : ''}`}
            onClick={() => setMode('login')}
          >
            Login
          </button>
          <button
            className={`w-1/2 rounded-md py-2 text-sm ${mode === 'register' ? 'bg-white font-semibold shadow' : ''}`}
            onClick={() => setMode('register')}
          >
            Register
          </button>
        </div>

        <form className="mt-5 space-y-3" onSubmit={submit}>
          {mode === 'register' && (
            <input
              className="w-full rounded-lg border border-slate-300 px-3 py-2"
              placeholder="Full name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          )}
          <input
            className="w-full rounded-lg border border-slate-300 px-3 py-2"
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <input
            className="w-full rounded-lg border border-slate-300 px-3 py-2"
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {error && <div className="rounded-lg bg-red-50 p-2 text-sm text-red-700">{error}</div>}
          {info && <div className="rounded-lg bg-emerald-50 p-2 text-sm text-emerald-700">{info}</div>}
          <button className="w-full rounded-lg bg-ink py-2.5 font-semibold text-white" disabled={loading}>
            {loading ? 'Submitting...' : mode === 'login' ? 'Login' : 'Create account'}
          </button>
        </form>
      </div>
    </div>
  )
}
