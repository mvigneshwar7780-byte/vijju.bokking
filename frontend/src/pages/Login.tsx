import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useSession } from '@/store/session'
import { ErrorNote } from '@/components/ui'

export function Login() {
  const navigate = useNavigate()
  const location = useLocation() as { state?: { from?: string } }
  const { signIn, register } = useSession()

  const [mode, setMode] = useState<'signin' | 'register'>('signin')
  const [email, setEmail] = useState('demo@cineai.example')
  const [password, setPassword] = useState('demopass1')
  const [fullName, setFullName] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'signin') await signIn(email, password)
      else await register({ email, password, full_name: fullName })
      navigate(location.state?.from ?? '/', { replace: true })
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-sm space-y-5">
      <div className="text-center">
        <h1 className="text-2xl font-bold tracking-tight">
          {mode === 'signin' ? 'Sign in' : 'Create an account'}
        </h1>
        <p className="mt-1 text-sm text-ink-500">
          {mode === 'signin' ? 'Welcome back.' : 'It takes a moment.'}
        </p>
      </div>

      <form className="card space-y-4 p-5" onSubmit={submit}>
        {mode === 'register' && (
          <div>
            <label className="label" htmlFor="name">Full name</label>
            <input id="name" className="field" required minLength={2}
              value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </div>
        )}
        <div>
          <label className="label" htmlFor="email">Email</label>
          <input id="email" type="email" className="field" required
            value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="password">Password</label>
          <input id="password" type="password" className="field" required minLength={8}
            value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>

        {error != null && <ErrorNote error={error} />}

        <button className="btn-primary w-full" disabled={busy}>
          {busy ? 'Please wait…' : mode === 'signin' ? 'Sign in' : 'Create account'}
        </button>
      </form>

      <p className="text-center text-sm text-ink-500">
        {mode === 'signin' ? "Don't have an account? " : 'Already registered? '}
        <button
          className="text-brand-400 hover:underline"
          onClick={() => { setMode(mode === 'signin' ? 'register' : 'signin'); setError(null) }}
        >
          {mode === 'signin' ? 'Register' : 'Sign in'}
        </button>
      </p>

      {mode === 'signin' && (
        <p className="text-center text-xs text-ink-500">
          Seeded demo account: <span className="font-mono">demo@cineai.example</span> /{' '}
          <span className="font-mono">demopass1</span>
        </p>
      )}
    </div>
  )
}
