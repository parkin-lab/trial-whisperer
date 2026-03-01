import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import api from './lib/api'
import Login from './pages/Login'
import Screener from './pages/Screener'
import Trials from './pages/Trials'
import TrialDetail from './pages/TrialDetail'
import Admin from './pages/Admin'

function ProtectedRoute({ children }) {
  const { user } = useAuth()
  if (!user) {
    return <Navigate to="/login" replace />
  }
  return children
}

function OwnerRoute({ children }) {
  const { user } = useAuth()
  if (!user) {
    return <Navigate to="/login" replace />
  }
  if (user.role !== 'owner') {
    return <Navigate to="/trials" replace />
  }
  return children
}

export default function App() {
  const { user, loading, login, logout } = useAuth()
  const navigate = useNavigate()

  const onLogin = async (email, password) => {
    const res = await api.post('/auth/login', { email, password })
    const me = await api.get('/auth/me', {
      headers: { Authorization: `Bearer ${res.data.access_token}` },
    })
    login(res.data.access_token, me.data, res.data.refresh_token)
    navigate('/trials')
  }

  const onLogout = () => {
    logout()
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
          <ProtectedRoute>
            <Trials onLogout={onLogout} />
          </ProtectedRoute>
        }
      />
      <Route
        path="/screen"
        element={
          <ProtectedRoute>
            <Screener onLogout={onLogout} />
          </ProtectedRoute>
        }
      />
      <Route
        path="/trials/:id"
        element={
          <ProtectedRoute>
            <TrialDetail onLogout={onLogout} />
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin"
        element={
          <OwnerRoute>
            <Admin onLogout={onLogout} />
          </OwnerRoute>
        }
      />
      <Route path="*" element={<Navigate to={user ? '/trials' : '/login'} replace />} />
    </Routes>
  )
}
