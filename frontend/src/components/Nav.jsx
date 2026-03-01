import { Link } from 'react-router-dom'

const roleClass = {
  owner: 'bg-clay/20 text-clay',
  pi: 'bg-moss/20 text-moss',
  coordinator: 'bg-ink/10 text-ink',
  collaborator: 'bg-slate-200 text-slate-700',
}

export default function Nav({ user, onLogout }) {
  return (
    <nav className="sticky top-0 z-10 border-b border-slate-200/80 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-6">
          <Link className="font-display text-xl tracking-tight" to="/trials">
            Trial Whisperer
          </Link>
          <Link className="text-sm font-medium text-slate-600 hover:text-ink" to="/trials">
            Trials
          </Link>
          <Link className="text-sm font-medium text-slate-600 hover:text-ink" to="/screen">
            Screener
          </Link>
        </div>
        <div className="flex items-center gap-3">
          <span className={`badge ${roleClass[user.role] || 'bg-slate-100'}`}>{user.role}</span>
          <span className="hidden text-sm text-slate-700 md:inline">{user.email}</span>
          <button
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
            onClick={onLogout}
          >
            Logout
          </button>
        </div>
      </div>
    </nav>
  )
}
