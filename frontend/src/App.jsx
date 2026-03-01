import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import api from './lib/api'
import Login from './pages/Login'
import Screener from './pages/Screener'
import Trials from './pages/Trials'
import TrialDetail from './pages/TrialDetail'
import Admin from './pages/Admin'

function ProtectedRoute({ children, user }) {
  if (!user) {
    return <Navigate to="/login" replace />
  }
  return children
}

function OwnerRoute({ children, user }) {
  if (!user) {
    return <Navigate to="/login" replace />
  }
  if (user.role !== 'owner') {
    return <Navigate to="/trials" replace />
  }
  return children
}

export default function App() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    const token = localStorage.getItem('tw_access_token')
    if (!token) {
      setLoading(false)
      return
    }

    api
      .get('/auth/me')
      .then((res) => setUser(res.data))
      .catch(() => {
        localStorage.removeItem('tw_access_token')
        localStorage.removeItem('tw_refresh_token')
      })
      .finally(() => setLoading(false))
  }, [])

  const onLogin = async (email, password) => {
    const res = await api.post('/auth/login', { email, password })
    localStorage.setItem('tw_access_token', res.data.access_token)
    localStorage.setItem('tw_refresh_token', res.data.refresh_token)
    const me = await api.get('/auth/me')
    setUser(me.data)
    navigate('/trials')
  }

  const onLogout = () => {
    localStorage.removeItem('tw_access_token')
    localStorage.removeItem('tw_refresh_token')
    setUser(null)
    navigate('/login')
  }

  if (loading) {
    return <div className="p-8 text-sm">Loading...</div>
  }

  return (
    <Routes>
      <Route path="/login" element={<Login onLogin={onLogin} />} />
      <Route
        path="/trials"
        element={
          <ProtectedRoute user={user}>
            <Trials user={user} onLogout={onLogout} />
          </ProtectedRoute>
        }
      />
      <Route
        path="/screen"
        element={
          <ProtectedRoute user={user}>
            <Screener user={user} onLogout={onLogout} />
          </ProtectedRoute>
        }
      />
      <Route
        path="/trials/:id"
        element={
          <ProtectedRoute user={user}>
            <TrialDetail user={user} onLogout={onLogout} />
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin"
        element={
          <OwnerRoute user={user}>
            <Admin user={user} onLogout={onLogout} />
          </OwnerRoute>
        }
      />
      <Route path="*" element={<Navigate to={user ? '/trials' : '/login'} replace />} />
    </Routes>
  )
}
